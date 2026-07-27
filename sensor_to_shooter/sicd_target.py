"""Read a SICD SAR image and extract the footprint + target detections.

The heavy lifting (NITF/SICD parsing, image-to-ground projection) is delegated
to SarPy.  This module adds a small, dependency-light layer on top that turns a
SICD into a set of geo-located detections and an image footprint polygon --
exactly the inputs a Cursor-on-Target emitter needs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy

from sarpy.geometry.point_projection import image_to_ground_geo
from sarpy.io.complex.converter import open_complex
from sarpy.io.complex.sicd_elements.SICD import SICDType

logger = logging.getLogger(__name__)

# Order of the four corners as stored in SICD GeoData.ImageCorners.
CORNER_LABELS: Tuple[str, ...] = ("FRFC", "FRLC", "LRLC", "LRFC")


@dataclass(frozen=True)
class GeoPoint:
    """A WGS-84 geodetic point.  ``hae`` is height above ellipsoid in metres."""

    lat: float
    lon: float
    hae: float = 0.0

    def as_cot_lat_lon(self) -> Tuple[float, float]:
        return self.lat, self.lon


@dataclass
class Footprint:
    """The ground footprint of the SAR image, as an ordered ring of corners."""

    corners: List[GeoPoint]
    labels: Tuple[str, ...] = CORNER_LABELS

    def as_ring(self) -> List[GeoPoint]:
        """Closed ring (first point repeated at the end)."""
        if not self.corners:
            return []
        return list(self.corners) + [self.corners[0]]

    def centroid(self) -> GeoPoint:
        lat = sum(c.lat for c in self.corners) / len(self.corners)
        lon = sum(c.lon for c in self.corners) / len(self.corners)
        hae = sum(c.hae for c in self.corners) / len(self.corners)
        return GeoPoint(lat, lon, hae)


@dataclass
class Detection:
    """A single detected target."""

    row: int
    col: int
    location: GeoPoint
    magnitude: float = 0.0
    snr_db: float = 0.0
    uid: str = ""


@dataclass
class TargetProduct:
    """Everything extracted from a SICD needed to build CoT events."""

    sensor: str
    collect_start: Optional[str]
    footprint: Footprint
    scp: GeoPoint
    detections: List[Detection] = field(default_factory=list)


class SICDTargetExtractor:
    """Extract footprint + detections from a SICD file or ``SICDType``.

    Parameters
    ----------
    sicd
        A parsed :class:`SICDType` metadata structure.
    reader
        Optional SarPy complex reader providing pixel access.  Required only for
        :meth:`detect_targets`; footprint extraction is metadata-only.
    index
        Image index within a multi-image reader.
    """

    def __init__(
        self, sicd: SICDType, reader=None, index: int = 0, owns_reader: bool = False
    ):
        if sicd is None:
            raise ValueError("A SICDType metadata structure is required.")
        self._sicd = sicd
        self._reader = reader
        self._index = index
        # Only readers we opened ourselves (via from_file) should be closed by us.
        self._owns_reader = owns_reader

    # -- construction ----------------------------------------------------

    @classmethod
    def from_file(cls, file_name: str, index: int = 0) -> "SICDTargetExtractor":
        reader = open_complex(file_name)
        sicds = reader.get_sicds_as_tuple()
        if not sicds:
            reader.close()
            raise ValueError("No SICD metadata found in {}".format(file_name))
        return cls(sicds[index], reader=reader, index=index, owns_reader=True)

    def close(self) -> None:
        """Close the underlying reader if this extractor opened it."""
        if self._owns_reader and self._reader is not None:
            try:
                self._reader.close()
            finally:
                self._reader = None

    def __enter__(self) -> "SICDTargetExtractor":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @classmethod
    def from_xml_file(cls, xml_file: str) -> "SICDTargetExtractor":
        """Build a metadata-only extractor from a SICD XML file.

        Useful for footprint extraction and testing without pixel data.
        """
        return cls(SICDType.from_xml_file(xml_file))

    @property
    def sicd(self) -> SICDType:
        return self._sicd

    # -- footprint -------------------------------------------------------

    def extract_footprint(self) -> Footprint:
        geo = getattr(self._sicd, "GeoData", None)
        if geo is None or geo.ImageCorners is None:
            raise ValueError("SICD has no GeoData.ImageCorners; cannot build footprint.")
        arr = geo.ImageCorners.get_array(dtype="float64")  # shape (4, 2) lat/lon
        corners = [GeoPoint(float(lat), float(lon)) for lat, lon in arr]
        return Footprint(corners)

    def scp(self) -> GeoPoint:
        llh = self._sicd.GeoData.SCP.LLH
        return GeoPoint(float(llh.Lat), float(llh.Lon), float(llh.HAE))

    def sensor_name(self) -> str:
        ci = getattr(self._sicd, "CollectionInfo", None)
        if ci is not None:
            for attr in ("CollectorName", "CoreName"):
                val = getattr(ci, attr, None)
                if val:
                    return str(val)
        return "UNKNOWN_SAR"

    def collect_start(self) -> Optional[str]:
        tl = getattr(self._sicd, "Timeline", None)
        if tl is not None and tl.CollectStart is not None:
            return numpy.datetime_as_string(tl.CollectStart, unit="ms") + "Z"
        return None

    # -- projection ------------------------------------------------------

    def image_points_to_geo(
        self, im_points: Sequence[Sequence[float]]
    ) -> List[GeoPoint]:
        """Project ``(row, col)`` image points to geodetic coordinates."""
        pts = numpy.asarray(im_points, dtype="float64").reshape(-1, 2)
        geo = image_to_ground_geo(pts, self._sicd, ordering="latlong")
        return [GeoPoint(float(g[0]), float(g[1]), float(g[2])) for g in geo]

    # -- detection -------------------------------------------------------

    def detect_targets(
        self,
        threshold_sigma: float = 5.0,
        decimation: int = 1,
        max_detections: int = 50,
        min_separation_px: int = 8,
    ) -> List[Detection]:
        """Run a simple global-threshold amplitude detector.

        Reads the (optionally decimated) magnitude image, flags pixels whose
        amplitude exceeds a single global threshold ``mean + threshold_sigma * std``
        computed over the whole scene, groups adjacent hits into targets, and
        projects each target centroid to the ground. This is not a sliding-window
        cell-averaging CFAR; a global threshold is adequate for the low-clutter
        detection this pipeline targets.

        Requires that the extractor was created with pixel access (``from_file``).
        """
        if self._reader is None:
            raise ValueError(
                "detect_targets requires pixel data; construct via from_file()."
            )
        if decimation < 1:
            raise ValueError("decimation must be >= 1")

        data = self._reader[::decimation, ::decimation, self._index]
        magnitude = numpy.abs(data).astype("float64")
        if magnitude.ndim != 2:
            magnitude = magnitude.reshape(magnitude.shape[0], -1)

        detections = self._threshold_and_cluster(
            magnitude,
            threshold_sigma=threshold_sigma,
            min_separation_px=max(1, min_separation_px // decimation),
            max_detections=max_detections,
        )

        results: List[Detection] = []
        for i, (r_dec, c_dec, mag, snr) in enumerate(detections):
            row = int(round(r_dec * decimation))
            col = int(round(c_dec * decimation))
            geo = self.image_points_to_geo([[row, col]])[0]
            results.append(
                Detection(
                    row=row,
                    col=col,
                    location=geo,
                    magnitude=float(mag),
                    snr_db=float(snr),
                    uid="det-{:03d}".format(i),
                )
            )
        return results

    @staticmethod
    def _threshold_and_cluster(
        magnitude: numpy.ndarray,
        threshold_sigma: float,
        min_separation_px: int,
        max_detections: int,
    ) -> List[Tuple[float, float, float, float]]:
        mean = float(magnitude.mean())
        std = float(magnitude.std())
        if std <= 0:
            return []
        threshold = mean + threshold_sigma * std
        mask = magnitude >= threshold
        if not mask.any():
            return []

        try:
            from scipy import ndimage

            labels, count = ndimage.label(mask)
            if count == 0:
                return []
            centroids = ndimage.center_of_mass(magnitude, labels, range(1, count + 1))
            peaks = ndimage.maximum(magnitude, labels, range(1, count + 1))
        except ImportError:  # pragma: no cover - scipy is a hard sarpy dep
            centroids, peaks = SICDTargetExtractor._naive_cluster(
                mask, magnitude, min_separation_px
            )

        results: List[Tuple[float, float, float, float]] = []
        for (r, c), peak in zip(centroids, numpy.atleast_1d(peaks)):
            snr = 20.0 * numpy.log10(peak / mean) if mean > 0 else 0.0
            results.append((float(r), float(c), float(peak), float(snr)))
        results.sort(key=lambda t: t[2], reverse=True)
        return results[:max_detections]

    @staticmethod
    def _naive_cluster(
        mask: numpy.ndarray, magnitude: numpy.ndarray, min_separation_px: int
    ) -> Tuple[List[Tuple[float, float]], List[float]]:
        coords = numpy.argwhere(mask)
        order = numpy.argsort(magnitude[mask])[::-1]
        picked: List[Tuple[float, float]] = []
        peaks: List[float] = []
        for idx in order:
            r, c = coords[idx]
            if all(
                (r - pr) ** 2 + (c - pc) ** 2 >= min_separation_px ** 2
                for pr, pc in picked
            ):
                picked.append((float(r), float(c)))
                peaks.append(float(magnitude[r, c]))
        return picked, peaks

    # -- product ---------------------------------------------------------

    def build_product(
        self, detect: bool = True, **detect_kwargs
    ) -> TargetProduct:
        footprint = self.extract_footprint()
        detections: List[Detection] = []
        if detect and self._reader is not None:
            detections = self.detect_targets(**detect_kwargs)
        return TargetProduct(
            sensor=self.sensor_name(),
            collect_start=self.collect_start(),
            footprint=footprint,
            scp=self.scp(),
            detections=detections,
        )
