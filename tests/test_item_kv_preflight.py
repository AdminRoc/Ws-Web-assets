import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from item_kv_preflight import should_publish  # noqa: E402


class ItemKvPreflightTests(unittest.TestCase):
    def test_matching_value_skips_put(self):
        self.assertFalse(should_publish(200, b'{"items":[]}', b'{"items":[]}'))

    def test_different_value_needs_put(self):
        self.assertTrue(should_publish(200, b'{"items":[]}', b'{"items":[1]}'))

    def test_missing_key_needs_put(self):
        self.assertTrue(should_publish(404, b"not found", b'{"items":[]}'))

    def test_provider_errors_fail_before_put(self):
        for status in ("000", 500, 502, 503):
            with self.subTest(status=status):
                with self.assertRaisesRegex(RuntimeError, "preflight failed"):
                    should_publish(status, b"", b'{"items":[1]}')


if __name__ == "__main__":
    unittest.main()
