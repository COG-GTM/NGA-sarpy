"""Sensor-to-shooter pipeline built on SarPy.

Reads a SICD SAR image, extracts the image footprint and detected target
coordinates, and emits them as Cursor-on-Target (CoT) XML events suitable for
dissemination to ATAK / TAK clients.

Public entry points
-------------------
* :class:`sensor_to_shooter.sicd_target.SICDTargetExtractor` -- read a SICD and
  extract footprint + detections.
* :func:`sensor_to_shooter.cot.build_detection_event` -- render a single
  detection as a hostile-contact CoT event.
* :func:`sensor_to_shooter.cot.build_footprint_event` -- render the SAR image
  footprint as a CoT polygon (drawing shape) event.
* :class:`sensor_to_shooter.pipeline.SensorToShooterPipeline` -- orchestrate the
  full read -> extract -> emit -> disseminate flow.
"""

from sensor_to_shooter.sicd_target import (
    Detection,
    Footprint,
    GeoPoint,
    SICDTargetExtractor,
    TargetProduct,
)
from sensor_to_shooter.cot import (
    build_detection_event,
    build_footprint_event,
    build_events,
)
from sensor_to_shooter.pipeline import SensorToShooterPipeline

__all__ = [
    "Detection",
    "Footprint",
    "GeoPoint",
    "SICDTargetExtractor",
    "TargetProduct",
    "build_detection_event",
    "build_footprint_event",
    "build_events",
    "SensorToShooterPipeline",
]
