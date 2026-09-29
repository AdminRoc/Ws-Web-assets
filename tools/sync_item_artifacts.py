#!/usr/bin/env python3
"""Mirror the declared item artifacts from Ws-Web without modifying its source data."""
import argparse
import hashlib
import json
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def release_bytes(path):
    """Use the bytes GitHub Actions commits, independent of Windows checkout EOLs."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def release_identifier(release):
    """Identify the declared artifact bytes, not unrelated source-repository commits."""
    identity = {
        "schema_version": release["schema_version"],
        "source_repository": release["source_repository"],
        "assets_release_path": release["assets_release_path"],
        "artifacts": release["artifacts"],
    }
    payload = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    # The browser contract currently accepts a 40-hex release id. Keep that shape
    # while deriving it from the SHA-256 digest of the complete artifact manifest.
    return hashlib.sha256(payload).hexdigest()[:40]


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
        "source_repository": contract["source_repository"],
        "assets_release_path": "data/item/item-release.json",
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
        payload = release_bytes(source)
        json.loads(payload.decode("utf-8"))
        digest = hashlib.sha256(payload).hexdigest()
        if artifact["delivery"] in ("kv-and-assets", "assets-only"):
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or release_bytes(target) != payload:
                changed.append(str(target.relative_to(assets_root)))
                if not args.dry_run:
                    target.write_bytes(payload)
        release["artifacts"][artifact["id"]] = {
            "path": artifact["asset_path"],
            "sha256": digest,
            "bytes": len(payload),
            "delivery": artifact["delivery"],
            "kv_key": artifact.get("kv_key"),
        }

    release["release_id"] = release_identifier(release)
    release_path = assets_root / "data/item/item-release.json"
    release_text = (json.dumps(release, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if not release_path.is_file() or release_bytes(release_path) != release_text:
        changed.append(str(release_path.relative_to(assets_root)))
        if not args.dry_run:
            release_path.parent.mkdir(parents=True, exist_ok=True)
            release_path.write_bytes(release_text)

    print(json.dumps({"dry_run": args.dry_run, "release_id": release["release_id"], "changed": changed}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
