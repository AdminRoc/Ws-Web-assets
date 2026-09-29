#!/usr/bin/env python3
"""Decide whether an ITEM_KV value needs a write, failing closed on read errors."""

import argparse
from pathlib import Path


def should_publish(status_code, current_value, expected_value):
    status = str(status_code)
    if status == "404":
        return True
    if status != "200":
        raise RuntimeError(f"ITEM_KV preflight failed with HTTP {status}")
    return current_value != expected_value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("status_code")
    parser.add_argument("current_path")
    parser.add_argument("expected_path")
    args = parser.parse_args()

    current = Path(args.current_path).read_bytes()
    expected = Path(args.expected_path).read_bytes()
    print("publish" if should_publish(args.status_code, current, expected) else "skip")


if __name__ == "__main__":
    main()
