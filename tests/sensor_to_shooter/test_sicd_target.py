import pathlib

import pytest

from sensor_to_shooter.sicd_target import (
    Detection,
    Footprint,
    GeoPoint,
    SICDTargetExtractor,
)

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"


def test_extract_footprint_from_xml():
    extractor = SICDTargetExtractor.from_xml_file(str(DATA_DIR / "example.sicd.xml"))
    footprint = extractor.extract_footprint()
    assert isinstance(footprint, Footprint)
    assert len(footprint.corners) == 4
    ring = footprint.as_ring()
    assert len(ring) == 5
    assert ring[0] == ring[-1]


def test_footprint_centroid():
    fp = Footprint(
        [GeoPoint(0, 0), GeoPoint(0, 2), GeoPoint(2, 2), GeoPoint(2, 0)]
    )
    c = fp.centroid()
    assert c.lat == pytest.approx(1.0)
    assert c.lon == pytest.approx(1.0)


def test_metadata_only_detect_raises():
    extractor = SICDTargetExtractor.from_xml_file(str(DATA_DIR / "example.sicd.xml"))
    with pytest.raises(ValueError):
        extractor.detect_targets()


def test_image_points_to_geo():
    extractor = SICDTargetExtractor.from_xml_file(str(DATA_DIR / "example.sicd.xml"))
    pts = extractor.image_points_to_geo([[10, 10], [20, 20]])
    assert len(pts) == 2
    assert all(isinstance(p, GeoPoint) for p in pts)


def test_detect_targets_from_synthetic(synthetic_sicd):
    extractor = SICDTargetExtractor.from_file(synthetic_sicd)
    detections = extractor.detect_targets(threshold_sigma=5.0)
    assert len(detections) >= 2
    for det in detections:
        assert isinstance(det, Detection)
        assert -90 <= det.location.lat <= 90
        assert -180 <= det.location.lon <= 180
    # Strongest detection first.
    assert detections[0].magnitude >= detections[-1].magnitude


def test_build_product_from_synthetic(synthetic_sicd):
    extractor = SICDTargetExtractor.from_file(synthetic_sicd)
    product = extractor.build_product(threshold_sigma=5.0)
    assert product.footprint.corners
    assert product.detections
    assert product.sensor
    assert product.collect_start is not None
