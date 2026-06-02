from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from secret_pond.audio.devices import AudioDeviceInfo, AudioDeviceRegistry, SoundDeviceRegistry
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths

REQUIRED_NATIVE_DEPENDENCIES = ("numpy", "sounddevice", "soundfile", "scipy", "pedalboard")


@dataclass(frozen=True)
class DoctorReport:
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secret-pond")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="Check local runtime and audio devices.")
    doctor_parser.add_argument("--root", type=Path, default=Path.cwd())

    serve_parser = subparsers.add_parser("serve", help="Run the local web server.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(args.root)
    if args.command == "serve":
        return run_serve(args.host, args.port)

    parser.error("unknown command")
    return 2


def run_doctor(root: Path) -> int:
    paths = ProjectPaths(root)
    try:
        report = build_doctor_report(paths, SoundDeviceRegistry(), AppSettings())
    except Exception as exc:  # pragma: no cover - depends on host audio stack
        print(f"Audio devices: unavailable ({exc})")
        return 1

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

    return 0


def build_doctor_report(
    paths: ProjectPaths,
    registry: AudioDeviceRegistry,
    settings: AppSettings,
) -> DoctorReport:
    paths.ensure_directories()

    native_dependencies = check_native_dependencies()
    input_devices = registry.list_input_devices()
    output_devices = registry.list_output_devices()
    input_device = registry.validate_input(settings.devices.input_device_id)
    output_device = registry.validate_output(settings.devices.output_device_id)
    missing_sources = [
        source for source in (paths.low_source, paths.mid_source) if not source.exists()
    ]
    warnings = build_device_warnings(input_device, output_device, settings)

    return DoctorReport(
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
    )


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
    warnings: list[str] = []
    if input_device and input_device.max_input_channels < 1:
        warnings.append("Selected input device does not expose an input channel.")
    if output_device and output_device.max_output_channels < settings.audio.channels:
        warnings.append(
            "Selected output supports "
            f"{output_device.max_output_channels} channels, "
            f"but settings request {settings.audio.channels}."
        )
    if output_device and output_device.default_sample_rate not in (
        None,
        settings.audio.sample_rate,
    ):
        warnings.append(
            "Selected output default sample rate is "
            f"{output_device.default_sample_rate}, "
            f"but settings request {settings.audio.sample_rate}."
        )
    return warnings


def run_serve(host: str, port: int) -> int:
    import uvicorn

    uvicorn.run("secret_pond.app:app", host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
