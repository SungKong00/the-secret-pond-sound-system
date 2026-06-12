from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "src/secret_pond/web/frontend/graph_eq_dsssp_adapter.mjs"
DSSSP_ENTRY = ROOT / "src/secret_pond/web/frontend/graph_eq_inline.jsx"
DSSSP_BUNDLE = ROOT / "src/secret_pond/web/static/graph_eq_dsssp_island.bundle.js"
WEQ8C_BUNDLE = ROOT / "src/secret_pond/web/static/graph_eq_inline.bundle.js"
PACKAGE_JSON = ROOT / "package.json"
PACKAGE_LOCK = ROOT / "package-lock.json"


def run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=True,
    )
    return json.loads(result.stdout)


def test_dsssp_dependency_contract_is_available_without_removing_weq8c_yet() -> None:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    dependencies = package["dependencies"]
    lock_dependencies = lock["packages"][""]["dependencies"]

    assert dependencies["dsssp"] == "0.6.4"
    assert dependencies["react"].startswith("^18.")
    assert dependencies["react-dom"].startswith("^18.")
    assert dependencies["weq8c"] == "0.3.5"
    assert lock_dependencies["dsssp"] == "0.6.4"
    assert lock_dependencies["weq8c"] == "0.3.5"


def test_dsssp_adapter_maps_secret_pond_points_and_locks_endpoints() -> None:
    output = run_node(
        f"""
import {{
  displayPositionForPoint,
  graphEqDisplayConfig,
  toDssspFilters,
  toSecretPondPoints
}} from {json.dumps(ADAPTER.as_uri())};

const points = [
  {{ id: "low", type: "low_shelf", frequency_hz: 120, gain_db: 3, q: 0.7 }},
  {{ id: "mid", type: "bell", frequency_hz: 1000, gain_db: -4, q: 1.2 }},
  {{ id: "high", type: "high_shelf", frequency_hz: 8000, gain_db: 5, q: 0.7 }},
];
const filters = toDssspFilters(points);
filters[0].freq = 320;
filters[1].freq = 2400;
filters[2].freq = 12000;
const roundTrip = toSecretPondPoints(filters, points);
const positions = points.map((point) => displayPositionForPoint(point, graphEqDisplayConfig));
console.log(JSON.stringify({{ filters, roundTrip, positions }}));
"""
    )

    assert [item["type"] for item in output["filters"]] == ["LOWSHELF2", "PEAK", "HIGHSHELF2"]
    assert output["filters"][0]["freq"] == 320
    assert output["roundTrip"][0]["frequency_hz"] == 120
    assert output["roundTrip"][1]["frequency_hz"] == 2400
    assert output["roundTrip"][2]["frequency_hz"] == 8000
    assert output["positions"][0]["x"] == 0
    assert output["positions"][2]["x"] == 1
    assert 0 < output["positions"][1]["x"] < 1


def test_dsssp_adapter_marks_drag_end_and_rejects_notch() -> None:
    output = run_node(
        f"""
import {{ fromDssspChangeEvent, supportedDssspTypes }} from {json.dumps(ADAPTER.as_uri())};
const event = {{ index: 1, type: "PEAK", freq: 2400, gain: 6, q: 2, ended: true }};
console.log(JSON.stringify({{
  mapped: fromDssspChangeEvent(event),
  supported: supportedDssspTypes,
  hasNotch: supportedDssspTypes.includes("NOTCH")
}}));
"""
    )

    assert output["mapped"]["index"] == 1
    assert output["mapped"]["ended"] is True
    assert output["mapped"]["point"]["type"] == "bell"
    assert output["mapped"]["point"]["frequency_hz"] == 2400
    assert output["mapped"]["point"]["gain_db"] == 6
    assert output["mapped"]["point"]["q"] == 2
    assert output["hasNotch"] is False


def test_dsssp_react_island_source_and_build_script_keep_weq8c_runtime_path() -> None:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    source = DSSSP_ENTRY.read_text(encoding="utf-8")
    weq8c_bundle = WEQ8C_BUNDLE.read_text(encoding="utf-8")

    assert "graph_eq_inline.js" in package["scripts"]["build:graph-eq"]
    assert "graph_eq_inline.bundle.js" in package["scripts"]["build:graph-eq"]
    assert "build:graph-eq-dsssp" in package["scripts"]
    assert "graph_eq_inline.jsx" in package["scripts"]["build:graph-eq-dsssp"]
    assert "graph_eq_dsssp_island.bundle.js" in package["scripts"]["build:graph-eq-dsssp"]

    assert "FrequencyResponseGraph" in source
    assert "mountEditor" in source
    assert "syncEditor" in source
    assert "unmountEditor" in source
    assert "data-graph-eq-dsssp-root" in source
    assert "weq8c" not in source.lower()
    assert "weq8c" in weq8c_bundle.lower()
    assert "weq8-ui" in weq8c_bundle


def test_dsssp_island_bundle_exposes_mount_contract_without_weq8c() -> None:
    bundle = DSSSP_BUNDLE.read_text(encoding="utf-8")
    output = run_node(
        f"""
globalThis.window = globalThis;
await import({json.dumps(DSSSP_BUNDLE.as_uri())});
console.log(JSON.stringify({{
  hasGlobal: Boolean(globalThis.secretPondGraphEq),
  keys: Object.keys(globalThis.secretPondGraphEq || {{}}),
  hasDssspAlias: Boolean(globalThis.secretPondDssspGraphEq)
}}));
"""
    )

    assert output["hasGlobal"] is True
    assert output["hasDssspAlias"] is True
    assert {"mountEditor", "syncEditor", "unmountEditor"}.issubset(output["keys"])
    assert "FrequencyResponseGraph" in bundle
    assert "toDssspFilters" in bundle
    assert "weq8c" not in bundle.lower()
    assert "weq8-ui" not in bundle
