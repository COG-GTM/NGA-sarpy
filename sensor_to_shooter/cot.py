"""Cursor-on-Target (CoT) XML event generation.

Produces MITRE CoT 2.0 events compatible with ATAK / TAK Server:

* a **hostile ground contact** (``a-h-G``) event per detection, and
* a **drawing-shape polygon** (``u-d-f``) event for the SAR image footprint.

References
----------
* MITRE, *Cursor-on-Target Message Router User's Guide* (event/point schema).
* ATAK drawing-shape ``u-d-f`` ``<shape><polyline>`` detail structure.
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable, List, Optional
from xml.etree import ElementTree as ET

from sensor_to_shooter.sicd_target import Detection, Footprint, GeoPoint, TargetProduct

COT_VERSION = "2.0"
HOSTILE_GROUND_TYPE = "a-h-G"          # atom, hostile, ground
DRAWING_SHAPE_TYPE = "u-d-f"           # user, drawing, free-form (polygon)
DEFAULT_HOW = "m-g"                    # machine, GPS-derived

# ARGB colours used by ATAK, sent on the wire as signed 32-bit decimal ints.
_RED_ARGB = 0xFFFF0000        # opaque red
_RED_FILL_ARGB = 0x33FF0000   # translucent red


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def _fmt_time(value: _dt.datetime) -> str:
    """CoT timestamps are ISO-8601 UTC with millisecond precision and 'Z'."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    value = value.astimezone(_dt.timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(value.microsecond // 1000)


def _signed32(argb: int) -> int:
    """Convert an unsigned 0xAARRGGBB value to the signed int ATAK expects."""
    return argb - (1 << 32) if argb >= (1 << 31) else argb


def _base_event(
    uid: str,
    cot_type: str,
    point: GeoPoint,
    *,
    start: Optional[_dt.datetime] = None,
    stale_seconds: float = 300.0,
    how: str = DEFAULT_HOW,
    ce: float = 9999999.0,
    le: float = 9999999.0,
) -> ET.Element:
    start = start or _utc_now()
    stale = start + _dt.timedelta(seconds=stale_seconds)
    event = ET.Element(
        "event",
        {
            "version": COT_VERSION,
            "uid": uid,
            "type": cot_type,
            "how": how,
            "time": _fmt_time(_utc_now()),
            "start": _fmt_time(start),
            "stale": _fmt_time(stale),
        },
    )
    ET.SubElement(
        event,
        "point",
        {
            "lat": "{:.8f}".format(point.lat),
            "lon": "{:.8f}".format(point.lon),
            "hae": "{:.2f}".format(point.hae),
            "ce": "{:.1f}".format(ce),
            "le": "{:.1f}".format(le),
        },
    )
    return event


def build_detection_event(
    detection: Detection,
    *,
    sensor: str = "SAR",
    uid_prefix: str = "sarpy",
    callsign: Optional[str] = None,
    start: Optional[_dt.datetime] = None,
    stale_seconds: float = 300.0,
    ce: Optional[float] = None,
) -> ET.Element:
    """Render a single detection as a hostile-ground-contact CoT event."""
    uid = "{}.{}".format(uid_prefix, detection.uid or "det")
    call = callsign or "{} {}".format(sensor, detection.uid or "TGT")
    circular_error = ce if ce is not None else 30.0
    event = _base_event(
        uid,
        HOSTILE_GROUND_TYPE,
        detection.location,
        start=start,
        stale_seconds=stale_seconds,
        ce=circular_error,
    )
    detail = ET.SubElement(event, "detail")
    ET.SubElement(detail, "contact", {"callsign": call})
    ET.SubElement(detail, "__group", {"name": "Red", "role": "Team Member"})
    ET.SubElement(
        detail,
        "remarks",
        {"source": "SarPy sensor-to-shooter", "sensor": sensor},
    ).text = (
        "SAR detection {} | pixel=({},{}) | mag={:.1f} | snr={:.1f} dB".format(
            detection.uid, detection.row, detection.col,
            detection.magnitude, detection.snr_db,
        )
    )
    ET.SubElement(detail, "precisionlocation", {"altsrc": "DTED0", "geopointsrc": "SICD"})
    return event


def build_footprint_event(
    footprint: Footprint,
    *,
    uid_prefix: str = "sarpy",
    sensor: str = "SAR",
    callsign: str = "SAR Footprint",
    start: Optional[_dt.datetime] = None,
    stale_seconds: float = 300.0,
) -> ET.Element:
    """Render the SAR image footprint as an ATAK drawing-shape polygon event."""
    if not footprint.corners:
        raise ValueError("Footprint has no corners.")
    centroid = footprint.centroid()
    uid = "{}.footprint".format(uid_prefix)
    event = _base_event(
        uid,
        DRAWING_SHAPE_TYPE,
        centroid,
        start=start,
        stale_seconds=stale_seconds,
        how="h-g-i-g-o",
    )
    detail = ET.SubElement(event, "detail")
    shape = ET.SubElement(detail, "shape")
    polyline = ET.SubElement(
        shape,
        "polyline",
        {
            "closed": "true",
            "fillColor": str(_signed32(_RED_FILL_ARGB)),
            "color": str(_signed32(_RED_ARGB)),
        },
    )
    for corner in footprint.corners:
        ET.SubElement(
            polyline,
            "vertex",
            {"lat": "{:.8f}".format(corner.lat), "lon": "{:.8f}".format(corner.lon)},
        )
    ET.SubElement(detail, "strokeColor", {"value": str(_signed32(_RED_ARGB))})
    ET.SubElement(detail, "strokeWeight", {"value": "3.0"})
    ET.SubElement(detail, "fillColor", {"value": str(_signed32(_RED_FILL_ARGB))})
    ET.SubElement(detail, "contact", {"callsign": callsign})
    ET.SubElement(detail, "labels_on", {"value": "true"})
    ET.SubElement(
        detail,
        "remarks",
        {"source": "SarPy sensor-to-shooter"},
    ).text = "{} image footprint".format(sensor)
    return event


def build_events(
    product: TargetProduct,
    *,
    uid_prefix: str = "sarpy",
    stale_seconds: float = 300.0,
    include_footprint: bool = True,
) -> List[ET.Element]:
    """Build all CoT events for a :class:`TargetProduct`.

    The footprint polygon comes first, followed by one hostile-contact event
    per detection.
    """
    start = None
    if product.collect_start:
        try:
            start = _dt.datetime.fromisoformat(product.collect_start.replace("Z", "+00:00"))
        except ValueError:
            start = None

    events: List[ET.Element] = []
    if include_footprint:
        events.append(
            build_footprint_event(
                product.footprint,
                uid_prefix=uid_prefix,
                sensor=product.sensor,
                start=start,
                stale_seconds=stale_seconds,
            )
        )
    for det in product.detections:
        events.append(
            build_detection_event(
                det,
                sensor=product.sensor,
                uid_prefix=uid_prefix,
                start=start,
                stale_seconds=stale_seconds,
            )
        )
    return events


def event_to_string(event: ET.Element, *, xml_declaration: bool = True) -> str:
    body = ET.tostring(event, encoding="unicode")
    if xml_declaration:
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body
    return body


def events_to_strings(
    events: Iterable[ET.Element], *, xml_declaration: bool = True
) -> List[str]:
    return [event_to_string(e, xml_declaration=xml_declaration) for e in events]
