from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from secret_pond.audio.device_readiness import build_device_warnings as shared_device_warnings
from secret_pond.audio.devices import AudioDeviceInfo, AudioDeviceRegistry, SoundDeviceRegistry
from secret_pond.audio.renderer import LayerRenderer
from secret_pond.audio.source_library import selected_source_path
from secret_pond.audio.voice_stack import VoiceStackStore
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.device_inventory import device_payload
from secret_pond.services.settings_store import SettingsStore

REQUIRED_NATIVE_DEPENDENCIES = ("numpy", "sounddevice", "soundfile", "scipy", "pedalboard")
DOCTOR_SCHEMA_VERSION = 1


class AudioDeviceCheckError(RuntimeError):
    """Raised when host audio device probing cannot complete."""


@dataclass(frozen=True)
class DoctorReport:
    root: Path
    os_name: str
    python_version: str
    data_dir: Path
    data_writable: bool
    native_dependencies: dict[str, bool]
    input_devices: list[AudioDeviceInfo]
    output_devices: list[AudioDeviceInfo]
    input_device: AudioDeviceInfo | None
    output_device: AudioDeviceInfo | None
    missing_sources: list[Path]
    warnings: list[str]
    settings: AppSettings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secret-pond")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="Check local runtime and audio devices.")
    doctor_parser.add_argument("--root", type=Path, default=Path.cwd())
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Print a machine-readable readiness report.",
    )
    doctor_parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with failure when show-readiness checks fail.",
    )

    serve_parser = subparsers.add_parser("serve", help="Run the local web server.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    rebuild_parser = subparsers.add_parser(
        "rebuild-test-library",
        help="Rebuild the voice stack from test_library accepted clips.",
    )
    rebuild_parser.add_argument("--root", type=Path, default=Path.cwd())

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(args.root, output_json=args.output_json, strict=args.strict)
    if args.command == "serve":
        return run_serve(args.host, args.port)
    if args.command == "rebuild-test-library":
        return run_rebuild_test_library(args.root)

    parser.error("unknown command")
    return 2


