from xml.etree import ElementTree as ET

import pytest

from sensor_to_shooter.cot import (
    DRAWING_SHAPE_TYPE,
    HOSTILE_GROUND_TYPE,
    _fmt_time,
    _signed32,
    build_detection_event,
    build_events,
    build_footprint_event,
    event_to_string,
)
from sensor_to_shooter.sicd_target import (
    Detection,
    Footprint,
    GeoPoint,
    TargetProduct,
)


def _footprint():
    return Footprint(
        [GeoPoint(1, 1), GeoPoint(1, 2), GeoPoint(2, 2), GeoPoint(2, 1)]
    )


def _detection():
    return Detection(
        row=10, col=20, location=GeoPoint(1.5, 1.5, 100.0),
        magnitude=42.0, snr_db=12.3, uid="det-000",
    )


def test_detection_event_is_hostile_ground():
    ev = build_detection_event(_detection(), sensor="TESTSAR")
    assert ev.tag == "event"
    assert ev.get("type") == HOSTILE_GROUND_TYPE
    point = ev.find("point")
    assert point.get("lat") == "1.50000000"
    assert point.get("lon") == "1.50000000"
    assert ev.find("./detail/contact") is not None
    remarks = ev.find("./detail/remarks").text
    assert "det-000" in remarks


def test_footprint_event_polygon_vertices():
    ev = build_footprint_event(_footprint(), sensor="TESTSAR")
    assert ev.get("type") == DRAWING_SHAPE_TYPE
    vertices = ev.findall("./detail/shape/polyline/vertex")
    assert len(vertices) == 4
    polyline = ev.find("./detail/shape/polyline")
    assert polyline.get("closed") == "true"


def test_footprint_event_requires_corners():
    with pytest.raises(ValueError):
        build_footprint_event(Footprint([]))


def test_build_events_ordering_and_count():
    product = TargetProduct(
        sensor="TESTSAR",
        collect_start="2022-12-05T18:41:24.051Z",
        footprint=_footprint(),
        scp=GeoPoint(1.5, 1.5),
        detections=[_detection(), _detection()],
    )
    events = build_events(product)
    assert len(events) == 3
    assert events[0].get("type") == DRAWING_SHAPE_TYPE
    assert all(e.get("type") == HOSTILE_GROUND_TYPE for e in events[1:])


def test_build_events_without_footprint():
    product = TargetProduct(
        sensor="S", collect_start=None, footprint=_footprint(),
        scp=GeoPoint(0, 0), detections=[_detection()],
    )
    events = build_events(product, include_footprint=False)
    assert len(events) == 1
    assert events[0].get("type") == HOSTILE_GROUND_TYPE


def test_event_to_string_roundtrip():
    ev = build_detection_event(_detection())
    xml = event_to_string(ev)
    assert xml.startswith("<?xml")
    reparsed = ET.fromstring(xml.split("\n", 1)[1])
    assert reparsed.get("uid") == ev.get("uid")


def test_signed32_conversion():
    assert _signed32(0x33FF0000) == 0x33FF0000
    assert _signed32(0xFFFF0000) == 0xFFFF0000 - (1 << 32)


def test_stale_anchored_to_emission_not_collect_time():
    import datetime as dt

    from sensor_to_shooter.cot import _fmt_time

    # Collection time years in the past.
    collect = dt.datetime(2022, 12, 5, 18, 41, 24, tzinfo=dt.timezone.utc)
    product = TargetProduct(
        sensor="S",
        collect_start="2022-12-05T18:41:24.000Z",
        footprint=_footprint(),
        scp=GeoPoint(0, 0),
        detections=[_detection()],
    )
    events = build_events(product, stale_seconds=300.0)
    now = dt.datetime.now(tz=dt.timezone.utc)
    for ev in events:
        # start stays at the collect time...
        assert ev.get("start") == _fmt_time(collect)
        # ...but stale is ~now + 300s, i.e. in the future, not already expired.
        stale = dt.datetime.fromisoformat(ev.get("stale").replace("Z", "+00:00"))
        assert stale > now
        assert (stale - now).total_seconds() <= 301


def test_fmt_time_has_millis_and_z():
    import datetime as dt

    s = _fmt_time(dt.datetime(2022, 12, 5, 18, 41, 24, 51402, tzinfo=dt.timezone.utc))
    assert s == "2022-12-05T18:41:24.051Z"
