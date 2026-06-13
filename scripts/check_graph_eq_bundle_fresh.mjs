import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";

const scriptPath = fileURLToPath(import.meta.url);
const root = path.resolve(path.dirname(scriptPath), "..");
const entryPoint = "src/secret_pond/web/frontend/graph_eq_inline.jsx";
const committedBundle = path.join(root, "src/secret_pond/web/static/graph_eq_dsssp_island.bundle.js");
const quiet = process.argv.includes("--quiet");

const tempDir = await mkdtemp(path.join(tmpdir(), "secret-pond-graph-eq-bundle-"));
const tempBundle = path.join(tempDir, "graph_eq_dsssp_island.bundle.js");

try {
  await esbuild.build({
    absWorkingDir: root,
    bundle: true,
    entryPoints: [entryPoint],
    format: "iife",
    globalName: "SecretPondDssspGraphEqBundle",
    jsx: "automatic",
    outfile: tempBundle,
    write: true,
  });

  const [expected, actual] = await Promise.all([
    readFile(tempBundle, "utf8"),
    readFile(committedBundle, "utf8"),
  ]);

  if (actual !== expected) {
    console.error(
      [
        "Graph EQ DSSSP bundle is stale.",
        "Run `npm run build:graph-eq-dsssp` after editing src/secret_pond/web/frontend/graph_eq_inline.jsx or its frontend imports.",
      ].join("\n"),
    );
    process.exitCode = 1;
  } else if (!quiet) {
    console.log("Graph EQ DSSSP bundle is fresh.");
  }
} finally {
  await rm(tempDir, { force: true, recursive: true });
}