def run_doctor(
    root: Path,
    *,
    output_json: bool = False,
    strict: bool = False,
    registry: AudioDeviceRegistry | None = None,
) -> int:
    paths = ProjectPaths(root)
    registry = registry or SoundDeviceRegistry()
    try:
        settings = SettingsStore(paths).load_for_startup().active
    except Exception as exc:
        error = f"Settings: unavailable ({exc})"
        if output_json:
            print(
                json.dumps(
                    doctor_failure_payload(paths, error),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(error)
        return 1

    try:
        report = build_doctor_report(paths, registry, settings)
    except AudioDeviceCheckError as exc:
        error = str(exc)
        if output_json:
            print(
                json.dumps(
                    doctor_failure_payload(paths, error, settings),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(error)
        return 1
    except Exception as exc:  # pragma: no cover - depends on host audio stack
        error = f"Doctor report: unavailable ({exc})"
        if output_json:
            print(
                json.dumps(
                    doctor_failure_payload(paths, error, settings),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(error)
        return 1

    failures = doctor_readiness_failures(report)
    if output_json:
        print(
            json.dumps(
                doctor_report_to_payload(report),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print_doctor_report(report, failures if strict else [])

    return 1 if strict and failures else 0


def build_doctor_report(
    paths: ProjectPaths,
    registry: AudioDeviceRegistry,
    settings: AppSettings,
) -> DoctorReport:
    paths.ensure_directories()

    native_dependencies = check_native_dependencies()
    try:
        input_devices = registry.list_input_devices()
        output_devices = registry.list_output_devices()
        input_device = registry.validate_input(settings.devices.input_device_id)
        output_device = registry.validate_output(settings.devices.output_device_id)
    except Exception as exc:
        msg = f"Audio devices: unavailable ({exc})"
        raise AudioDeviceCheckError(msg) from exc

    low_source = selected_source_path(paths, settings, "low") or paths.low_source
    mid_source = selected_source_path(paths, settings, "mid") or paths.mid_source
    missing_sources = [source for source in (low_source, mid_source) if not source.exists()]
    warnings = build_device_warnings(input_device, output_device, settings)

    return DoctorReport(
        root=paths.root,
        os_name=platform.platform(),
        python_version=sys.version.split()[0],
        data_dir=paths.data_dir,
        data_writable=check_write_access(paths.data_dir),
        native_dependencies=native_dependencies,
        input_devices=input_devices,
        output_devices=output_devices,
        input_device=input_device,
        output_device=output_device,
        missing_sources=missing_sources,
        warnings=warnings,
        settings=settings,
    )


def print_doctor_report(report: DoctorReport, readiness_failures: Sequence[str]) -> None:
    print("Secret Pond doctor")
    print(f"OS: {report.os_name}")
    print(f"Python: {report.python_version}")
    print(f"Data directory: {report.data_dir}")
    print(f"Data writable: {report.data_writable}")
    for name, available in report.native_dependencies.items():
        print(f"Dependency {name}: {'ok' if available else 'missing'}")

    print(f"Input devices: {len(report.input_devices)}")
    for device in report.input_devices:
        print(f"  [{device.id}] {device.name}")

    print(f"Output devices: {len(report.output_devices)}")
    for device in report.output_devices:
        print(f"  [{device.id}] {device.name}")

    for source in report.missing_sources:
        print(f"Missing source: {source}")
    for warning in report.warnings:
        print(f"Warning: {warning}")
    for failure in readiness_failures:
        print(f"Readiness failure: {failure}")


def doctor_report_to_payload(
    report: DoctorReport,
    errors: Sequence[str] = (),
) -> dict[str, object]:
    failures = doctor_readiness_failures(report)
    return {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "ready": not failures and not errors,
        "root": str(report.root),
        "os_name": report.os_name,
        "python_version": report.python_version,
        "data_dir": str(report.data_dir),
        "data_writable": report.data_writable,
        "native_dependencies": report.native_dependencies,
        "input_devices": [device_payload(device) for device in report.input_devices],
        "output_devices": [device_payload(device) for device in report.output_devices],
        "selected_input_device": device_payload(report.input_device),
        "selected_output_device": device_payload(report.output_device),
        "missing_sources": [str(source) for source in report.missing_sources],
        "warnings": report.warnings,
        "errors": list(errors),
        "readiness_failures": failures,
        "settings": _settings_to_payload(report.settings),
    }


def doctor_failure_payload(
    paths: ProjectPaths,
    error: str,
    settings: AppSettings | None = None,
) -> dict[str, object]:
    return {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "ready": False,
        "root": str(paths.root),
        "os_name": platform.platform(),
        "python_version": sys.version.split()[0],
        "data_dir": str(paths.data_dir),
        "data_writable": _safe_check_write_access(paths.data_dir),
        "native_dependencies": check_native_dependencies(),
        "input_devices": [],
        "output_devices": [],
        "selected_input_device": None,
        "selected_output_device": None,
        "missing_sources": [
            str(source)
            for source in (paths.low_source, paths.mid_source)
            if not source.exists()
        ],
        "warnings": [],
        "errors": [error],
        "readiness_failures": [error],
        "settings": None if settings is None else _settings_to_payload(settings),
    }


def doctor_readiness_failures(report: DoctorReport) -> list[str]:
    failures: list[str] = []
    if not report.data_writable:
        failures.append(f"Data directory is not writable: {report.data_dir}")

    for name, available in report.native_dependencies.items():
        if not available:
            failures.append(f"Dependency {name} is missing.")

    if report.input_device is None:
        if report.settings.devices.input_device_id:
            failures.append(
                f"Configured input device is unavailable: {report.settings.devices.input_device_id}"
            )
        else:
            failures.append("No input device is available.")

    if report.output_device is None:
        if report.settings.devices.output_device_id:
            device_id = report.settings.devices.output_device_id
            failures.append(
                f"Configured output device is unavailable: {device_id}"
            )
        else:
            failures.append("No output device is available.")

    failures.extend(build_device_readiness_failures(report))
    failures.extend(f"Missing source: {source}" for source in report.missing_sources)
    return failures


def build_device_readiness_failures(report: DoctorReport) -> list[str]:
    failures: list[str] = []
    if report.input_device and report.input_device.max_input_channels < 1:
        failures.append("Selected input device does not expose an input channel.")
    if (
        report.output_device
        and report.output_device.max_output_channels < report.settings.audio.channels
    ):
        failures.append(
            "Selected output supports "
            f"{report.output_device.max_output_channels} channels, "
            f"but settings request {report.settings.audio.channels}."
        )
    return failures


def _settings_to_payload(settings: AppSettings) -> dict[str, object]:
    return {
        "sample_rate": settings.audio.sample_rate,
        "channels": settings.audio.channels,
        "loop_seconds": settings.audio.loop_seconds,
        "voice_stack_loop_seconds": settings.voice_stack.loop_seconds,
        "input_device_id": settings.devices.input_device_id,
        "output_device_id": settings.devices.output_device_id,
    }


def check_write_access(directory: Path) -> bool:
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ".secret_pond_write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        return probe.read_text(encoding="utf-8") == "ok"
    except OSError:
        return False
    finally:
        if probe.exists():
            probe.unlink()


def _safe_check_write_access(directory: Path) -> bool:
    try:
        return check_write_access(directory)
    except OSError:
        return False


def check_native_dependencies() -> dict[str, bool]:
    return {
        package: importlib.util.find_spec(package) is not None
        for package in REQUIRED_NATIVE_DEPENDENCIES
    }


def build_device_warnings(
    input_device: AudioDeviceInfo | None,
    output_device: AudioDeviceInfo | None,
    settings: AppSettings,
) -> list[str]:
    return shared_device_warnings(input_device, output_device, settings)


def run_serve(host: str, port: int) -> int:
    import uvicorn

    uvicorn.run("secret_pond.app:app", host=host, port=port)
    return 0


def run_rebuild_test_library(root: Path) -> int:
    paths = ProjectPaths(root)
    paths.ensure_directories()
    try:
        settings = SettingsStore(paths).load_for_startup().active
    except Exception as exc:
        print(f"Rebuild test_library failed: settings unavailable ({exc})", file=sys.stderr)
        return 1

    if settings.voice_stack.mode != "test_library":
        print(
            "Rebuild test_library requires active voice_stack.mode to be test_library "
            f"(current: {settings.voice_stack.mode}).",
            file=sys.stderr,
        )
        return 1

    try:
        stack_result = VoiceStackStore(paths).rebuild_from_test_library(settings)
        render_result = LayerRenderer(paths).render_layer("voice", settings)
    except Exception as exc:
        print(f"Rebuild test_library failed: {exc}", file=sys.stderr)
        return 1

    print("Rebuilt test_library voice stack")
    print(f"  added_chunks={stack_result.added_chunks}")
    print(f"  raw_path={paths.voice_stack_raw.as_posix()}")
    print(f"  rendered_path={render_result.output_path.as_posix()}")
    print(f"  peak_before_guard={stack_result.peak_before_guard:.6f}")
    print(f"  peak_after_guard={stack_result.peak_after_guard:.6f}")
    print(f"  gain_reduction_db={stack_result.gain_reduction_db:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
