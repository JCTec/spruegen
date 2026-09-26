"""Local web app: `spruegen gui` -> http://127.0.0.1:8765 (files never leave this machine)."""

from __future__ import annotations

import atexit
import re
import shutil
import socket
import threading
import uuid
import webbrowser
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from spruegen.gui import service
from spruegen.gui.service import GuiError, Session

STATIC = Path(__file__).parent / "static"
ROOT = Path.home() / ".spruegen" / "gui"
SERVE_SUFFIXES = {".stl", ".png", ".json", ".html"}
MAX_UPLOAD = 200 * 1024 * 1024

app = FastAPI(title="spruegen", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
SESSIONS: dict[str, Session] = {}
_LOCK = threading.Lock()


@app.exception_handler(GuiError)
async def _gui_error(_, exc: GuiError):
    return JSONResponse(status_code=400, content={"error": str(exc)})


def _session(sid: str) -> Session:
    s = SESSIONS.get(sid)
    if s is None:
        raise HTTPException(404, "Session not found — load the ring again.")
    return s


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/presets")
def presets():
    return service.preset_list()


@app.post("/api/session")
def new_session(file: UploadFile = File(...)):
    raw_name = Path(file.filename or "ring.stl").name
    if not raw_name.lower().endswith(".stl"):
        raise GuiError("Please load an .stl file.")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name) or "ring.stl"
    sid = uuid.uuid4().hex[:12]
    sdir = ROOT / sid
    sdir.mkdir(parents=True, exist_ok=True)
    stl = sdir / safe
    size = 0
    with open(stl, "wb") as f:
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                shutil.rmtree(sdir, ignore_errors=True)
                raise GuiError("File too large (over 200 MB).")
            f.write(chunk)
    try:
        info = service.load_summary(stl)
    except GuiError:
        shutil.rmtree(sdir, ignore_errors=True)
        raise
    sess = Session(sid=sid, dir=sdir, name=raw_name, stl=stl, info=info)
    with _LOCK:
        SESSIONS[sid] = sess
    return {"sid": sid, "name": raw_name, "mesh_url": safe, **info}


@app.post("/api/{sid}/analyze")
def analyze(sid: str, config: dict = Body(default={})):
    return service.analyze(_session(sid), config)


@app.post("/api/{sid}/generate")
def generate(sid: str, config: dict = Body(default={})):
    return service.generate(_session(sid), config)


@app.get("/api/{sid}/file/{name:path}")
def session_file(sid: str, name: str):
    s = _session(sid)
    path = (s.dir / name).resolve()
    if s.dir.resolve() not in path.parents or path.suffix.lower() not in SERVE_SUFFIXES or not path.is_file():
        raise HTTPException(404, "File not found.")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@app.get("/api/{sid}/export/stl")
def export_stl(sid: str):
    s = _session(sid)
    out = s.dir / "gen" / "out.stl"
    if not s.result_ok or not out.exists():
        raise HTTPException(409, "Nothing to export yet — generate a valid result first.")
    return FileResponse(out, filename=f"{Path(s.name).stem}_sprued.stl", media_type="model/stl")


@app.get("/api/{sid}/export/zip")
def export_zip(sid: str):
    s = _session(sid)
    if not s.result_ok:
        raise HTTPException(409, "Nothing to export yet — generate a valid result first.")
    z = service.export_zip(s)
    return FileResponse(z, filename=z.name, media_type="application/zip")


def _cleanup() -> None:
    for s in list(SESSIONS.values()):
        shutil.rmtree(s.dir, ignore_errors=True)


def free_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port")


def run(port: int = 8765, open_browser: bool = True, echo=print) -> None:
    import uvicorn

    port = free_port(port)
    url = f"http://127.0.0.1:{port}"
    atexit.register(_cleanup)
    echo(f"spruegen GUI → {url}   (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
