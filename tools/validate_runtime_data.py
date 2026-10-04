#!/usr/bin/env python3
"""Validate the non-item runtime data release contract and public readback."""
import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "runtime-data-contract.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
GROUPS = CONTRACT["groups"]


def paths_for(target):
    if target == "all":
        selected = GROUPS
    elif target in GROUPS:
        selected = {target: GROUPS[target]}
    else:
        raise ValueError(f"unknown runtime-data target: {target}")
    return [artifact["path"] for group in selected.values() for artifact in group["artifacts"]]


def json_read(path):
    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)


def require_text_map(value, label, *, minimum=0):
    if not isinstance(value, dict) or len(value) < minimum:
        raise ValueError(f"{label} is empty, malformed, or below minimum coverage {minimum}")
    for key, text in value.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(text, str) or not text.strip():
            raise ValueError(f"{label} contains an empty or malformed entry")


def parse_assignment(path, marker):
    source = path.read_text(encoding="utf-8")
    position = source.find(marker)
    if position < 0:
        raise ValueError(f"{path}: missing expected JavaScript assignment")
    decoded, end = json.JSONDecoder().raw_decode(source[position + len(marker):])
    if source[position + len(marker) + end:].strip() != ";":
        raise ValueError(f"{path}: unexpected trailing JavaScript after generated object")
    return decoded


def validate_rotation():
    payload = json_read(ROOT / "data/tenet-coda-rotation.json")
    if not isinstance(payload, dict):
        raise ValueError("Tenet/Coda rotation must be a JSON object")
    for faction in ("tenet", "coda"):
        section = payload.get(faction)
        rows = section.get("weapons") if isinstance(section, dict) else None
        if not isinstance(rows, list) or len(rows) < 3:
            raise ValueError(f"{faction} weapon table is empty or incomplete")
        names = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{faction} contains a malformed weapon row")
            name, element, bonus = row.get("name"), row.get("element"), row.get("bonusPct")
            if not isinstance(name, str) or not name.strip() or name in names:
                raise ValueError(f"{faction} contains a missing or duplicate weapon name")
            if not isinstance(element, str) or not element.strip():
                raise ValueError(f"{faction} contains a missing progenitor element")
            if (not isinstance(bonus, (int, float)) or isinstance(bonus, bool)
                    or not math.isfinite(bonus) or not 0 < bonus <= 100):
                raise ValueError(f"{faction} contains an invalid progenitor bonus")
            names.add(name)
        if (not isinstance(section.get("changedAt"), int) or isinstance(section["changedAt"], bool)
                or section["changedAt"] <= 0):
            raise ValueError(f"{faction} has an invalid change timestamp")
    batch = payload["coda"].get("batch")
    if not isinstance(batch, str) or len(batch) != 1 or not batch.isalpha() or not batch.isascii():
        raise ValueError("Coda batch label is invalid")
    if not isinstance(payload.get("fetchedAt"), str) or not payload["fetchedAt"].endswith("Z"):
        raise ValueError("Tenet/Coda artifact has no UTC fetch timestamp")


