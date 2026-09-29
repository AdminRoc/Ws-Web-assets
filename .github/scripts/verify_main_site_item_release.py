#!/usr/bin/env python3
"""Verify that Maker-served main-site item artifacts match one committed release."""

import argparse
import hashlib
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PUBLIC_BASE = "https://wfspeed.run/data/item/"
ARTIFACTS = ("wm-items.json", "drops-index.json")


def validate_payload(name, payload):
    document = json.loads(payload.decode("utf-8"))
    items = document.get("items") if isinstance(document, dict) else None
    if name == "wm-items.json":
        if not isinstance(items, list) or document.get("count") != len(items) or len(items) < 1500:
            raise ValueError("public item manifest is incomplete")
        ids = [str(item.get("id") or "") for item in items if isinstance(item, dict)]
        slugs = [str(item.get("slug") or "") for item in items if isinstance(item, dict)]
        if len(ids) != len(items) or any(not item_id for item_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("public item manifest has missing or duplicate stable IDs")
        if any(not slug for slug in slugs) or len(set(slugs)) != len(slugs):
            raise ValueError("public item manifest has missing or duplicate slugs")
    elif name == "drops-index.json":
        if not isinstance(items, dict) or document.get("count") != len(items) or len(items) < 2000:
            raise ValueError("public official drop index is incomplete")


def fetch(url):
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "wfspeed-item-release-verifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read(), response.headers, ""
    except HTTPError as error:
        return error.code, error.read(), error.headers, "HTTP error"
    except URLError as error:
        return 0, b"", {}, str(error.reason)


def check_once(expected):
    mismatches = []
    for name, (expected_hash, expected_bytes) in expected.items():
        status, payload, headers, error = fetch(PUBLIC_BASE + name)
        actual_hash = hashlib.sha256(payload).hexdigest() if payload else "-"
        matched = status == 200 and actual_hash == expected_hash and len(payload) == expected_bytes
        if matched:
            try:
                validate_payload(name, payload)
            except (UnicodeError, ValueError, json.JSONDecodeError) as validation_error:
                matched = False
                error = "invalid JSON artifact: " + str(validation_error)
        cache = headers.get("EO-Cache-Status", "-") if headers else "-"
        age = headers.get("Age", "-") if headers else "-"
        modified = headers.get("Last-Modified", "-") if headers else "-"
        print(
            "%s http=%s match=%s bytes=%s/%s sha256=%s/%s edge_cache=%s age=%s last_modified=%s%s"
            % (
                name,
                status,
                str(matched).lower(),
                len(payload),
                expected_bytes,
                actual_hash[:12],
                expected_hash[:12],
                cache,
                age,
                modified,
                (" error=" + error) if error else "",
            ),
            flush=True,
        )
        if not matched:
            mismatches.append(name)
    return mismatches


def parse_expected(args):
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha, re.I):
        raise ValueError("source SHA must be a full 40-character commit hash")
    expected = {}
    for name, digest, size in (
        ("wm-items.json", args.wm_sha256, args.wm_bytes),
        ("drops-index.json", args.drops_sha256, args.drops_bytes),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", digest, re.I):
            raise ValueError("artifact SHA-256 is malformed")
        if size < 1:
            raise ValueError("artifact byte length must be positive")
        expected[name] = (digest.lower(), size)
    return expected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--wm-sha256", required=True)
    parser.add_argument("--wm-bytes", required=True, type=int)
    parser.add_argument("--drops-sha256", required=True)
    parser.add_argument("--drops-bytes", required=True, type=int)
    parser.add_argument("--initial-delay", type=int, default=1860)
    parser.add_argument("--max-wait", type=int, default=600)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.initial_delay < 0 or args.max_wait < 0 or args.interval < 1:
        raise SystemExit("delay/wait must be non-negative and interval must be positive")
    try:
        expected = parse_expected(args)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    print("Verifying main-site artifacts for Ws-Web source " + args.source_sha[:12], flush=True)
    print(
        "Expected SHA-256 prefixes: "
        + ", ".join("%s=%s" % (name, value[0][:12]) for name, value in expected.items()),
        flush=True,
    )
    if args.initial_delay:
        print("Waiting %d seconds for Maker deployment and the configured cache TTL." % args.initial_delay, flush=True)
        time.sleep(args.initial_delay)

    deadline = time.monotonic() + args.max_wait
    attempt = 0
    while True:
        attempt += 1
        print("Public item artifact readback attempt %d" % attempt, flush=True)
        if not check_once(expected):
            print("Main-site public item artifacts match the committed Ws-Web source.", flush=True)
            return 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit("Main-site public item artifacts did not converge to the committed Ws-Web source.")
        time.sleep(min(args.interval, remaining))


if __name__ == "__main__":
    raise SystemExit(main())
