#!/usr/bin/env python3
"""Mirror the declared item artifacts from Ws-Web without modifying its source data."""
import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_revision(root):
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, help="Local Ws-Web root")
    parser.add_argument("--assets-root", default=".", help="Local Ws-Web-assets root")
    parser.add_argument("--contract", default="item-artifact-contract.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    assets_root = Path(args.assets_root).resolve()
    contract = read_json(assets_root / args.contract)
    release = {
        "schema_version": 1,
        "release_id": source_revision(source_root),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_repository": contract["source_repository"],
        "artifacts": {},
    }
    changed = []

    for artifact in contract["artifacts"]:
        owner = artifact.get("source_repository", contract["source_repository"])
        origin_root = assets_root if owner == contract["asset_repository"] else source_root
        source = origin_root / artifact["source_path"]
        target = assets_root / artifact["asset_path"]
        if not source.is_file():
            raise SystemExit(f"missing required source: {source}")
        read_json(source)
        digest = sha256(source)
        if artifact["delivery"] in ("kv-and-assets", "assets-only"):
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or sha256(target) != digest:
                changed.append(str(target.relative_to(assets_root)))
                if not args.dry_run:
                    shutil.copy2(source, target)
        release["artifacts"][artifact["id"]] = {
            "path": artifact["asset_path"],
            "sha256": digest,
            "bytes": source.stat().st_size,
            "delivery": artifact["delivery"],
            "kv_key": artifact.get("kv_key"),
        }

    release_path = assets_root / "data/item/item-release.json"
    release_text = json.dumps(release, ensure_ascii=False, indent=2) + "\n"
    if not release_path.is_file() or release_path.read_text(encoding="utf-8") != release_text:
        changed.append(str(release_path.relative_to(assets_root)))
        if not args.dry_run:
            release_path.parent.mkdir(parents=True, exist_ok=True)
            release_path.write_text(release_text, encoding="utf-8")

    print(json.dumps({"dry_run": args.dry_run, "release_id": release["release_id"], "changed": changed}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
