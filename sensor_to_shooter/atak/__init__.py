"""ATAK-side CoT reception and rendering helpers.

This subpackage models what a TAK client (e.g. an ATAK plugin) does with the
CoT produced by the sensor-to-shooter pipeline: parse hostile-contact atoms and
the SAR footprint drawing shape into map overlay objects, and expose them as
GeoJSON for rendering.
"""

from sensor_to_shooter.atak.cot_handler import (
    CoTOverlayHandler,
    HostileContactOverlay,
    MapMarker,
    MapPolygon,
)

__all__ = [
    "CoTOverlayHandler",
    "HostileContactOverlay",
    "MapMarker",
    "MapPolygon",
]
