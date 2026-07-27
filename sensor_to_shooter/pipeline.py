"""End-to-end sensor-to-shooter orchestration.

Read SICD -> extract footprint + detections -> build CoT events ->
optionally disseminate to ATAK / TAK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List
from xml.etree import ElementTree as ET

from sensor_to_shooter.cot import build_events, event_to_string
from sensor_to_shooter.dissemination import (
    DEFAULT_SA_MULTICAST_GROUP,
    DEFAULT_SA_PORT,
    CoTSender,
)
from sensor_to_shooter.sicd_target import SICDTargetExtractor, TargetProduct

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    product: TargetProduct
    events: List[ET.Element] = field(default_factory=list)

    @property
    def detection_count(self) -> int:
        return len(self.product.detections)

    def to_xml_strings(self, xml_declaration: bool = True) -> List[str]:
        return [event_to_string(e, xml_declaration=xml_declaration) for e in self.events]


class SensorToShooterPipeline:
    """Configure once, then run against one or more SICD files."""

    def __init__(
        self,
        uid_prefix: str = "sarpy",
        stale_seconds: float = 300.0,
        include_footprint: bool = True,
        threshold_sigma: float = 5.0,
        decimation: int = 1,
        max_detections: int = 50,
    ):
        self.uid_prefix = uid_prefix
        self.stale_seconds = stale_seconds
        self.include_footprint = include_footprint
        self.threshold_sigma = threshold_sigma
        self.decimation = decimation
        self.max_detections = max_detections

    def run_file(self, sicd_file: str, detect: bool = True) -> PipelineResult:
        extractor = SICDTargetExtractor.from_file(sicd_file)
        try:
            return self._run_extractor(extractor, detect=detect)
        finally:
            extractor.close()

    def run_extractor(
        self, extractor: SICDTargetExtractor, detect: bool = True
    ) -> PipelineResult:
        return self._run_extractor(extractor, detect=detect)

    def _run_extractor(
        self, extractor: SICDTargetExtractor, detect: bool
    ) -> PipelineResult:
        product = extractor.build_product(
            detect=detect,
            threshold_sigma=self.threshold_sigma,
            decimation=self.decimation,
            max_detections=self.max_detections,
        )
        events = build_events(
            product,
            uid_prefix=self.uid_prefix,
            stale_seconds=self.stale_seconds,
            include_footprint=self.include_footprint,
        )
        logger.info(
            "Extracted %d detection(s) from sensor %s",
            len(product.detections),
            product.sensor,
        )
        return PipelineResult(product=product, events=events)

    def disseminate(
        self,
        result: PipelineResult,
        host: str = DEFAULT_SA_MULTICAST_GROUP,
        port: int = DEFAULT_SA_PORT,
        protocol: str = "udp",
    ) -> int:
        """Send all events in ``result``; returns number of events sent."""
        with CoTSender(host=host, port=port, protocol=protocol) as sender:
            sender.send_events(result.events)
        return len(result.events)
