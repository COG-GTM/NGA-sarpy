from sensor_to_shooter.atak.cot_handler import CoTOverlayHandler, HostileContactOverlay
from sensor_to_shooter.cot import build_detection_event, build_footprint_event
from sensor_to_shooter.sicd_target import Detection, Footprint, GeoPoint


def _footprint():
    return Footprint(
        [GeoPoint(1, 1), GeoPoint(1, 2), GeoPoint(2, 2), GeoPoint(2, 1)]
    )


def _detection():
    return Detection(
        row=10, col=20, location=GeoPoint(1.5, 1.5, 100.0),
        magnitude=42.0, snr_db=12.3, uid="det-000",
    )


def test_handle_hostile_marker():
    ev = build_detection_event(_detection(), sensor="TESTSAR")
    overlay = CoTOverlayHandler().handle(ev)
    assert len(overlay.markers) == 1
    assert not overlay.polygons
    marker = overlay.markers[0]
    assert marker.is_hostile
    assert marker.lat == 1.5
    assert marker.callsign


def test_handle_footprint_polygon():
    ev = build_footprint_event(_footprint(), sensor="TESTSAR")
    overlay = CoTOverlayHandler().handle(ev)
    assert len(overlay.polygons) == 1
    assert not overlay.markers
    poly = overlay.polygons[0]
    assert len(poly.vertices) == 4
    ring = poly.ring()
    assert ring[0] == ring[-1]
    # Colours round-trip back to ARGB hex.
    assert poly.stroke_color.startswith("#")
    assert poly.fill_color.startswith("#")


def test_handle_from_xml_string():
    xml = "<event version='2.0' uid='x' type='a-h-G'>" \
          "<point lat='5' lon='6' hae='7' ce='30'/>" \
          "<detail><contact callsign='TGT'/></detail></event>"
    overlay = CoTOverlayHandler().handle(xml)
    assert overlay.markers[0].lat == 5.0
    assert overlay.markers[0].callsign == "TGT"


def test_overlay_to_geojson():
    handler = CoTOverlayHandler()
    overlay = HostileContactOverlay()
    handler.handle_into(build_footprint_event(_footprint()), overlay)
    handler.handle_into(build_detection_event(_detection()), overlay)

    gj = overlay.to_geojson()
    assert gj["type"] == "FeatureCollection"
    kinds = {f["properties"]["kind"] for f in gj["features"]}
    assert "sar-footprint" in kinds
    assert "hostile-contact" in kinds
    for feat in gj["features"]:
        if feat["geometry"]["type"] == "Polygon":
            # GeoJSON is [lon, lat]; footprint lon values are ~1-2.
            ring = feat["geometry"]["coordinates"][0]
            assert ring[0] == ring[-1]
        else:
            lon, lat = feat["geometry"]["coordinates"][:2]
            assert lat == 1.5 and lon == 1.5


def test_non_event_raises():
    import pytest

    with pytest.raises(ValueError):
        CoTOverlayHandler().handle("<notanevent/>")
