#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
INSTALL_MARKER_NAME = ".secret_pond_install_complete"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def venv_python_path(root: Path, os_name: str = os.name) -> Path:
    if os_name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def build_serve_command(
    root: Path,
    host: str,
    port: int,
    *,
    os_name: str = os.name,
) -> list[str]:
    return [
        venv_python_path(root, os_name).as_posix(),
        "-m",
        "secret_pond.cli",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]


def bootstrap_candidates(os_name: str = os.name) -> list[list[str]]:
    if os_name == "nt":
        return [["py", "-3.11"], ["py", "-3.12"], ["python"]]
    return [["python3.11"], ["python3.12"], ["python3"]]


def needs_install(root: Path) -> bool:
    marker = root / ".venv" / INSTALL_MARKER_NAME
    if not marker.exists():
        return True

    watched_files = [root / "pyproject.toml", root / "uv.lock"]
    marker_mtime = marker.stat().st_mtime
    return any(path.exists() and path.stat().st_mtime > marker_mtime for path in watched_files)


def server_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"", "0.0.0.0"} else host
    return f"http://{browser_host}:{port}"


def _supported_python_command(command: list[str]) -> bool:
    probe = (
        "import sys; "
        "raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)"
    )
    try:
        result = subprocess.run(
            [*command, "-c", probe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def choose_bootstrap_python() -> list[str]:
    if (3, 11) <= sys.version_info[:2] < (3, 13):
        return [sys.executable]

    for command in bootstrap_candidates():
        if _supported_python_command(command):
            return command

    raise RuntimeError("Python 3.11 또는 3.12를 찾을 수 없습니다.")


def ensure_venv(root: Path) -> Path:
    python_path = venv_python_path(root)
    if python_path.exists():
        return python_path

    command = choose_bootstrap_python()
    print("가상환경을 준비합니다: .venv")
    subprocess.check_call([*command, "-m", "venv", str(root / ".venv")], cwd=root)
    return python_path


def install_project(root: Path, python_path: Path) -> None:
    print("필요한 Python 패키지를 설치합니다.")
    subprocess.check_call([str(python_path), "-m", "pip", "install", "--upgrade", "pip"], cwd=root)
    subprocess.check_call([str(python_path), "-m", "pip", "install", "-e", "."], cwd=root)
    marker = root / ".venv" / INSTALL_MARKER_NAME
    marker.write_text("ok\n", encoding="utf-8")


def wait_for_server(
    url: str,
    process: subprocess.Popen[bytes],
    timeout_seconds: float = 30.0,
) -> bool:
    health_url = f"{url}/health"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="The Secret Pond 서버를 준비하고 실행합니다.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="서버만 켜고 브라우저는 자동으로 열지 않습니다.",
    )
    parser.add_argument(
        "--reinstall",
        action="store_true",
        help="가상환경 패키지를 다시 설치한 뒤 서버를 켭니다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = project_root()
    python_path = ensure_venv(root)

    if args.reinstall or needs_install(root):
        install_project(root, python_path)

    url = server_url(args.host, args.port)
    command = build_serve_command(root, args.host, args.port)

    print(f"Secret Pond 서버를 시작합니다: {url}")
    print("이 창을 닫거나 Ctrl+C를 누르면 서버가 종료됩니다.")
    process = subprocess.Popen(command, cwd=root)

    try:
        if not args.no_browser:
            if wait_for_server(url, process):
                webbrowser.open(url)
            elif process.poll() is None:
                print(f"브라우저 자동 열기 확인에 실패했습니다. 직접 열어주세요: {url}")
        return process.wait()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
        process.terminate()
        return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