def validate_translations(core_root, item_names_path=None):
    i18n_path = ROOT / "data/i18n/wf-i18n.json"
    script_path = ROOT / "js/wf-translations.js"
    names_path = Path(item_names_path) if item_names_path else ROOT / "data/item/item-names-zh.json"
    item_contract = json_read(ROOT / "item-artifact-contract.json")
    declared_item_names = (
        isinstance(item_contract, dict)
        and any(
            artifact.get("source_path") == "data/item/item-names-zh.json"
            and artifact.get("asset_path") == "data/item/item-names-zh.json"
            for artifact in item_contract.get("artifacts", [])
            if isinstance(artifact, dict)
        )
    )
    if not declared_item_names:
        raise ValueError("the shared i18n input is not declared by item-artifact-contract.json")
    i18n = json_read(i18n_path)
    names = json_read(names_path)
    curated = json_read(core_root / "data/wf-translations.json")
    if not isinstance(i18n, dict) or not isinstance(names, dict) or not isinstance(curated, dict):
        raise ValueError("shared i18n inputs or output must be JSON objects")

    tables = ("byPath", "byName", "byLang", "override", "planet", "mission", "misc")
    for table in tables:
        minimum = 50 if table == "byName" else (100 if table in ("byPath", "byLang") else 0)
        require_text_map(i18n.get(table), f"wf-i18n.{table}", minimum=minimum)
    expected_names = {key: value for key, value in names.items() if not str(key).startswith("_")}
    if i18n["byName"] != expected_names:
        raise ValueError("wf-i18n.byName does not match the contracted item-name input")

    expected_categories = {
        "ITEM_OVERRIDE": "override",
        "PLANET": "planet",
        "MISSION_TYPE": "mission",
        "MISC": "misc",
    }
    expected_script = {key: value for key, value in curated.items() if key != "_comment"}
    for category, values in expected_script.items():
        require_text_map(values, f"Core {category}")
    for source_key, output_key in expected_categories.items():
        values = curated.get(source_key, {})
        if i18n[output_key] != values:
            raise ValueError(f"wf-i18n.{output_key} does not match the curated Core source")
    generated_script = parse_assignment(script_path, "window.WF_TR = ")
    if generated_script != expected_script:
        raise ValueError("wf-translations.js differs from the curated Core translation source")

    script_dir = core_root / ".github/scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import gen_i18n  # pylint: disable=import-outside-toplevel

    expected_by_path = gen_i18n._strip_meta(gen_i18n.parse_i18n_zh(str(core_root)))
    if i18n["byPath"] != expected_by_path:
        raise ValueError("wf-i18n.byPath does not match the curated Core source")

    node_names = json_read(ROOT / "data/worldstate/cn-solnodes.json")
    require_text_map(node_names, "cn-solnodes", minimum=100)


def changed_paths(kind):
    command = ["git", "diff", "--name-only", "HEAD"] if kind == "worktree" else ["git", "diff", "--cached", "--name-only"]
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    paths = set(result.stdout.splitlines())
    if kind == "worktree":
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        paths.update(untracked.stdout.splitlines())
    return paths


def validate_scope(target, kind):
    actual = changed_paths(kind)
    allowed = set(paths_for(target))
    unexpected = sorted(actual - allowed)
    if unexpected:
        raise ValueError(f"{kind} contains changes outside the {target} runtime-data contract: {unexpected}")


