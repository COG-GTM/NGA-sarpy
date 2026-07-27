"""Dissemination of CoT events to TAK clients / servers.

Supports the two transports ATAK understands out of the box:

* **UDP multicast/unicast** -- the default SA mesh transport
  (``239.2.3.1:6969`` is the ATAK default SA multicast group), and
* **TCP streaming** -- newline/length-agnostic stream to a TAK Server input.

The sender is deliberately small and dependency-free so it can run on an edge
node next to the sensor.
"""

from __future__ import annotations

import logging
import socket
from contextlib import AbstractContextManager
from typing import Iterable, List, Optional
from xml.etree import ElementTree as ET

from sensor_to_shooter.cot import event_to_string

logger = logging.getLogger(__name__)

DEFAULT_SA_MULTICAST_GROUP = "239.2.3.1"
DEFAULT_SA_PORT = 6969


class CoTSender(AbstractContextManager):
    """Send CoT event XML over UDP or TCP.

    Parameters
    ----------
    host
        Destination IP / multicast group.
    port
        Destination port.
    protocol
        ``"udp"`` (default) or ``"tcp"``.
    multicast_ttl
        TTL for UDP multicast packets.
    """

    def __init__(
        self,
        host: str = DEFAULT_SA_MULTICAST_GROUP,
        port: int = DEFAULT_SA_PORT,
        protocol: str = "udp",
        multicast_ttl: int = 1,
    ):
        proto = protocol.lower()
        if proto not in ("udp", "tcp"):
            raise ValueError("protocol must be 'udp' or 'tcp'")
        self.host = host
        self.port = port
        self.protocol = proto
        self.multicast_ttl = multicast_ttl
        self._sock: Optional[socket.socket] = None

    def __enter__(self) -> "CoTSender":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        if self._sock is not None:
            return
        if self.protocol == "udp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.multicast_ttl
            )
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.host, self.port))
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def send_event(self, event: ET.Element) -> int:
        """Serialize and send a single CoT event. Returns bytes sent."""
        return self.send_raw(event_to_string(event, xml_declaration=False))

    def send_raw(self, xml: str) -> int:
        if self._sock is None:
            self.connect()
        assert self._sock is not None
        payload = xml.encode("utf-8")
        if self.protocol == "udp":
            return self._sock.sendto(payload, (self.host, self.port))
        # TCP streams concatenate events; a trailing newline keeps parsers happy.
        return self._sock.send(payload + b"\n")

    def send_events(self, events: Iterable[ET.Element]) -> List[int]:
        return [self.send_event(e) for e in events]
