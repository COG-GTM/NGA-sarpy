"""Command-line entry point for the sensor-to-shooter pipeline.

Examples
--------
Print CoT events for a SICD to stdout::

    python -m sensor_to_shooter.cli image.nitf

Detect targets and multicast them to the ATAK SA mesh::

    python -m sensor_to_shooter.cli image.nitf --send \
        --host 239.2.3.1 --port 6969 --protocol udp
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from sensor_to_shooter.dissemination import (
    DEFAULT_SA_MULTICAST_GROUP,
    DEFAULT_SA_PORT,
)
from sensor_to_shooter.pipeline import SensorToShooterPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensor_to_shooter",
        description="Read a SICD SAR image and emit Cursor-on-Target events.",
    )
    parser.add_argument("sicd", help="Path to a SICD (NITF) file.")
    parser.add_argument(
        "--no-detect",
        action="store_true",
        help="Skip target detection; emit footprint only.",
    )
    parser.add_argument(
        "--no-footprint",
        action="store_true",
        help="Skip the footprint polygon event.",
    )
    parser.add_argument(
        "--threshold-sigma",
        type=float,
        default=5.0,
        help="Detection threshold in std-devs above the mean (default: 5.0).",
    )
    parser.add_argument(
        "--decimation",
        type=int,
        default=1,
        help="Decimation factor when reading pixels (default: 1).",
    )
    parser.add_argument(
        "--max-detections",
        type=int,
        default=50,
        help="Maximum number of detections to emit (default: 50).",
    )
    parser.add_argument(
        "--stale-seconds",
        type=float,
        default=300.0,
        help="CoT stale time in seconds (default: 300).",
    )
    parser.add_argument(
        "--uid-prefix", default="sarpy", help="Prefix for generated CoT UIDs."
    )
    parser.add_argument(
        "--send", action="store_true", help="Disseminate events over the network."
    )
    parser.add_argument("--host", default=DEFAULT_SA_MULTICAST_GROUP)
    parser.add_argument("--port", type=int, default=DEFAULT_SA_PORT)
    parser.add_argument("--protocol", choices=("udp", "tcp"), default="udp")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable info logging."
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pipeline = SensorToShooterPipeline(
        uid_prefix=args.uid_prefix,
        stale_seconds=args.stale_seconds,
        include_footprint=not args.no_footprint,
        threshold_sigma=args.threshold_sigma,
        decimation=args.decimation,
        max_detections=args.max_detections,
    )
    result = pipeline.run_file(args.sicd, detect=not args.no_detect)

    for xml in result.to_xml_strings():
        print(xml)

    print(
        "# sensor={} detections={} events={}".format(
            result.product.sensor, result.detection_count, len(result.events)
        ),
        file=sys.stderr,
    )

    if args.send:
        sent = pipeline.disseminate(
            result, host=args.host, port=args.port, protocol=args.protocol
        )
        print(
            "# sent {} event(s) via {} to {}:{}".format(
                sent, args.protocol, args.host, args.port
            ),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
