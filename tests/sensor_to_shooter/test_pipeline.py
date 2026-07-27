import threading

from sensor_to_shooter.atak.cot_handler import HostileContactOverlay
from sensor_to_shooter.atak.listener import CoTListener
from sensor_to_shooter.dissemination import CoTSender
from sensor_to_shooter.pipeline import SensorToShooterPipeline


def test_pipeline_run_file(synthetic_sicd):
    pipeline = SensorToShooterPipeline(threshold_sigma=5.0)
    result = pipeline.run_file(synthetic_sicd)
    assert result.detection_count >= 2
    # footprint + one event per detection
    assert len(result.events) == result.detection_count + 1
    xmls = result.to_xml_strings()
    assert all(x.startswith("<?xml") for x in xmls)


def test_pipeline_no_footprint(synthetic_sicd):
    pipeline = SensorToShooterPipeline(include_footprint=False, threshold_sigma=5.0)
    result = pipeline.run_file(synthetic_sicd)
    assert len(result.events) == result.detection_count


def test_udp_roundtrip_loopback(synthetic_sicd):
    """Emit via UDP unicast to loopback and re-parse on the ATAK side."""
    pipeline = SensorToShooterPipeline(threshold_sigma=5.0)
    result = pipeline.run_file(synthetic_sicd)
    n_events = len(result.events)

    listener = CoTListener(group=None, port=0, bind_host="127.0.0.1")
    listener.bind()
    port = listener._sock.getsockname()[1]

    overlay = HostileContactOverlay()

    def _receive():
        listener.receive_into(overlay, count=n_events, timeout=10.0)

    thread = threading.Thread(target=_receive)
    thread.start()

    with CoTSender(host="127.0.0.1", port=port, protocol="udp") as sender:
        sender.send_events(result.events)

    thread.join(timeout=15.0)
    listener.close()

    assert len(overlay.polygons) == 1
    assert len(overlay.markers) == result.detection_count
    assert all(m.is_hostile for m in overlay.markers)


def test_tcp_roundtrip_loopback():
    import socket

    from xml.etree import ElementTree as ET

    from sensor_to_shooter.cot import build_footprint_event
    from sensor_to_shooter.sicd_target import Footprint, GeoPoint

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    # A footprint with many vertices exercises the full sendall() path.
    big_footprint = Footprint(
        [GeoPoint(i * 1e-4, i * 1e-4) for i in range(2000)]
    )
    event = build_footprint_event(big_footprint)
    expected = len(ET.tostring(event, encoding="unicode").encode("utf-8")) + 1  # +\n

    received = {"data": b""}

    def _serve():
        conn, _ = server.accept()
        while len(received["data"]) < expected:
            chunk = conn.recv(65535)
            if not chunk:
                break
            received["data"] += chunk
        conn.close()

    thread = threading.Thread(target=_serve)
    thread.start()

    with CoTSender(host="127.0.0.1", port=port, protocol="tcp") as sender:
        sent = sender.send_event(event)

    thread.join(timeout=10.0)
    server.close()

    assert sent == expected
    assert len(received["data"]) == expected
    parsed = ET.fromstring(received["data"].decode("utf-8").strip())
    assert parsed.get("type") == event.get("type")
    assert len(parsed.findall("./detail/shape/polyline/vertex")) == 2000
