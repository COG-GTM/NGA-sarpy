"""ATAK-side CoT handler: turn CoT XML into a hostile-contact map overlay.

An ATAK plugin receiving the pipeline's CoT would create a red hostile marker
for each ``a-h-G`` atom and a red translucent polygon for the ``u-d-f`` SAR
footprint shape.  This module is a transport-agnostic, pure-Python reference
implementation of that logic: it parses the CoT and builds overlay objects that
can be rendered directly (GeoJSON) or mapped onto ATAK ``MapItem`` types by a
thin Java/Kotlin shim.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# CoT datagrams arrive from the network, so guard the stdlib XML parser against
# entity-expansion ("billion laughs") DoS: valid CoT never carries a DTD, so we
# reject any DOCTYPE/ENTITY declaration and cap the payload size.
_MAX_COT_BYTES = 1_000_000
_DTD_RE = re.compile(r"<!\s*(DOCTYPE|ENTITY)\b", re.IGNORECASE)

HOSTILE_AFFILIATION = "h"
DEFAULT_HOSTILE_COLOR = "#FFFF0000"       # opaque red
DEFAULT_FOOTPRINT_STROKE = "#FFFF0000"
DEFAULT_FOOTPRINT_FILL = "#33FF0000"      # translucent red


@dataclass
class MapMarker:
    """A point map item (renders as a 2525C hostile ground symbol in ATAK)."""

    uid: str
    lat: float
    lon: float
    hae: float
    cot_type: str
    callsign: str = ""
    remarks: str = ""
    color: str = DEFAULT_HOSTILE_COLOR
    ce: float = 9999999.0

    @property
    def is_hostile(self) -> bool:
        parts = self.cot_type.split("-")
        return len(parts) >= 2 and parts[0] == "a" and parts[1] == HOSTILE_AFFILIATION


@dataclass
class MapPolygon:
    """A closed polygon overlay (renders the SAR footprint in ATAK)."""

    uid: str
    vertices: List[Tuple[float, float]]  # (lat, lon)
    callsign: str = ""
    stroke_color: str = DEFAULT_FOOTPRINT_STROKE
    fill_color: str = DEFAULT_FOOTPRINT_FILL
    closed: bool = True

    def ring(self) -> List[Tuple[float, float]]:
        if self.closed and self.vertices and self.vertices[0] != self.vertices[-1]:
            return self.vertices + [self.vertices[0]]
        return list(self.vertices)


@dataclass
class HostileContactOverlay:
    """Everything extracted from one or more CoT events, ready to render."""

    markers: List[MapMarker] = field(default_factory=list)
    polygons: List[MapPolygon] = field(default_factory=list)

    def extend(self, other: "HostileContactOverlay") -> None:
        self.markers.extend(other.markers)
        self.polygons.extend(other.polygons)

    def to_geojson(self) -> Dict:
        features: List[Dict] = []
        for poly in self.polygons:
            features.append(
                {
                    "type": "Feature",
                    "id": poly.uid,
                    "geometry": {
                        "type": "Polygon",
                        # GeoJSON coordinates are [lon, lat].
                        "coordinates": [[[lon, lat] for lat, lon in poly.ring()]],
                    },
                    "properties": {
                        "kind": "sar-footprint",
                        "callsign": poly.callsign,
                        "stroke": poly.stroke_color,
                        "fill": poly.fill_color,
                    },
                }
            )
        for marker in self.markers:
            features.append(
                {
                    "type": "Feature",
                    "id": marker.uid,
                    "geometry": {
                        "type": "Point",
                        "coordinates": [marker.lon, marker.lat, marker.hae],
                    },
                    "properties": {
                        "kind": "hostile-contact" if marker.is_hostile else "contact",
                        "cot_type": marker.cot_type,
                        "callsign": marker.callsign,
                        "remarks": marker.remarks,
                        "marker-color": marker.color,
                        "ce": marker.ce,
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}


class CoTOverlayHandler:
    """Parse CoT XML into a :class:`HostileContactOverlay`."""

    def handle(self, xml: Union[str, bytes, ET.Element]) -> HostileContactOverlay:
        overlay = HostileContactOverlay()
        self.handle_into(xml, overlay)
        return overlay

    def handle_into(
        self, xml: Union[str, bytes, ET.Element], overlay: HostileContactOverlay
    ) -> None:
        event = self._as_element(xml)
        if event.tag != "event":
            raise ValueError("Expected a CoT <event> element, got <{}>".format(event.tag))
        cot_type = event.get("type", "")
        detail = event.find("detail")
        polygon = self._extract_polygon(event, detail) if detail is not None else None
        if polygon is not None:
            overlay.polygons.append(polygon)
        else:
            overlay.markers.append(self._extract_marker(event, detail, cot_type))

    # -- parsing helpers -------------------------------------------------

    @staticmethod
    def _as_element(xml: Union[str, bytes, ET.Element]) -> ET.Element:
        if isinstance(xml, ET.Element):
            return xml
        if isinstance(xml, bytes):
            xml = xml.decode("utf-8")
        if len(xml) > _MAX_COT_BYTES:
            raise ValueError("CoT payload exceeds maximum allowed size.")
        if _DTD_RE.search(xml):
            raise ValueError(
                "CoT payload contains a DTD/entity declaration; rejected."
            )
        return ET.fromstring(xml)

    @staticmethod
    def _point(event: ET.Element) -> Tuple[float, float, float]:
        point = event.find("point")
        if point is None:
            raise ValueError("CoT event missing <point>")
        return (
            float(point.get("lat", "0")),
            float(point.get("lon", "0")),
            float(point.get("hae", "0")),
        )

    def _extract_polygon(
        self, event: ET.Element, detail: ET.Element
    ) -> Optional[MapPolygon]:
        polyline = detail.find("./shape/polyline")
        if polyline is None:
            # Not a drawing-shape event.
            return None
        vertices: List[Tuple[float, float]] = []
        for vertex in polyline.findall("vertex"):
            vertices.append((float(vertex.get("lat", "0")), float(vertex.get("lon", "0"))))
        if not vertices:
            for link in polyline.findall("link"):
                point = link.get("point", "")
                parts = point.split(",")
                if len(parts) >= 2:
                    vertices.append((float(parts[0]), float(parts[1])))
        if not vertices:
            return None
        callsign = self._callsign(detail)
        stroke = self._color_hex(detail, "strokeColor", DEFAULT_FOOTPRINT_STROKE)
        fill = self._color_hex(detail, "fillColor", DEFAULT_FOOTPRINT_FILL)
        return MapPolygon(
            uid=event.get("uid", ""),
            vertices=vertices,
            callsign=callsign,
            stroke_color=stroke,
            fill_color=fill,
            closed=polyline.get("closed", "true").lower() == "true",
        )

    def _extract_marker(
        self, event: ET.Element, detail: Optional[ET.Element], cot_type: str
    ) -> MapMarker:
        lat, lon, hae = self._point(event)
        callsign = self._callsign(detail) if detail is not None else ""
        remarks = ""
        ce = 9999999.0
        point = event.find("point")
        if point is not None and point.get("ce"):
            try:
                ce = float(point.get("ce"))
            except ValueError:
                pass
        if detail is not None:
            remarks_el = detail.find("remarks")
            if remarks_el is not None and remarks_el.text:
                remarks = remarks_el.text
        return MapMarker(
            uid=event.get("uid", ""),
            lat=lat,
            lon=lon,
            hae=hae,
            cot_type=cot_type,
            callsign=callsign,
            remarks=remarks,
            ce=ce,
        )

    @staticmethod
    def _callsign(detail: ET.Element) -> str:
        contact = detail.find("contact")
        if contact is not None and contact.get("callsign"):
            return contact.get("callsign", "")
        return ""

    @staticmethod
    def _color_hex(detail: ET.Element, tag: str, default: str) -> str:
        el = detail.find(tag)
        if el is None or el.get("value") is None:
            return default
        try:
            argb = int(el.get("value"))
        except ValueError:
            return default
        if argb < 0:
            argb += 1 << 32
        return "#{:08X}".format(argb & 0xFFFFFFFF)
