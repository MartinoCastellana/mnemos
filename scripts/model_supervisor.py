#!/usr/bin/env python3
"""Small authenticated host process manager for mutually exclusive local models."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


PROJECT_DIR = Path(__file__).resolve().parent.parent
TOKEN = os.environ.get("DOC_AI_MODEL_SUPERVISOR_TOKEN", "")
if not TOKEN:
    try:
        TOKEN = Path("/tmp/mnemos-model-supervisor.token").read_text().strip()
    except OSError:
        TOKEN = ""
PORT = int(os.environ.get("DOC_AI_MODEL_SUPERVISOR_PORT", "18500"))
MODEL_ENDPOINTS = {
    "minicpm": ("http://127.0.0.1:18499/health", "scripts/start_minicpm_ocr.sh", "/tmp/mnemos-minicpm-ocr.log"),
    "qwen": ("http://127.0.0.1:8081/v1/models", "scripts/start_mlx.sh", "/tmp/mnemos-mlx.log"),
}
PID_FILES = {"minicpm": "/tmp/mnemos-minicpm-ocr.pid", "qwen": "/tmp/mnemos-mlx.pid"}
lock = threading.RLock()
processes: dict[str, subprocess.Popen] = {}
owner: str | None = None


def healthy(model: str) -> bool:
    try:
        with urlopen(MODEL_ENDPOINTS[model][0], timeout=2) as response:
            return 200 <= response.status < 300
    except (OSError, URLError, TimeoutError):
        return False


def process_command(pid: int) -> str:
    try:
        return subprocess.check_output(
            ["/bin/ps", "-p", str(pid), "-o", "command="], text=True, timeout=2
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _kill_process_group(pid: int, proc: subprocess.Popen | None = None) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        # Some macOS launch contexts can deny process-group signalling even when
        # the supervisor owns the server PID. The launch scripts exec the model
        # server, so signalling the validated PID is a safe fallback.
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    if proc is not None:
        try:
            proc.wait(timeout=20)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except PermissionError:
            os.kill(pid, signal.SIGKILL)
        proc.wait(timeout=5)
        return
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            # macOS may deny signal 0 to a protected child after SIGTERM.
            # Confirm the PID still belongs to the expected server before waiting.
            if not process_command(pid):
                return
            time.sleep(0.25)
            continue
        time.sleep(0.25)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def stop(model: str) -> None:
    global owner
    proc = processes.pop(model, None)
    pid = proc.pid if proc else None
    if pid is None:
        pid_path = Path(PID_FILES[model])
        try:
            candidate = int(pid_path.read_text().strip())
        except (OSError, ValueError):
            candidate = 0
        command = process_command(candidate) if candidate else ""
        expected = "llama-server" if model == "minicpm" else "mlx_lm server"
        if candidate and expected in command:
            pid = candidate
    if pid:
        _kill_process_group(pid, proc)
    Path(PID_FILES[model]).unlink(missing_ok=True)
    deadline = time.monotonic() + 15
    while healthy(model) and time.monotonic() < deadline:
        time.sleep(0.25)
    if healthy(model):
        raise RuntimeError(f"{model} è ancora caricato dopo la richiesta di arresto")
    if owner == model:
        owner = None


def start(model: str) -> None:
    global owner
    endpoint, script, logfile = MODEL_ENDPOINTS[model]
    del endpoint
    log = open(logfile, "ab", buffering=0)
    try:
        proc = subprocess.Popen(
            ["/bin/zsh", str(PROJECT_DIR / script)],
            cwd=PROJECT_DIR,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log.close()
    processes[model] = proc
    Path(PID_FILES[model]).write_text(f"{proc.pid}\n")
    owner = model
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        if healthy(model):
            return
        if proc.poll() is not None:
            break
        time.sleep(1)
    try:
        lines = Path(logfile).read_text(errors="replace").splitlines()[-30:]
    except OSError:
        lines = []
    stop(model)
    raise RuntimeError(
        f"Avvio di {model} non riuscito. Log: " + "\n".join(lines)
    )


def acquire(model: str) -> dict:
    global owner
    if model not in MODEL_ENDPOINTS:
        raise ValueError("Modello non riconosciuto")
    with lock:
        other = "qwen" if model == "minicpm" else "minicpm"
        if owner == model and healthy(model):
            return {"ok": True, "model": model, "loaded": True, "reused": True}
        if owner == other:
            stop(other)
        elif healthy(other):
            raise RuntimeError(
                f"{other} risulta caricato fuori dal supervisor; arrestalo prima di continuare"
            )
        if owner == model:
            stop(model)
        if healthy(model):
            raise RuntimeError(
                f"{model} risulta caricato fuori dal supervisor; arrestalo prima di continuare"
            )
        start(model)
        return {"ok": True, "model": model, "loaded": True, "reused": False}


def release(model: str) -> dict:
    with lock:
        if owner == model or model in processes or healthy(model):
            stop(model)
        return {"ok": True, "model": model, "loaded": False}


def status() -> dict:
    with lock:
        return {
            "ok": True,
            "owner": owner,
            "minicpm_loaded": healthy("minicpm"),
            "qwen_loaded": healthy("qwen"),
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        return

    def send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/status":
            self.send_json(404, {"ok": False, "error": "Not found"})
            return
        if self.headers.get("X-Mnemos-Token", "") != TOKEN:
            self.send_json(401, {"ok": False, "error": "Unauthorized"})
            return
        self.send_json(200, status())

    def do_POST(self) -> None:
        if self.headers.get("X-Mnemos-Token", "") != TOKEN:
            self.send_json(401, {"ok": False, "error": "Unauthorized"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size) or b"{}")
            model = payload.get("model")
            if self.path == "/acquire":
                result = acquire(str(model or ""))
            elif self.path == "/release":
                result = release(str(model or ""))
            else:
                self.send_json(404, {"ok": False, "error": "Not found"})
                return
            self.send_json(200, result)
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})


if not TOKEN:
    raise SystemExit("DOC_AI_MODEL_SUPERVISOR_TOKEN mancante")

server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)


def shutdown(_signum, _frame) -> None:
    def stop_all() -> None:
        for model in ("minicpm", "qwen"):
            try:
                stop(model)
            except Exception:
                pass
        server.shutdown()

    threading.Thread(target=stop_all, daemon=True).start()


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
server.serve_forever()
