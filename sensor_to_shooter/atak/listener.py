"""A minimal UDP CoT listener that renders incoming events as an overlay.

Mirrors what a TAK client's SA input does: bind the SA port (optionally joining
the multicast group), parse each datagram as CoT, and merge the parsed markers
and polygons into a running :class:`HostileContactOverlay`.
"""

from __future__ import annotations

import logging
import socket
import struct
from typing import Callable, Optional

from sensor_to_shooter.atak.cot_handler import CoTOverlayHandler, HostileContactOverlay

logger = logging.getLogger(__name__)

DEFAULT_SA_MULTICAST_GROUP = "239.2.3.1"
DEFAULT_SA_PORT = 6969


class CoTListener:
    """Receive CoT over UDP and accumulate an overlay.

    Parameters
    ----------
    group
        Multicast group to join (``None`` for plain unicast).
    port
        UDP port to bind.
    bind_host
        Local interface to bind (``""`` = all).
    """

    def __init__(
        self,
        group: Optional[str] = DEFAULT_SA_MULTICAST_GROUP,
        port: int = DEFAULT_SA_PORT,
        bind_host: str = "",
    ):
        self.group = group
        self.port = port
        self.bind_host = bind_host
        self.handler = CoTOverlayHandler()
        self._sock: Optional[socket.socket] = None

    def __enter__(self) -> "CoTListener":
        self.bind()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def bind(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_host, self.port))
        if self.group:
            mreq = struct.pack(
                "4sl", socket.inet_aton(self.group), socket.INADDR_ANY
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def receive_into(
        self,
        overlay: HostileContactOverlay,
        count: int = 1,
        timeout: Optional[float] = None,
        on_event: Optional[Callable[[HostileContactOverlay], None]] = None,
    ) -> HostileContactOverlay:
        """Receive ``count`` datagrams, merging each into ``overlay``."""
        if self._sock is None:
            self.bind()
        assert self._sock is not None
        if timeout is not None:
            self._sock.settimeout(timeout)
        received = 0
        while received < count:
            data, _addr = self._sock.recvfrom(65535)
            received += 1
            try:
                parsed = self.handler.handle(data)
            except Exception as exc:  # noqa: BLE001 - tolerate malformed traffic
                logger.warning("Dropping malformed CoT datagram: %s", exc)
                continue
            overlay.extend(parsed)
            if on_event is not None:
                on_event(parsed)
        return overlay
