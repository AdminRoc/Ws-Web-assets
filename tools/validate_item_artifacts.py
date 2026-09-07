#!/usr/bin/env python3
"""Validate the item-data contract without mutating Ws-Web, assets, or ITEM_KV."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release_bytes(path):
    # GitHub Actions publishes Linux LF bytes; local Windows worktrees may use CRLF.
    return path.read_bytes().replace(b"\r\n", b"\n")


def release_digest(path):
    return hashlib.sha256(release_bytes(path)).hexdigest()


def parse_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid JSON: {error}") from error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, help="Local Ws-Web root")
    parser.add_argument("--assets-root", default=".", help="Local Ws-Web-assets root")
    parser.add_argument("--contract", default="item-artifact-contract.json")
    parser.add_argument("--report", help="Optional JSON report path")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    assets_root = Path(args.assets_root).resolve()
    contract = parse_json(assets_root / args.contract)
    release = parse_json(assets_root / "data/item/item-release.json")
    release_artifacts = release.get("artifacts", {})
    limit = int(contract["kv_value_limit_bytes"])
    report = {"schema_version": 1, "artifacts": [], "errors": []}

    keys = set()
    for artifact in contract["artifacts"]:
        owner = artifact.get("source_repository", contract["source_repository"])
        root = assets_root if owner == contract["asset_repository"] else source_root
        source = root / artifact["source_path"]
        asset = assets_root / artifact["asset_path"]
        entry = {"id": artifact["id"], "source": str(source), "asset": str(asset)}

        if not source.is_file():
            report["errors"].append(f"{artifact['id']}: missing source {source}")
            report["artifacts"].append(entry)
            continue

        try:
            parse_json(source)
        except ValueError as error:
            report["errors"].append(f"{artifact['id']}: {error}")
            report["artifacts"].append(entry)
            continue

        entry["bytes"] = source.stat().st_size
        entry["sha256"] = digest(source)
        entry["delivery"] = artifact["delivery"]
        entry["asset_present"] = asset.is_file()
        entry["asset_matches_source"] = asset.is_file() and digest(asset) == entry["sha256"]

        key = artifact.get("kv_key")
        if key:
            if key in keys:
                report["errors"].append(f"{artifact['id']}: duplicate KV key {key}")
            keys.add(key)
            entry["kv_key"] = key
            entry["kv_eligible"] = entry["bytes"] <= limit
            if artifact["delivery"] == "kv-and-assets" and not entry["kv_eligible"]:
                report["errors"].append(f"{artifact['id']}: {entry['bytes']} bytes exceeds {limit}-byte KV limit")

        if artifact["delivery"] in ("kv-and-assets", "assets-only") and not entry["asset_matches_source"]:
            report["errors"].append(f"{artifact['id']}: assets mirror missing or differs from source")

        release_entry = release_artifacts.get(artifact["id"])
        if not release_entry:
            report["errors"].append(f"{artifact['id']}: missing release metadata")
        elif not asset.is_file() or release_entry.get("sha256") != release_digest(asset) or release_entry.get("bytes") != len(release_bytes(asset)):
            report["errors"].append(f"{artifact['id']}: release metadata differs from assets mirror")
        report["artifacts"].append(entry)

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
