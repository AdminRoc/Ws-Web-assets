#!/usr/bin/env python3
"""Build a deterministic EELog public-runtime release descriptor."""
import argparse
import hashlib
import json
from pathlib import Path


ARTIFACTS = {
    "translationsScript": "js/wf-translations.js",
    "i18nJson": "data/i18n/wf-i18n.json",
}


def artifact_bytes(path):
    # Match the LF-normalized bytes stored in Git and served by jsDelivr.
    return path.read_bytes().replace(b"\r\n", b"\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-root", default=".")
    parser.add_argument("--assets-revision", required=True, help="Immutable Assets commit containing both translation artifacts")
    parser.add_argument("--out", default="data/eelog-runtime-release.json")
    args = parser.parse_args()
    root = Path(args.assets_root).resolve()
    artifacts = {}
    for name, relative in ARTIFACTS.items():
        path = root / relative
        if not path.is_file():
            raise SystemExit(f"missing runtime artifact: {path}")
        payload = artifact_bytes(path)
        if path.suffix == ".json":
            json.loads(payload.decode("utf-8"))
        artifacts[name] = {
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }

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