def fetch_bytes(url):
    request = urllib.request.Request(url, headers={"User-Agent": "wfspeed-runtime-data-verifier/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.status, response.read()


def git_blob_bytes(path):
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=ROOT, check=True, capture_output=True,
    )
    return result.stdout


def purge_and_verify(target, revision, purge):
    if not revision or not all(c in "0123456789abcdef" for c in revision.lower()):
        raise ValueError("an immutable hexadecimal Assets revision is required for public readback")
    for path in paths_for(target):
        if purge:
            url = f"https://purge.jsdelivr.net/gh/AdminRoc/Ws-Web-assets@main/{path}"
            request = urllib.request.Request(url, headers={"User-Agent": "wfspeed-runtime-data-verifier/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"jsDelivr purge failed for {path}: HTTP {response.status}")
        # Compare against committed bytes, not a Windows CRLF-normalized worktree copy.
        expected = git_blob_bytes(path)
        expected_hash = hashlib.sha256(expected).hexdigest()
        for channel in ("main", revision):
            url = f"https://cdn.jsdelivr.net/gh/AdminRoc/Ws-Web-assets@{channel}/{path}"
            last = "no response"
            for attempt in range(20):
                try:
                    status, actual = fetch_bytes(url)
                    actual_hash = hashlib.sha256(actual).hexdigest()
                    if status == 200 and actual_hash == expected_hash:
                        print(f"PUBLIC READBACK OK {path} @{channel} bytes={len(actual)} sha256={actual_hash}")
                        break
                    last = f"HTTP {status}, sha256={actual_hash}, expected={expected_hash}"
                except (urllib.error.URLError, TimeoutError, OSError) as error:
                    last = type(error).__name__
                if attempt < 19:
                    time.sleep(5)
            else:
                raise RuntimeError(f"public readback mismatch for {path} @{channel}: {last}")


def verify_eelog_release():
    expected_paths = {
        "translationsScript": "js/wf-translations.js",
        "i18nJson": "data/i18n/wf-i18n.json",
    }
    # Git checkout may normalize this tracked JSON to CRLF on Windows; the public
    # descriptor and its hashes are based on the committed LF bytes.
    local_bytes = git_blob_bytes("data/eelog-runtime-release.json")
    local_hash = hashlib.sha256(local_bytes).hexdigest()
    descriptor_url = (
        "https://raw.githubusercontent.com/AdminRoc/Ws-Web-assets/main/"
        f"data/eelog-runtime-release.json?v={time.time_ns()}"
    )
    last = "no response"
    for attempt in range(20):
        try:
            status, actual = fetch_bytes(descriptor_url)
            if status == 200 and hashlib.sha256(actual).hexdigest() == local_hash:
                break
            last = f"HTTP {status}, descriptor hash mismatch"
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = type(error).__name__
        if attempt < 19:
            time.sleep(5)
    else:
        raise RuntimeError(f"EELog runtime descriptor public readback mismatch: {last}")

    descriptor = json.loads(actual.decode("utf-8"))
    revision = descriptor.get("assetsRevision") if isinstance(descriptor, dict) else None
    artifacts = descriptor.get("artifacts") if isinstance(descriptor, dict) else None
    if (not isinstance(descriptor, dict)
            or descriptor.get("schemaVersion") != 1
            or not isinstance(revision, str)
            or len(revision) not in (40, 64)
            or any(char not in "0123456789abcdef" for char in revision.lower())
            or not isinstance(artifacts, dict)
            or set(artifacts) != set(expected_paths)):
        raise ValueError("EELog runtime descriptor schema, revision, or artifact set is invalid")

    for artifact_id, expected_path in expected_paths.items():
        artifact = artifacts[artifact_id]
        if (not isinstance(artifact, dict) or artifact.get("path") != expected_path
                or not isinstance(artifact.get("sha256"), str)
                or len(artifact["sha256"]) != 64
                or not isinstance(artifact.get("bytes"), int)
                or isinstance(artifact.get("bytes"), bool)
                or artifact["bytes"] <= 0):
            raise ValueError(f"EELog runtime descriptor entry is malformed: {artifact_id}")
        url = f"https://cdn.jsdelivr.net/gh/AdminRoc/Ws-Web-assets@{revision}/{expected_path}"
        expected_hash = artifact["sha256"]
        last = "no response"
        for attempt in range(20):
            try:
                status, payload = fetch_bytes(url)
                actual_hash = hashlib.sha256(payload).hexdigest()
                if (status == 200 and actual_hash == expected_hash
                        and len(payload) == artifact["bytes"]):
                    print(f"EELOG RELEASE READBACK OK {expected_path} @{revision} bytes={len(payload)} sha256={actual_hash}")
                    break
                last = f"HTTP {status}, bytes={len(payload)}, sha256={actual_hash}"
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last = type(error).__name__
            if attempt < 19:
                time.sleep(5)
        else:
            raise RuntimeError(f"EELog pinned artifact readback mismatch for {expected_path}: {last}")
    print(f"EELog descriptor public readback OK sha256={local_hash}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["all", *GROUPS], required=True)
    parser.add_argument("--core-root", type=Path)
    parser.add_argument("--item-names", type=Path)
    parser.add_argument("--list-paths", action="store_true")
    parser.add_argument("--check-worktree", action="store_true")
    parser.add_argument("--check-staged", action="store_true")
    parser.add_argument("--verify-public", action="store_true")
    parser.add_argument("--verify-eelog-release", action="store_true")
    parser.add_argument("--purge", action="store_true")
    parser.add_argument("--revision")
    args = parser.parse_args(argv)

    try:
        if args.list_paths:
            print("\n".join(paths_for(args.target)))
            return 0
        selected = set(GROUPS) if args.target == "all" else {args.target}
        if "rotation" in selected:
            validate_rotation()
        if "translations" in selected:
            if not args.core_root:
                raise ValueError("--core-root is required for translation validation")
            validate_translations(args.core_root.resolve(), args.item_names)
        if args.check_worktree:
            validate_scope(args.target, "worktree")
        if args.check_staged:
            validate_scope(args.target, "staged")
        if args.verify_public:
            purge_and_verify(args.target, args.revision, args.purge)
        if args.verify_eelog_release:
            verify_eelog_release()
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"runtime-data validation failed: {error}", file=sys.stderr)
        return 1
    print(f"runtime-data validation OK target={args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
