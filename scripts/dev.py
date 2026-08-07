"""Run the local API and dashboard as one supervised process group."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import re
import signal
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "logs" / "error.log"
LOCK_PATH = ROOT / "logs" / "dev.lock"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SERVICE_PORTS = {"backend": 8010, "frontend": 3000}


def make_logger() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("hynix_basis.dev")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        logger.addHandler(handler)
    return logger


LOGGER = make_logger()


def acquire_lock(path: Path = LOCK_PATH) -> TextIO | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def listening_pids(port: int) -> list[int]:
    result = subprocess.run(
        ["lsof", "-t", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
    )
    return sorted({int(value) for value in result.stdout.split() if value.isdigit()})


def process_command(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def is_project_listener(service: str, command: str) -> bool:
    if str(ROOT) not in command:
        return False
    if service == "backend":
        return "uvicorn" in command and "backend.main:app" in command
    return "vinext" in command


def stop_stale_listener(service: str, port: int) -> None:
    pids = listening_pids(port)
    if not pids:
        return
    commands = {pid: process_command(pid) for pid in pids}
    grouped: dict[int, list[tuple[int, str]]] = {}
    for pid, command in commands.items():
        grouped.setdefault(os.getpgid(pid), []).append((pid, command))
    unexpected = {
        group: entries
        for group, entries in grouped.items()
        if not any(is_project_listener(service, command) for _, command in entries)
    }
    if unexpected:
        details = "; ".join(
            f"pid {pid}: {command}"
            for entries in unexpected.values()
            for pid, command in entries
        )
        raise RuntimeError(f"Port {port} is used by another application ({details})")

    groups = set(grouped)
    LOGGER.warning(
        "Removing stale %s listener on port %s (pids=%s)", service, port, pids
    )
    for group in groups:
        os.killpg(group, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and listening_pids(port):
        time.sleep(0.1)
    if listening_pids(port):
        LOGGER.warning("Stale %s listener required forced shutdown", service)
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass


def clear_stale_services() -> None:
    for service, port in SERVICE_PORTS.items():
        stop_stale_listener(service, port)


async def stream_output(service: str, process: asyncio.subprocess.Process) -> None:
    if process.stdout is None:
        return
    while line := await process.stdout.readline():
        text = line.decode(errors="replace")
        sys.stdout.write(text)
        sys.stdout.flush()
        clean = ANSI_ESCAPE.sub("", text).rstrip()
        if clean:
            LOGGER.info("[%s] %s", service, clean)


async def stop_process(name: str, process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    LOGGER.info("Stopping %s process group (pid=%s)", name, process.pid)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        LOGGER.warning("%s did not stop after five seconds; forcing shutdown", name)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


async def run() -> int:
    backend_env = os.environ.copy()
    backend_env.update(HYNIX_LOG_MODE="stderr", PYTHONUNBUFFERED="1")
    services = {
        "backend": await asyncio.create_subprocess_exec(
            str(ROOT / ".venv/bin/uvicorn"),
            "backend.main:app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            "8010",
            cwd=ROOT,
            env=backend_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        ),
        "frontend": await asyncio.create_subprocess_exec(
            "npm",
            "run",
            "dev",
            cwd=ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        ),
    }
    LOGGER.info(
        "Started local dashboard: backend pid=%s, frontend pid=%s",
        services["backend"].pid,
        services["frontend"].pid,
    )

    output_tasks = [
        asyncio.create_task(stream_output(name, process))
        for name, process in services.items()
    ]
    wait_tasks = {
        asyncio.create_task(process.wait()): name for name, process in services.items()
    }
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_requested.set)
    stop_task = asyncio.create_task(stop_requested.wait())

    done, _ = await asyncio.wait(
        [*wait_tasks, stop_task], return_when=asyncio.FIRST_COMPLETED
    )
    exit_code = 0
    if stop_task not in done:
        completed = next(task for task in done if task in wait_tasks)
        name = wait_tasks[completed]
        child_status = completed.result()
        exit_code = child_status or 1
        LOGGER.error(
            "%s exited unexpectedly with status %s; shutting down the other service",
            name,
            child_status,
        )

    await asyncio.gather(
        *(stop_process(name, process) for name, process in services.items())
    )
    await asyncio.gather(*output_tasks, return_exceptions=True)
    for task in [*wait_tasks, stop_task]:
        if not task.done():
            task.cancel()
    return exit_code


def main() -> None:
    lock = acquire_lock()
    if lock is None:
        print("Hynix Basis is already running at http://localhost:3000/")
        raise SystemExit(0)
    try:
        clear_stale_services()
        raise SystemExit(asyncio.run(run()))
    except RuntimeError as exc:
        LOGGER.error("Local dashboard could not start: %s", exc)
        print(f"Cannot start Hynix Basis: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    finally:
        lock.close()


if __name__ == "__main__":
    main()
