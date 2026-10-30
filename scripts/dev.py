#!/usr/bin/env python3
"""One-command development launcher.

Starts what the project needs for local development:

1. Qdrant (unless a compatible instance is already listening)
2. the FastAPI engine with dev tools enabled
3. the Tauri desktop window (unless --no-desktop)

Every child process is logged under ``logs/dev/`` and stopped on Ctrl+C.
Only processes started by this script are stopped; an existing Qdrant/engine
instance is reused and left running.

Examples:
    ./run.sh
    ./run.sh --no-desktop --mock-llm
    ./run.sh --engine-port 8090 --no-qdrant
    ./run.sh --check
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "runtime" / "logs" / "dev"
IS_WINDOWS = os.name == "nt"


def log(message: str) -> None:
    print(message, flush=True)


@dataclass
class Service:
    name: str
    command: list[str]
    cwd: Path = ROOT
    env: dict[str, str] = field(default_factory=dict)
    quiet: bool = False
    process: subprocess.Popen[str] | None = None
    log_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.log_path = LOG_DIR / f"{self.name}.log"

    def start(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handle = self.log_path.open("a", encoding="utf-8", errors="replace")
        handle.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} =====\n")
        handle.flush()

        environment = os.environ.copy()
        environment.update(self.env)
        popen_kwargs = {}
        if IS_WINDOWS:
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        self.process = subprocess.Popen(
            self.command,
            cwd=str(self.cwd),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **popen_kwargs,
        )
        threading.Thread(target=self._pump, args=(handle,), daemon=True).start()
        log(f"[{self.name}] started pid={self.process.pid} log={self.log_path}")

    def _pump(self, handle) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            handle.write(line)
            handle.flush()
            if not self.quiet:
                print(f"[{self.name}] {line.rstrip()}", flush=True)
        handle.close()

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        log(f"[{self.name}] stopping…")
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except OSError:
                self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(400).decode("utf-8", errors="replace")
            return response.status < 400, body
    except (urllib.error.URLError, OSError) as exc:
        return False, str(exc)


def wait_for_port(port: int, timeout: float, label: str) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.3)
    log(f"! {label} did not start listening on 127.0.0.1:{port} within {timeout:.0f}s")
    return False


def wait_for_http(url: str, timeout: float, label: str) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ok, _ = http_ok(url)
        if ok:
            return True
        time.sleep(0.3)
    log(f"! {label} health check failed: {url}")
    return False


def find_venv_python() -> Path | None:
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def find_qdrant() -> Path | None:
    candidates = []
    override = os.environ.get("QDRANT_BIN", "").strip()
    if override:
        candidates.append(Path(override))
    candidates.append(
        ROOT / "runtime" / "tools" / "qdrant" / ("qdrant.exe" if IS_WINDOWS else "qdrant")
    )
    found = shutil.which("qdrant")
    if found:
        candidates.append(Path(found))
    return next((path for path in candidates if path.is_file()), None)


def python_version(python: Path) -> str:
    try:
        output = subprocess.run(
            [str(python), "-c", "import platform; print(platform.python_version())"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return output.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def run_collection_init(python: Path, qdrant_url: str) -> bool:
    environment = os.environ.copy()
    environment.update(
        {
            "QDRANT_URL": qdrant_url,
            "PYTHONIOENCODING": "utf-8",
        }
    )
    result = subprocess.run(
        [str(python), "scripts/create_collection.py"],
        cwd=str(ROOT),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        log(f"[collection] {lines[0] if lines else 'ok'}")
        return True
    log("[collection] failed:")
    log((result.stderr or result.stdout).strip()[-2000:])
    return False


def check_report(
    python: Path,
    qdrant: Path | None,
    engine_port: int,
    qdrant_http_port: int,
    desktop: bool,
) -> int:
    log(f"repo       : {ROOT}")
    log(f"python     : {python} ({python_version(python)})")
    log(f"qdrant bin : {qdrant or 'not found'}")
    models = ROOT / "runtime" / "models"
    missing = [
        name for name in ("bge-m3", "bge-reranker-v2-m3", "bm25") if not (models / name).is_dir()
    ]
    log(f"models     : {'ok' if not missing else 'missing ' + ', '.join(missing)}")
    log(f"engine port: {engine_port} {'in use' if port_open(engine_port) else 'free'}")
    log(f"qdrant port: {qdrant_http_port} {'in use' if port_open(qdrant_http_port) else 'free'}")
    if desktop:
        log(f"npm        : {shutil.which('npm') or 'not found'}")
        log(f"cargo      : {shutil.which('cargo') or 'not found'}")
        log(f"node_modules: {'ok' if (ROOT / 'desktop' / 'node_modules').is_dir() else 'missing'}")
    return 0 if python.is_file() and (qdrant or port_open(qdrant_http_port)) else 1


def install_desktop_dependencies(npm: str) -> bool:
    log("[desktop] node_modules missing, running npm install…")
    result = subprocess.run([npm, "install"], cwd=str(ROOT / "desktop"), check=False)
    return result.returncode == 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Start Qdrant, the RAG engine and the Tauri desktop client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--engine-port", type=int, default=8080)
    parser.add_argument("--qdrant-http-port", type=int, default=6333)
    parser.add_argument("--qdrant-grpc-port", type=int, default=6334)
    parser.add_argument("--no-desktop", action="store_true", help="only start the backend")
    parser.add_argument("--no-qdrant", action="store_true", help="reuse an existing Qdrant")
    parser.add_argument("--no-init", action="store_true", help="skip collection creation")
    parser.add_argument("--mock-llm", action="store_true", help="force LLM_MOCK=true")
    parser.add_argument("--warmup", action="store_true", help="load models during engine startup")
    parser.add_argument(
        "--redis", action="store_true", help="enable Redis cache (CACHE_ENABLED=true)"
    )
    parser.add_argument("--no-reload", action="store_true", help="disable uvicorn --reload")
    parser.add_argument("--no-install", action="store_true", help="never run npm install")
    parser.add_argument("--quiet", action="store_true", help="write logs to files only")
    parser.add_argument(
        "--check", action="store_true", help="print the environment report and exit"
    )
    args = parser.parse_args()

    python = find_venv_python()
    if python is None:
        log("! .venv not found.")
        log("  Create it first:")
        log("    uv venv --python 3.12 .venv")
        log("    uv pip install --python .venv/Scripts/python.exe -r requirements.txt")
        return 1

    qdrant = find_qdrant()
    if args.check:
        return check_report(
            python,
            qdrant,
            args.engine_port,
            args.qdrant_http_port,
            not args.no_desktop,
        )

    started: list[Service] = []
    qdrant_url = f"http://127.0.0.1:{args.qdrant_http_port}"

    try:
        # ------------------------------------------------------------- Qdrant
        if args.no_qdrant or port_open(args.qdrant_http_port):
            if port_open(args.qdrant_http_port):
                log(f"[qdrant] reusing existing instance on {qdrant_url}")
            else:
                log("[qdrant] --no-qdrant set, expecting an external instance")
        else:
            if qdrant is None:
                log("! qdrant binary not found.")
                log(
                    "  Put it at runtime/tools/qdrant/qdrant.exe, "
                    "set QDRANT_BIN, or use --no-qdrant."
                )
                return 1
            qdrant_service = Service(
                name="qdrant",
                command=[str(qdrant)],
                cwd=ROOT / "runtime",
                env={
                    "QDRANT__STORAGE__STORAGE_PATH": str(ROOT / "runtime" / "qdrant_storage"),
                    "QDRANT__STORAGE__SNAPSHOTS_PATH": str(ROOT / "runtime" / "snapshots"),
                    "QDRANT__SERVICE__HOST": "127.0.0.1",
                    "QDRANT__SERVICE__HTTP_PORT": str(args.qdrant_http_port),
                    "QDRANT__SERVICE__GRPC_PORT": str(args.qdrant_grpc_port),
                    "QDRANT__SERVICE__ENABLE_CORS": "false",
                    "QDRANT__TELEMETRY_DISABLED": "true",
                },
                quiet=args.quiet,
            )
            qdrant_service.start()
            started.append(qdrant_service)
            if not wait_for_port(args.qdrant_http_port, 30, "qdrant"):
                return 1

        if not args.no_init:
            if not run_collection_init(python, qdrant_url):
                return 1

        # ------------------------------------------------------------- engine
        if port_open(args.engine_port):
            ok, _ = http_ok(f"http://127.0.0.1:{args.engine_port}/health")
            if not ok:
                log(f"! engine port {args.engine_port} is in use by something else")
                return 1
            log(f"[engine] reusing existing instance on http://127.0.0.1:{args.engine_port}")
        else:
            engine_env = {
                "QDRANT_URL": qdrant_url,
                "DEV_TOOLS_ENABLED": "true",
                "CACHE_ENABLED": "true" if args.redis else "false",
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
                "BGE_M3_PATH": str(ROOT / "runtime" / "models" / "bge-m3"),
                "BGE_RERANKER_PATH": str(ROOT / "runtime" / "models" / "bge-reranker-v2-m3"),
                "BM25_MODEL_PATH": str(ROOT / "runtime" / "models" / "bm25"),
                "UPLOAD_DIR": str(ROOT / "runtime" / "data" / "uploads"),
            }
            if args.mock_llm:
                engine_env["LLM_MOCK"] = "true"
            if args.warmup:
                engine_env["WARMUP_ON_STARTUP"] = "true"
            command = [
                str(python),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.engine_port),
            ]
            if not args.no_reload:
                command.extend(["--reload", "--reload-dir", "app"])
            engine_service = Service(
                name="engine",
                command=command,
                env=engine_env,
                quiet=args.quiet,
            )
            engine_service.start()
            started.append(engine_service)
            if not wait_for_http(f"http://127.0.0.1:{args.engine_port}/health", 60, "engine"):
                return 1

        # ------------------------------------------------------------ desktop
        if not args.no_desktop:
            npm = shutil.which("npm")
            cargo = shutil.which("cargo")
            if not npm or not cargo:
                log("! npm/cargo not found; skipping the desktop client.")
                log("  Install Node 20+ and Rust 1.77+, or pass --no-desktop.")
            else:
                if not (ROOT / "desktop" / "node_modules").is_dir() and not args.no_install:
                    if not install_desktop_dependencies(npm):
                        log("! npm install failed; skipping the desktop client.")
                        npm = None
                if npm:
                    desktop_env = {
                        "ARG_ENGINE_ROOT": str(ROOT),
                        "ARG_VENV_DIR": str(ROOT / ".venv"),
                        "ARG_MODELS_DIR": str(ROOT / "runtime" / "models"),
                        "ARG_ENGINE_URL": f"http://127.0.0.1:{args.engine_port}",
                    }
                    if qdrant is not None:
                        desktop_env["ARG_QDRANT_BIN"] = str(qdrant)
                    desktop_service = Service(
                        name="desktop",
                        command=[npm, "run", "tauri", "dev"],
                        cwd=ROOT / "desktop",
                        env=desktop_env,
                        quiet=args.quiet,
                    )
                    desktop_service.start()
                    started.append(desktop_service)

        # ------------------------------------------------------------ summary
        log("")
        log("=" * 64)
        log(f"Engine   : http://127.0.0.1:{args.engine_port}")
        log(f"Swagger  : http://127.0.0.1:{args.engine_port}/docs")
        log(f"Qdrant   : {qdrant_url}")
        log(f"Logs     : {LOG_DIR}")
        if any(service.name == "desktop" for service in started):
            log("Desktop  : Tauri window should open shortly")
        elif args.no_desktop:
            log("Desktop  : skipped (--no-desktop)")
        log("Press Ctrl+C to stop everything started by this script.")
        log("=" * 64)

        while True:
            for service in started:
                if service.process is not None and service.process.poll() is not None:
                    log(f"[{service.name}] exited with code {service.process.returncode}")
                    return service.process.returncode or 0
            time.sleep(1)

    except KeyboardInterrupt:
        log("\nStopping…")
        return 0
    finally:
        for service in reversed(started):
            service.stop()


if __name__ == "__main__":
    sys.exit(main())
