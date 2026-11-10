#!/usr/bin/env python3
"""Publish a verified, bounded Item snapshot to EdgeOne Makers KV."""
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "AdminRoc/Ws-Web-assets"
RELEASE_PATH = "data/item/item-release.json"
ENDPOINT = "https://item.wfspeed.run"
KEY = "item_release_meta"
CHUNK_BYTES = 512 * 1024
SLOT_CHUNKS = 64


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def get(url, timeout=45, attempts=4, delay=2):
    request = urllib.request.Request(url, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt + 1 == attempts:
                raise
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            if attempt + 1 == attempts:
                raise
        time.sleep(delay * (attempt + 1))
    raise RuntimeError("unreachable GET retry state")


def current_pointer():
    url = ENDPOINT + "/api/kv?key=" + KEY + "&v=" + str(time.time_ns())
    try:
        return json.loads(get(url, timeout=15).decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def immutable_identity(pointer):
    if not isinstance(pointer, dict):
        return None
    return {
        "schema_version": pointer.get("schema_version"),
        "source_repository": pointer.get("source_repository"),
        "assets_release_path": pointer.get("assets_release_path"),
        "release_id": pointer.get("release_id"),
        "artifacts": pointer.get("artifacts"),
    }


def verify_pointer_after_write(expected, attempts=10, delay=3):
    for attempt in range(attempts):
        try:
            actual = current_pointer()
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt + 1 == attempts:
                raise
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            if attempt + 1 == attempts:
                raise
        else:
            if actual == expected:
                return
            if actual and dict(actual, snapshot={
                key: value for key, value in (actual.get("snapshot") or {}).items()
                if key != "switched_at"
            }) == expected:
                return
        if attempt + 1 < attempts:
            time.sleep(delay * (attempt + 1))
    raise SystemExit("Item release pointer readback mismatch after bounded verification")


def snapshot_url(commit, slot, start, count):
    return ENDPOINT + "/api/item-artifact?" + urllib.parse.urlencode(
        {"revision": commit, "slot": slot, "start": start, "count": count}
    )


def stage_snapshot(commit, previous, payloads, token):
    active = (previous or {}).get("snapshot") or {}
    slot = "b" if active.get("slot") == "a" else "a"
    files = {}
    chunks = []
    for path, raw in payloads.items():
        parts = [raw[offset:offset + CHUNK_BYTES] for offset in range(0, len(raw), CHUNK_BYTES)]
        if not 1 <= len(parts) <= 16:
            raise SystemExit("Item snapshot file exceeds its supported size: " + path)
        files[path] = {"start": len(chunks), "count": len(parts), "sha256": sha(raw)}
        chunks.extend(parts)
    if len(chunks) > SLOT_CHUNKS:
        raise SystemExit("Item snapshot exceeds the fixed two-slot KV budget")
    def stage_chunk(index, chunk):
        url = snapshot_url(commit, slot, index, 1)
        try:
            if get(url + "&v=" + str(time.time_ns()), attempts=4) == chunk:
                return
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        request = urllib.request.Request(url, data=base64.b64encode(chunk), method="POST",
            headers={"Authorization": "Bearer " + token, "Content-Type": "text/plain"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    response.read()
                break
            except (urllib.error.URLError, TimeoutError) as error:
                code = getattr(error, "code", None)
                if code in (400, 401, 403, 409, 413):
                    raise
                print(f"Chunk {index} write response inconclusive ({code}); verifying before any retry", file=sys.stderr)
                time.sleep(5)
                try:
                    if get(url + "&v=" + str(time.time_ns()), attempts=4) == chunk:
                        break
                except urllib.error.HTTPError as read_error:
                    if read_error.code != 404:
                        raise
                if attempt == 2 or current_pointer() != previous:
                    raise SystemExit("KV chunk readback mismatch") from error
    for index, chunk in enumerate(chunks):
        stage_chunk(index, chunk)
    for path, raw in payloads.items():
        file = files[path]
        url = snapshot_url(commit, slot, file["start"], file["count"])
        for attempt in range(7):
            try:
                actual = get(url + "&v=" + str(time.time_ns()), attempts=1)
                if len(actual) == len(raw) and sha(actual) == file["sha256"]:
                    break
            except (urllib.error.URLError, TimeoutError):
                pass
            if attempt == 6:
                raise SystemExit("KV snapshot readback mismatch: " + path)
            time.sleep(11)
            if attempt in (2, 4):
                if current_pointer() != previous:
                    raise SystemExit("Active Item pointer changed during repair")
                for index in range(file["start"], file["start"] + file["count"]):
                    stage_chunk(index, chunks[index])
    return {"slot": slot, "files": files}


def main():
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if len(commit) != 40:
        raise SystemExit("Invalid assets commit SHA")
    remote = subprocess.check_output(["git", "ls-remote", "origin", "refs/heads/main"], cwd=ROOT, text=True).split()
    if not remote or remote[0].lower() != commit.lower():
        raise SystemExit("Candidate release is not the current remote main; refusing pointer publication")

    release_raw = (ROOT / RELEASE_PATH).read_bytes()
    release = json.loads(release_raw.decode("utf-8"))
    if release.get("schema_version") != 1 or release.get("source_repository") != "Ws-Web":
        raise SystemExit("Item release schema or source repository mismatch")
    if release.get("assets_release_path") != RELEASE_PATH:
        raise SystemExit("Item release path mismatch")
    artifacts = release.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise SystemExit("Item release has no declared artifacts")

    raw_base = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/"
    remote_release = get(raw_base + RELEASE_PATH)
    if json.loads(remote_release.decode("utf-8")) != release:
        raise SystemExit("Pinned raw item release differs from the pushed release")
    payloads = {"item-release.json": remote_release}
    for name, artifact in sorted(artifacts.items()):
        path = artifact.get("path")
        expected_sha = artifact.get("sha256")
        expected_bytes = artifact.get("bytes")
        if not path or not isinstance(expected_sha, str) or len(expected_sha) != 64 or not isinstance(expected_bytes, int):
            raise SystemExit("Incomplete item release entry: " + name)
        raw = get(raw_base + urllib.parse.quote(path, safe="/._-"))
        if len(raw) != expected_bytes or sha(raw) != expected_sha.lower():
            raise SystemExit("Pinned raw item artifact mismatch: " + path)
        payloads[path.removeprefix("data/item/")] = raw

    pointer = dict(release)
    pointer["assets_revision"] = commit
    previous = current_pointer()
    if previous and previous.get("snapshot") and immutable_identity(previous) == immutable_identity(pointer):
        print(f"ITEM RELEASE POINTER ALREADY CURRENT commit={commit} release_id={pointer['release_id']} files_checked={len(artifacts)}")
        return

    token = os.environ.get("KV_WRITE_TOKEN", "")
    if not token:
        raise SystemExit("Missing KV_WRITE_TOKEN")
    pointer["generation"] = os.environ.get("GITHUB_RUN_ID", str(time.time_ns()))
    pointer["snapshot"] = stage_snapshot(commit, previous, payloads, token)
    if current_pointer() != previous:
        raise SystemExit("Active Item pointer changed during staging; refusing publication")
    value = json.dumps(pointer, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(value.encode("utf-8")) > 65536:
        raise SystemExit("Item release pointer exceeds the 64 KiB bound")
    body = json.dumps({"key": KEY, "value": value}, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT + "/api/update-kv",
        data=body,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except Exception as error:
        print("Pointer write response was inconclusive; checking readback without replay: " + type(error).__name__, file=sys.stderr)
    verify_pointer_after_write(pointer)
    print(f"ITEM RELEASE POINTER OK commit={commit} release_id={pointer['release_id']} files_checked={len(artifacts)}")


if __name__ == "__main__":
    main()
