from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "launch_secret_pond.py"


def load_launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("launch_secret_pond", LAUNCHER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_builds_serve_command_for_platform_venv() -> None:
    launcher = load_launcher()

    posix_command = launcher.build_serve_command(
        Path("/show/secret-pond"),
        "127.0.0.1",
        8000,
        os_name="posix",
    )
    windows_command = launcher.build_serve_command(
        Path("C:/show/secret-pond"),
        "127.0.0.1",
        8000,
        os_name="nt",
    )

    assert posix_command == [
        "/show/secret-pond/.venv/bin/python",
        "-m",
        "secret_pond.cli",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    assert windows_command == [
        "C:/show/secret-pond/.venv/Scripts/python.exe",
        "-m",
        "secret_pond.cli",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]


def test_launcher_reinstalls_when_project_inputs_are_newer_than_marker(tmp_path: Path) -> None:
    launcher = load_launcher()
    marker = tmp_path / ".venv" / ".secret_pond_install_complete"
    pyproject = tmp_path / "pyproject.toml"
    lock = tmp_path / "uv.lock"
    marker.parent.mkdir()
    pyproject.write_text("[project]\n", encoding="utf-8")
    lock.write_text("lock", encoding="utf-8")
    marker.write_text("ok", encoding="utf-8")

    assert launcher.needs_install(tmp_path) is False

    marker_mtime = marker.stat().st_mtime
    os.utime(pyproject, (marker_mtime + 10, marker_mtime + 10))

    assert launcher.needs_install(tmp_path) is True


def test_launcher_uses_python_bootstrap_candidates_by_os() -> None:
    launcher = load_launcher()

    assert launcher.bootstrap_candidates("nt") == [
        ["py", "-3.11"],
        ["py", "-3.12"],
        ["py", "-3.13"],
        ["py", "-3.14"],
        ["python"],
    ]
    assert launcher.bootstrap_candidates("posix") == [
        ["python3.11"],
        ["python3.12"],
        ["python3.13"],
        ["python3.14"],
        ["python3"],
    ]


def test_clickable_launcher_wrappers_call_common_bootstrapper() -> None:
    mac_launcher = ROOT / "Start Secret Pond.command"
    windows_launcher = ROOT / "Start Secret Pond.bat"

    assert "scripts/launch_secret_pond.py" in mac_launcher.read_text(encoding="utf-8")
    assert "scripts\\launch_secret_pond.py" in windows_launcher.read_text(encoding="utf-8")


def test_windows_launcher_stays_safe_for_cmd_batch_parsing() -> None:
    windows_launcher = ROOT / "Start Secret Pond.bat"
    launcher_bytes = windows_launcher.read_bytes()
    launcher_text = launcher_bytes.decode("ascii")

    assert "(3, 11)" not in launcher_text
    assert "(3, 13)" not in launcher_text
    assert "if not defined SECRET_POND_PY (" not in launcher_text
    assert "if errorlevel 1 (" not in launcher_text


def test_windows_launcher_validates_probe_output_not_just_py_exit_code() -> None:
    windows_launcher = ROOT / "Start Secret Pond.bat"
    launcher_text = windows_launcher.read_text(encoding="ascii").lower()

    assert "for /f" in launcher_text
    assert "-vv" in launcher_text


def test_launcher_rejects_python_manager_error_even_with_zero_exit(monkeypatch) -> None:
    launcher = load_launcher()

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="[ERROR] No runtime installed")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    assert launcher._supported_python_command(["py", "-3.11"]) is False
