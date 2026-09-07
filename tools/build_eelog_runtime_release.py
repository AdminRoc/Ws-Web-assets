#!/usr/bin/env python3
"""Build a deterministic EELog public-runtime release descriptor."""
import argparse
import hashlib
import json
from pathlib import Path


ARTIFACTS = {
    "translationsScript": "js/wf-translations.js",
    "i18nJson": "data/i18n/wf-i18n.json",
    "arbBaselineSeed": "data/arbitration-metrics/arb-node-baseline.js",
    "arbBaselineJson": "data/arbitration-metrics/arb-node-baseline.json",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-root", default=".")
    parser.add_argument("--assets-revision", required=True, help="Immutable assets commit containing all four artifacts")
    parser.add_argument("--out", default="data/eelog-runtime-release.json")
    args = parser.parse_args()
    root = Path(args.assets_root).resolve()
    artifacts = {}
    for name, relative in ARTIFACTS.items():
        path = root / relative
        if not path.is_file():
            raise SystemExit(f"missing runtime artifact: {path}")
        if path.suffix == ".json":
            read_json(path)
        artifacts[name] = {"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size}

    seed = read_json(root / ARTIFACTS["arbBaselineJson"])
    seed_js = (root / ARTIFACTS["arbBaselineSeed"]).read_text(encoding="utf-8")
    marker = "WF.ARB_NODE_BASELINE_DATA="
    if marker not in seed_js:
        raise SystemExit("baseline seed does not expose WF.ARB_NODE_BASELINE_DATA")
    if str(seed.get("generatedAt")) not in seed_js:
        raise SystemExit("baseline JS/JSON generatedAt mismatch")

    release = {
        "schemaVersion": 1,
        "assetsRevision": args.assets_revision,
        "artifacts": artifacts,
    }
    output = root / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(output), "artifacts": len(artifacts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
