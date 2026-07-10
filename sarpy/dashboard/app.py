"""
A real-time dashboard for SAR-derived imagery and metadata display, with high
resolution JPEG/PDF export.

This is an optional subpackage requiring dependencies beyond the core sarpy
requirements, see `sarpy/dashboard/requirements.txt`. All web functionality
degrades with a clear runtime error when those optional dependencies are missing.

Run the dashboard against a directory of SAR data files:

>>> python -m sarpy.dashboard.app --data-directory <directory> --port 8000

New files appearing in the data directory are pushed to connected clients via
websocket for real-time display.
"""

__classification__ = "UNCLASSIFIED"
__author__ = "Cognition AI"

import argparse
import asyncio
import json
import logging
import os
import re
import tempfile

from sarpy.io.complex.converter import open_complex
from sarpy.visualization import remap
from sarpy.visualization.image_export import create_image_export

try:
    # noinspection PyPackageRequirements
    import fastapi
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, HTMLResponse
except ImportError:
    fastapi = None

try:
    # noinspection PyPackageRequirements
    import uvicorn
except ImportError:
    uvicorn = None

logger = logging.getLogger(__name__)

PREVIEW_PIXEL_LIMIT = 1024
POLL_INTERVAL_SECONDS = 2.0
_FILE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')

