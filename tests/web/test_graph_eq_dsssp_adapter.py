from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "src/secret_pond/web/frontend/graph_eq_dsssp_adapter.mjs"
DSSSP_ENTRY = ROOT / "src/secret_pond/web/frontend/graph_eq_inline.jsx"
DSSSP_BUNDLE = ROOT / "src/secret_pond/web/static/graph_eq_dsssp_island.bundle.js"
LEGACY_EQ_ENTRY = ROOT / "src/secret_pond/web/frontend/graph_eq_inline.js"
LEGACY_EQ_BUNDLE = ROOT / "src/secret_pond/web/static/graph_eq_inline.bundle.js"
LEGACY_EQ_TEST = ROOT / ("tests/web/test_graph_eq_" + "weq" + "8c_adapter.py")
PACKAGE_JSON = ROOT / "package.json"


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


def test_dsssp_dependency_contract_replaces_legacy_runtime() -> None:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    dependencies = package["dependencies"]
    build_script = package["scripts"]["build:graph-eq"]
    legacy_package_name = "weq" + "8c"

    assert dependencies["dsssp"] == "0.6.4"
    assert dependencies["react"].startswith("^18.")
    assert dependencies["react-dom"].startswith("^18.")
    assert legacy_package_name not in dependencies
    assert "graph_eq_inline.jsx" in build_script
    assert "graph_eq_dsssp_island.bundle.js" in build_script
    assert "graph_eq_inline.js --bundle" not in build_script
    assert "graph_eq_inline.bundle.js" not in build_script
    assert not LEGACY_EQ_ENTRY.exists()
    assert not LEGACY_EQ_BUNDLE.exists()
    assert not LEGACY_EQ_TEST.exists()


def test_dsssp_adapter_maps_secret_pond_points_with_pinned_shelves() -> None:
    output = run_node(
        f"""
import {{
  displayPositionForPoint,
  graphEqDisplayConfig,
  toDssspFilters,
  toSecretPondPoints
}} from {json.dumps(ADAPTER.as_uri())};

const points = [
  {{ id: "low", type: "low_shelf", frequency_hz: 80, gain_db: 3, q: 0.707 }},
  {{ id: "mid", type: "bell", frequency_hz: 1000, gain_db: -4, q: 1.2 }},
  {{ id: "high", type: "high_shelf", frequency_hz: 10000, gain_db: 5, q: 0.707 }},
];
const displayFilters = toDssspFilters(points);
const filters = displayFilters.map((filter) => ({{ ...filter }}));
filters[0].freq = 320;
filters[1].freq = 2400;
filters[2].freq = 12000;
const roundTrip = toSecretPondPoints(filters, points);
const positions = points.map((point) => displayPositionForPoint(point, graphEqDisplayConfig));
console.log(JSON.stringify({{ displayFilters, roundTrip, positions }}));
"""
    )

    assert [item["type"] for item in output["displayFilters"]] == [
        "LOWSHELF2",
        "PEAK",
        "HIGHSHELF2",
    ]
    assert output["displayFilters"][0]["freq"] == 80
    assert output["displayFilters"][2]["freq"] == 10000
    assert output["roundTrip"][0]["frequency_hz"] == 80
    assert output["roundTrip"][1]["frequency_hz"] == 2400
    assert output["roundTrip"][2]["frequency_hz"] == 10000
    assert output["positions"][0]["x"] == 0
    assert output["positions"][2]["x"] == 1
    assert 0 < output["positions"][1]["x"] < 1


def test_dsssp_adapter_defaults_missing_bell_q_to_musical_one_octave_width() -> None:
    output = run_node(
        f"""
import {{
  fromDssspChangeEvent,
  toDssspFilters,
  toSecretPondPoints
}} from {json.dumps(ADAPTER.as_uri())};

const points = [
  {{ id: "low", type: "low_shelf", frequency_hz: 80, gain_db: 0 }},
  {{ id: "mid", type: "bell", frequency_hz: 1000, gain_db: 0 }},
  {{ id: "high", type: "high_shelf", frequency_hz: 10000, gain_db: 0 }},
];
const displayFilters = toDssspFilters(points);
const roundTrip = toSecretPondPoints([{{ id: "created", type: "PEAK", freq: 1500, gain: 3 }}], []);
const event = fromDssspChangeEvent({{ type: "PEAK", freq: 1600, gain: -2 }});
console.log(JSON.stringify({{ displayFilters, roundTrip, event }}));
"""
    )

    assert output["displayFilters"][0]["q"] == 0.707
    assert output["displayFilters"][1]["q"] == 1.4
    assert output["displayFilters"][2]["q"] == 0.707
    assert output["roundTrip"][0]["q"] == 1.4
    assert output["event"]["point"]["q"] == 1.4


