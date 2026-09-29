import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_main_site_item_release as verifier


def wm_payload(count=1500):
    items = [{"id": f"id-{n}", "slug": f"slug-{n}"} for n in range(count)]
    return json.dumps({"count": count, "items": items}).encode("utf-8")


def drops_payload(count=2000):
    items = {f"item-{n}": [] for n in range(count)}
    return json.dumps({"count": count, "items": items}).encode("utf-8")


class MainSiteItemReleaseTests(unittest.TestCase):
    def test_valid_source_artifacts_pass_structure_checks(self):
        verifier.validate_payload("wm-items.json", wm_payload())
        verifier.validate_payload("drops-index.json", drops_payload())

    def test_duplicate_stable_ids_are_rejected(self):
        payload = json.dumps({
            "count": 1500,
            "items": [{"id": f"id-{n}", "slug": f"slug-{n}"} for n in range(1499)]
            + [{"id": "id-0", "slug": "slug-last"}],
        }).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate stable IDs"):
            verifier.validate_payload("wm-items.json", payload)

    def test_readback_requires_exact_hash_and_byte_count(self):
        payload = wm_payload()
        expected = {"wm-items.json": (hashlib.sha256(payload).hexdigest(), len(payload))}
        with patch.object(verifier, "fetch", return_value=(200, payload, {}, "")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verifier.check_once(expected), [])

        wrong_expected = {"wm-items.json": ("0" * 64, len(payload))}
        with patch.object(verifier, "fetch", return_value=(200, payload, {}, "")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verifier.check_once(wrong_expected), ["wm-items.json"])

    def test_dispatch_values_are_validated(self):
        args = SimpleNamespace(
            source_sha="a" * 40,
            wm_sha256="b" * 64,
            wm_bytes=100,
            drops_sha256="c" * 64,
            drops_bytes=200,
        )
        self.assertEqual(len(verifier.parse_expected(args)), 2)
        args.wm_sha256 = "invalid"
        with self.assertRaisesRegex(ValueError, "SHA-256 is malformed"):
            verifier.parse_expected(args)


if __name__ == "__main__":
    unittest.main()
