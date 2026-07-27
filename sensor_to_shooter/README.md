# Sensor-to-Shooter Pipeline (SAR → CoT → ATAK)

A small, dependency-light service that turns an NGA **SICD** SAR image into
**Cursor-on-Target (CoT)** events and disseminates them to **ATAK / TAK**
clients, plus an ATAK-side handler that renders those events as a
hostile-contact overlay with the SAR image footprint drawn as a polygon.

```
 SICD (NITF)                                        ATAK / TAK client
     │                                                     ▲
     ▼                                                     │
 SICDTargetExtractor ──► TargetProduct ──► CoT events ──► CoTSender ──► UDP/TCP
 (footprint + CFAR      (footprint,        (a-h-G hostile   (SA mesh
  detections via         detections,        contacts +       multicast
  sarpy projection)      sensor meta)        u-d-f polygon)   or TCP)
                                                     │
                                                     ▼  (receiving side)
                                            CoTListener ──► CoTOverlayHandler
                                                          ──► HostileContactOverlay
                                                          ──► GeoJSON / ATAK MapItems
```

## Components

| Module | Responsibility |
| --- | --- |
| `sicd_target.py` | Open a SICD with SarPy, extract the `GeoData.ImageCorners` footprint, run a cell-averaging CFAR-style amplitude detector, and project detections to WGS-84 via `image_to_ground_geo`. |
| `cot.py` | Build MITRE CoT 2.0 XML: `a-h-G` hostile-ground contacts per detection and a `u-d-f` drawing-shape polygon for the footprint. |
| `dissemination.py` | `CoTSender` — emit events over UDP (SA multicast `239.2.3.1:6969` by default) or a TCP stream to a TAK Server input. |
| `pipeline.py` | `SensorToShooterPipeline` — orchestrate read → extract → build → disseminate. |
| `cli.py` | `python -m sensor_to_shooter.cli` command-line entry point. |
| `atak/cot_handler.py` | ATAK-side handler: parse CoT into `MapMarker` (hostile symbol) and `MapPolygon` (footprint) overlay objects; export GeoJSON. |
| `atak/listener.py` | `CoTListener` — bind the SA UDP port (optionally joining the multicast group) and render incoming CoT into an overlay. |

## CLI usage

```bash
# Print CoT events for a SICD to stdout
python -m sensor_to_shooter.cli image.nitf

# Detect targets and multicast to the ATAK SA mesh
python -m sensor_to_shooter.cli image.nitf --send \
    --host 239.2.3.1 --port 6969 --protocol udp -v

# Footprint only (no detection), streamed to a TAK Server over TCP
python -m sensor_to_shooter.cli image.nitf --no-detect --send \
    --protocol tcp --host takserver.mil --port 8087
```

## Library usage

```python
from sensor_to_shooter import SensorToShooterPipeline

pipeline = SensorToShooterPipeline(threshold_sigma=5.0)
result = pipeline.run_file("image.nitf")
for xml in result.to_xml_strings():
    print(xml)
pipeline.disseminate(result, host="239.2.3.1", port=6969, protocol="udp")
```

Receiving / rendering side:

```python
from sensor_to_shooter.atak.cot_handler import CoTOverlayHandler, HostileContactOverlay

overlay = HostileContactOverlay()
handler = CoTOverlayHandler()
for xml in result.to_xml_strings():
    handler.handle_into(xml, overlay)

geojson = overlay.to_geojson()   # ready for a web map, or map to ATAK MapItems
```

## ATAK integration notes

`CoTOverlayHandler` is a transport-agnostic, pure-Python reference of the logic
an ATAK plugin performs on receipt. Mapping the overlay objects onto ATAK
`MapItem` types in a Java/Kotlin plugin:

* **`MapMarker`** (`a-h-G`) → a `com.atakmap.android.maps.Marker` with a
  MIL-STD-2525C hostile-ground icon; `callsign`, `remarks`, and `ce` map to the
  marker's metadata and the "SAR detection" details pane.
* **`MapPolygon`** (`u-d-f`) → a `com.atakmap.android.drawing.mvp` /
  `DrawingShape` with the footprint vertices; `stroke_color` / `fill_color`
  come straight from the CoT `strokeColor` / `fillColor` (ARGB) values.

Colours are carried on the wire as signed 32-bit decimal integers (ATAK
convention) and converted back to `#AARRGGBB` hex by the handler.