def test_dsssp_adapter_keeps_shelf_cutoff_frequency_even_with_custom_ids() -> None:
    output = run_node(
        f"""
import {{
  displayPositionForPoint,
  graphEqDisplayConfig,
  isLockedEndpointPoint,
  toDssspFilters,
  toSecretPondPoints
}} from {json.dumps(ADAPTER.as_uri())};

const points = [
  {{ id: "custom-low", type: "low_shelf", frequency_hz: 280, gain_db: 4, q: 0.7 }},
  {{ id: "custom-mid", type: "bell", frequency_hz: 1200, gain_db: -2, q: 1.1 }},
  {{ id: "custom-high", type: "high_shelf", frequency_hz: 6400, gain_db: 3, q: 0.7 }},
];
const displayFilters = toDssspFilters(points);
const filters = displayFilters.map((filter) => ({{ ...filter }}));
filters[0].freq = 1800;
filters[2].freq = 1200;
filters[2].gain = -6;
const roundTrip = toSecretPondPoints(filters, points);
const locked = points.map((point, index) => isLockedEndpointPoint(point, index, points));
const positions = points.map((point, index) => displayPositionForPoint(
  point,
  graphEqDisplayConfig,
  index,
  points,
));
console.log(JSON.stringify({{ displayFilters, roundTrip, locked, positions }}));
"""
    )

    assert output["locked"] == [True, False, True]
    assert output["displayFilters"][0]["freq"] == 280
    assert output["displayFilters"][2]["freq"] == 6400
    assert output["roundTrip"][0]["frequency_hz"] == 280
    assert output["roundTrip"][2]["frequency_hz"] == 6400
    assert output["roundTrip"][2]["gain_db"] == -6
    assert output["positions"][0]["x"] == 0
    assert output["positions"][2]["x"] == 1


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


def test_dsssp_react_island_source_and_build_script_are_current_runtime_path() -> None:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    source = DSSSP_ENTRY.read_text(encoding="utf-8")

    assert "graph_eq_inline.jsx" in package["scripts"]["build:graph-eq"]
    assert "graph_eq_dsssp_island.bundle.js" in package["scripts"]["build:graph-eq"]
    if "build:graph-eq-dsssp" in package["scripts"]:
        assert package["scripts"]["build:graph-eq-dsssp"] == package["scripts"]["build:graph-eq"]

    assert "FrequencyResponseGraph" in source
    assert "mountEditor" in source
    assert "syncEditor" in source
    assert "unmountEditor" in source
    assert "data-graph-eq-dsssp-root" in source
    assert ("weq" + "8c") not in source.lower()


def test_dsssp_island_bundle_freshness_check_rebuilds_from_frontend_sources() -> None:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))

    assert (
        package["scripts"]["test:graph-eq-bundle"]
        == "node scripts/check_graph_eq_bundle_fresh.mjs"
    )

    dependency_output = run_node(
        f"""
import * as esbuild from "esbuild";

const result = await esbuild.build({{
  absWorkingDir: {json.dumps(str(ROOT))},
  bundle: true,
  entryPoints: ["src/secret_pond/web/frontend/graph_eq_inline.jsx"],
  format: "iife",
  globalName: "SecretPondDssspGraphEqBundle",
  jsx: "automatic",
  metafile: true,
  write: false,
}});

console.log(JSON.stringify({{
  includesAdapter: Object.keys(result.metafile.inputs).includes(
    "src/secret_pond/web/frontend/graph_eq_dsssp_adapter.mjs",
  ),
}}));
"""
    )
    assert dependency_output["includesAdapter"] is True

    subprocess.run(
        ["npm", "run", "test:graph-eq-bundle", "--", "--quiet"],
        cwd=ROOT,
        check=True,
    )


def test_dsssp_island_bundle_exposes_mount_contract_without_legacy_runtime() -> None:
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
    assert ("weq" + "8c") not in bundle.lower()
    assert ("weq" + "8-ui") not in bundle