_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>SarPy SAR Dashboard</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #10141a; color: #e8e8e8; }
  header { background: #1b2430; padding: 12px 20px; display: flex; align-items: baseline; gap: 14px; }
  header h1 { font-size: 18px; margin: 0; }
  header .status { font-size: 12px; color: #7fd18c; }
  main { display: flex; gap: 16px; padding: 16px; }
  #file-list { width: 280px; min-width: 200px; }
  #file-list ul { list-style: none; padding: 0; margin: 0; }
  #file-list li { padding: 8px 10px; border-radius: 4px; cursor: pointer; word-break: break-all; }
  #file-list li:hover { background: #263242; }
  #file-list li.selected { background: #33507a; }
  #viewer { flex: 1; }
  #preview { max-width: 100%; border: 1px solid #33415a; border-radius: 4px; background: #000; }
  #metadata { font-size: 13px; }
  #metadata table { border-collapse: collapse; }
  #metadata td { padding: 3px 10px 3px 0; vertical-align: top; }
  #metadata td:first-child { color: #8fa8c8; white-space: nowrap; }
  .controls { margin: 10px 0; display: flex; gap: 10px; align-items: center; }
  button, select { background: #33507a; color: #fff; border: none; padding: 8px 14px;
                   border-radius: 4px; cursor: pointer; font-size: 13px; }
  button:hover { background: #40639a; }
  .muted { color: #7d8ca0; }
</style>
</head>
<body>
<header>
  <h1>SarPy SAR Dashboard</h1>
  <span class="status" id="conn-status">connecting&hellip;</span>
</header>
<main>
  <section id="file-list">
    <h3>SAR products</h3>
    <ul id="files"></ul>
  </section>
  <section id="viewer">
    <div class="controls">
      <select id="export-format">
        <option value="jpg">JPG</option>
        <option value="pdf">PDF</option>
      </select>
      <button id="export-btn" disabled>Export high-res</button>
      <span class="muted" id="selected-name"></span>
    </div>
    <img id="preview" alt="" style="display:none"/>
    <div id="metadata"></div>
  </section>
</main>
<script>
let selected = null;

async function refreshFiles() {
  const res = await fetch('api/files');
  const data = await res.json();
  const ul = document.getElementById('files');
  ul.innerHTML = '';
  for (const name of data.files) {
    const li = document.createElement('li');
    li.textContent = name;
    li.className = (name === selected) ? 'selected' : '';
    li.onclick = () => selectFile(name);
    ul.appendChild(li);
  }
}

async function selectFile(name) {
  selected = name;
  document.getElementById('selected-name').textContent = name;
  document.getElementById('export-btn').disabled = false;
  refreshFiles();
  const img = document.getElementById('preview');
  img.style.display = 'block';
  img.src = 'api/files/' + encodeURIComponent(name) + '/preview?t=' + Date.now();
  const res = await fetch('api/files/' + encodeURIComponent(name) + '/metadata');
  const meta = await res.json();
  const table = document.createElement('table');
  for (const [k, v] of Object.entries(meta)) {
    const tr = document.createElement('tr');
    const td1 = document.createElement('td');
    td1.textContent = k;
    const td2 = document.createElement('td');
    td2.textContent = String(v);
    tr.appendChild(td1);
    tr.appendChild(td2);
    table.appendChild(tr);
  }
  const container = document.getElementById('metadata');
  container.innerHTML = '';
  container.appendChild(table);
}

document.getElementById('export-btn').onclick = () => {
  if (!selected) return;
  const fmt = document.getElementById('export-format').value;
  window.location = 'api/files/' + encodeURIComponent(selected) + '/export?format=' + fmt;
};

function connect() {
  const proto = (window.location.protocol === 'https:') ? 'wss://' : 'ws://';
  const ws = new WebSocket(proto + window.location.host + '/ws');
  ws.onopen = () => { document.getElementById('conn-status').textContent = 'live'; };
  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.event === 'new_files') {
      refreshFiles();
      if (!selected && msg.files.length > 0) selectFile(msg.files[0]);
    }
  };
  ws.onclose = () => {
    document.getElementById('conn-status').textContent = 'disconnected - retrying';
    setTimeout(connect, 3000);
  };
}

refreshFiles();
connect();
</script>
</body>
</html>
"""


def _summarize_sicd(sicd):
    """
    Extract a flat dictionary of key metadata fields from a SICD structure.

    Parameters
    ----------
    sicd : sarpy.io.complex.sicd_elements.SICD.SICDType

    Returns
    -------
    dict
    """

    out = {}
    try:
        out['CoreName'] = sicd.CollectionInfo.CoreName
        out['CollectorName'] = sicd.CollectionInfo.CollectorName
    except AttributeError:
        pass
    try:
        out['CollectStart'] = str(sicd.Timeline.CollectStart)
    except AttributeError:
        pass
    try:
        out['Rows'] = sicd.ImageData.NumRows
        out['Columns'] = sicd.ImageData.NumCols
        out['PixelType'] = sicd.ImageData.PixelType
    except AttributeError:
        pass
    try:
        llh = sicd.GeoData.SCP.LLH
        out['SceneCenterLat'] = round(llh.Lat, 6)
        out['SceneCenterLon'] = round(llh.Lon, 6)
    except AttributeError:
        pass
    try:
        out['RowResolution_m'] = round(sicd.Grid.Row.SS, 4)
        out['ColResolution_m'] = round(sicd.Grid.Col.SS, 4)
    except (AttributeError, TypeError):
        pass
    try:
        out['Polarization'] = sicd.ImageFormation.TxRcvPolarizationProc
        out['ImageFormAlgo'] = sicd.ImageFormation.ImageFormAlgo
    except AttributeError:
        pass
    return out


def create_app(data_directory):
    """
    Create the dashboard FastAPI application.

    Parameters
    ----------
    data_directory : str
        The directory containing (and watched for) SAR data files.

    Returns
    -------
    fastapi.FastAPI
    """

    if fastapi is None:
        raise RuntimeError(
            'The sarpy dashboard requires the optional fastapi dependency, which '
            'appears to be missing. Install the dashboard dependencies via '
            '`pip install -r sarpy/dashboard/requirements.txt`.')

    data_directory = os.path.abspath(data_directory)
    if not os.path.isdir(data_directory):
        raise ValueError('data_directory `{}` does not exist'.format(data_directory))

    app = FastAPI(title='SarPy SAR Dashboard')
    app.state.data_directory = data_directory

    def _list_files():
        return sorted(
            entry for entry in os.listdir(data_directory)
            if os.path.isfile(os.path.join(data_directory, entry))
            and not entry.startswith('.'))

    def _resolve_file(file_name):
        if not _FILE_NAME_PATTERN.match(file_name):
            raise HTTPException(status_code=400, detail='Invalid file name')
        full_path = os.path.abspath(os.path.join(data_directory, file_name))
        if os.path.dirname(full_path) != data_directory or not os.path.isfile(full_path):
            raise HTTPException(status_code=404, detail='File not found')
        return full_path

    def _open_reader(full_path):
        try:
            return open_complex(full_path)
        except Exception:
            logger.exception('Unable to open %s as a complex SAR file', full_path)
            raise HTTPException(status_code=422, detail='Unable to open file as complex SAR data')

    @app.get('/', response_class=HTMLResponse)
    async def index():
        return _INDEX_HTML

    @app.get('/api/files')
    async def list_files():
        return {'files': _list_files()}

    @app.get('/api/files/{file_name}/metadata')
    async def file_metadata(file_name: str):
        full_path = _resolve_file(file_name)

        def _fetch_metadata():
            reader = _open_reader(full_path)
            try:
                sicd = reader.get_sicds_as_tuple()[0]
                return _summarize_sicd(sicd)
            finally:
                reader.close()

        return await asyncio.to_thread(_fetch_metadata)

    @app.get('/api/files/{file_name}/preview')
    async def file_preview(file_name: str):
        full_path = _resolve_file(file_name)
        preview_path = os.path.join(
            tempfile.gettempdir(),
            'sarpy_dashboard_preview_{}.jpg'.format(os.path.splitext(file_name)[0]))
        if not os.path.isfile(preview_path) or \
                os.path.getmtime(preview_path) < os.path.getmtime(full_path):
            reader = _open_reader(full_path)
            try:
                await asyncio.to_thread(
                    create_image_export, reader, preview_path,
                    pixel_limit=PREVIEW_PIXEL_LIMIT, output_format='JPEG')
            finally:
                reader.close()
        return FileResponse(preview_path, media_type='image/jpeg')

    @app.get('/api/files/{file_name}/export')
    async def file_export(file_name: str, format: str = 'jpg', dpi: int = 300,
                          remap_name: str = 'nrl'):
        if format not in ('jpg', 'pdf'):
            raise HTTPException(status_code=400, detail='format must be jpg or pdf')
        if not (50 <= dpi <= 2400):
            raise HTTPException(status_code=400, detail='dpi must be between 50 and 2400')
        if remap_name not in remap.get_remap_names():
            raise HTTPException(status_code=400, detail='Unknown remap function')
        remap_function = remap.get_registered_remap(remap_name)
        if remap_function.bit_depth != 8:
            raise HTTPException(
                status_code=400, detail='Only 8-bit remap functions are supported for export')
        full_path = _resolve_file(file_name)
        stem = os.path.splitext(file_name)[0]
        out_name = '{}_export.{}'.format(stem, format)
        out_path = os.path.join(
            tempfile.gettempdir(),
            'sarpy_dashboard_{}_{}_{}dpi.{}'.format(stem, remap_name, dpi, format))
        output_format = 'JPEG' if format == 'jpg' else 'PDF'
        reader = _open_reader(full_path)
        try:
            await asyncio.to_thread(
                create_image_export, reader, out_path,
                remap_function=remap_function,
                output_format=output_format, dpi=dpi)
        finally:
            reader.close()
        media_type = 'image/jpeg' if format == 'jpg' else 'application/pdf'
        return FileResponse(out_path, media_type=media_type, filename=out_name)

    @app.websocket('/ws')
    async def watch_directory(websocket: WebSocket):
        await websocket.accept()
        known = set(_list_files())
        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                current = set(_list_files())
                new_files = sorted(current - known)
                known = current
                if new_files:
                    await websocket.send_text(
                        json.dumps({'event': 'new_files', 'files': new_files}))
        except WebSocketDisconnect:
            pass

    return app


def main(args=None):
    parser = argparse.ArgumentParser(
        description='Run the SarPy real-time SAR dashboard.',
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        '-d', '--data-directory', default=os.getcwd(),
        help='The directory containing (and watched for) SAR data files.\n'
             '(default: current working directory)')
    parser.add_argument(
        '--host', default='127.0.0.1', help='The host to bind. (default: %(default)s)')
    parser.add_argument(
        '-p', '--port', default=8000, type=int, help='The port to bind. (default: %(default)s)')
    parser.add_argument(
        '-v', '--verbose', action='store_true', help='Verbose (level="INFO") logging?')

    args = parser.parse_args(args)

    level = 'INFO' if args.verbose else 'WARNING'
    logging.basicConfig(level=level)

    if uvicorn is None:
        raise RuntimeError(
            'The sarpy dashboard requires the optional uvicorn dependency, which '
            'appears to be missing. Install the dashboard dependencies via '
            '`pip install -r sarpy/dashboard/requirements.txt`.')

    app = create_app(args.data_directory)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == '__main__':
    main()
