from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ENTRY = ROOT / "src/secret_pond/web/frontend/graph_eq_inline.js"
STATIC_BUNDLE = ROOT / "src/secret_pond/web/static/graph_eq_inline.bundle.js"


def test_weq8c_frontend_entry_declares_adapter_contract() -> None:
    source = FRONTEND_ENTRY.read_text(encoding="utf-8")

    assert "weq8c" in source
    assert "secretPondGraphEq" in source
    assert "toSecretPondEqPoints" in source
    assert "fromSecretPondEqPoints" in source
    assert "MAX_SECRET_POND_EQ_POINTS" in source
    assert "SUPPORTED_SECRET_POND_TYPES" in source


def test_committed_weq8c_bundle_exists_for_fastapi_runtime() -> None:
    bundle = STATIC_BUNDLE.read_text(encoding="utf-8")

    assert "customElements" in bundle
    assert "secretPondGraphEq" in bundle
    assert "toSecretPondEqPoints" in bundle
    assert "fromSecretPondEqPoints" in bundle
