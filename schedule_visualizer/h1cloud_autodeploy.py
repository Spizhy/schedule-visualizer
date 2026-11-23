"""Run the site and deploy successful main builds from the public GitHub repository."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parent
RELEASES = ROOT / ".schedule-releases"
ACTIVE = RELEASES / "active.json"
REPO = "Spizhy/schedule-visualizer"
PORT = int(os.environ.get("SERVER_PORT") or os.environ.get("PORT") or "25070")
CHECK_INTERVAL = 90
ARCHIVE_LIMIT = 16 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}")
BUILD_TAG = re.compile(r"h1cloud-(\d+)-([0-9a-f]{40})")


def read_url(url: str, limit: int, timeout: int = 10) -> bytes:
    request = Request(url, headers={"User-Agent": "ScheduleViz-H1Cloud"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("GitHub response exceeds the download limit")
    return body


def latest_build() -> tuple[int, str] | None:
    feed = ElementTree.fromstring(read_url(f"https://github.com/{REPO}/releases.atom", 256 * 1024))
    builds = []
    for link in feed.findall("{*}entry/{*}link"):
        path = urlparse(link.get("href", "")).path
        prefix = f"/{REPO}/releases/tag/"
        if path.startswith(prefix) and (tag := BUILD_TAG.fullmatch(path.removeprefix(prefix))):
            builds.append((int(tag[1]), tag[2]))
    return max(builds, default=None)


def stage_build(revision: str) -> Path:
    address = f"https://codeload.github.com/{REPO}/zip/{revision}"
    with tempfile.TemporaryDirectory(dir=RELEASES) as temporary:
        stage = Path(temporary)
        with ZipFile(io.BytesIO(read_url(address, ARCHIVE_LIMIT))) as archive:
            if sum(info.file_size for info in archive.infolist()) > ARCHIVE_LIMIT:
                raise ValueError("Expanded release exceeds the size limit")
            for info in archive.infolist():
                parts = PurePosixPath(info.filename).parts
                if len(parts) < 3 or parts[1] != "schedule_visualizer" or info.is_dir():
                    continue
                if any(part in ("..", ".") or "\\" in part for part in parts[2:]):
                    raise ValueError("Invalid release archive path")
                target = stage.joinpath(*parts[2:])
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)

        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             "--target", str(stage / ".deps"), "-r", "requirements.txt"],
            cwd=stage, check=True, timeout=90,
        )
        subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"],
            cwd=stage, env=worker_env(stage, revision), check=True, timeout=45,
        )
        target = RELEASES / revision
        stage.rename(target)
        return target


def worker_env(path: Path, revision: str) -> dict[str, str]:
    env = {**os.environ, "SERVER_PORT": str(PORT), "SCHEDULE_REVISION": revision}
    deps = path / ".deps"
    if deps.is_dir():
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(deps), env.get("PYTHONPATH"))))
    return env


def launch_worker(path: Path, revision: str) -> subprocess.Popen:
    worker = subprocess.Popen(
        [sys.executable, "-B", str(path / "run.py")],
        cwd=path, env=worker_env(path, revision),
    )
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and worker.poll() is None:
            try:
                status = json.loads(read_url(f"http://127.0.0.1:{PORT}/healthz", 4096, timeout=1))
                if status.get("revision") == revision or (
                    revision == "initial" and status.get("status") == "ok"
                ):
                    return worker
            except (OSError, ValueError):
                pass
            time.sleep(0.25)
        raise RuntimeError("The new process did not pass its health check")
    except BaseException:
        stop_worker(worker)
        raise


def stop_worker(worker: subprocess.Popen) -> None:
    if worker.poll() is not None:
        return
    worker.terminate()
    try:
        worker.wait(timeout=8)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait()


def save_build(number: int, revision: str) -> None:
    temporary = ACTIVE.with_suffix(".tmp")
    temporary.write_text(json.dumps([number, revision]), encoding="utf-8")
    temporary.replace(ACTIVE)


def shutdown(_signum, _frame):
    raise SystemExit(0)


def main() -> None:
    RELEASES.mkdir(exist_ok=True)
    number, revision = json.loads(ACTIVE.read_text(encoding="utf-8")) if ACTIVE.exists() else (0, "initial")
    path = RELEASES / revision if SHA.fullmatch(revision) else ROOT
    worker = launch_worker(path, revision)
    failed = None
    try:
        while worker.poll() is None:
            try:
                build = latest_build()
                if build and build[0] > number and build != failed:
                    new_number, new_revision = build
                    candidate = RELEASES / new_revision
                    if not candidate.exists():
                        candidate = stage_build(new_revision)
                    stop_worker(worker)
                    try:
                        worker = launch_worker(candidate, new_revision)
                        save_build(new_number, new_revision)
                    except (OSError, RuntimeError):
                        stop_worker(worker)
                        worker = launch_worker(path, revision)
                        failed = build
                        print(f"Release {new_revision[:12]} failed. Restored {revision[:12]}.", flush=True)
                    else:
                        print(f"Deployed {new_revision[:12]} (workflow run {new_number}).", flush=True)
                        previous = path
                        number, revision, path = new_number, new_revision, candidate
                        for entry in RELEASES.iterdir():
                            if entry not in (previous, path) and entry.is_dir() and SHA.fullmatch(entry.name):
                                shutil.rmtree(entry, ignore_errors=True)
            except (URLError, OSError, ValueError, ElementTree.ParseError, BadZipFile, subprocess.SubprocessError) as error:
                print(f"Update check will retry: {error}", flush=True)
            try:
                worker.wait(timeout=CHECK_INTERVAL)
            except subprocess.TimeoutExpired:
                continue
        raise SystemExit(worker.returncode or 1)
    finally:
        stop_worker(worker)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, shutdown)
    main()
