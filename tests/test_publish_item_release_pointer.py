import importlib.util
import pathlib
import socket
import unittest
import urllib.error
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "item_release_pointer", ROOT / ".github/scripts/publish_item_release_pointer.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Response:
    def __init__(self, body=b"ok"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class ItemPointerTests(unittest.TestCase):
    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_get_retries_transient_timeout(self, urlopen, sleep):
        urlopen.side_effect = [socket.timeout("temporary"), Response()]
        self.assertEqual(MODULE.get("https://example.test", attempts=2, delay=0), b"ok")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0)

    def test_identity_ignores_generation_only(self):
        base = {
            "schema_version": 1,
            "source_repository": "Ws-Web",
            "assets_release_path": "data/item/item-release.json",
            "assets_revision": "a" * 40,
            "release_id": "release",
            "artifacts": {"one": {"path": "one.json", "sha256": "b" * 64, "bytes": 1}},
        }
        newer = dict(base, generation="new", assets_revision="a" * 40)
        older = dict(base, generation="old", assets_revision="b" * 40)
        self.assertEqual(MODULE.immutable_identity(newer), MODULE.immutable_identity(older))

    @mock.patch.object(MODULE.time, "sleep")
    def test_readback_accepts_same_immutable_release(self, _sleep):
        expected = {"release_id": "same", "generation": "new"}
        actual = {"release_id": "same", "generation": "old"}
        with mock.patch.object(MODULE, "current_pointer", return_value=actual):
            MODULE.verify_pointer_after_write(expected, attempts=1, delay=0)

    @mock.patch.object(MODULE.time, "sleep")
    def test_readback_waits_for_exact_expected_value(self, _sleep):
        expected = {"release_id": "new", "generation": "2"}
        with mock.patch.object(MODULE, "current_pointer", side_effect=[None, expected]):
            MODULE.verify_pointer_after_write(expected, attempts=2, delay=0)

    @mock.patch.object(MODULE.time, "sleep")
    def test_readback_rejects_persistent_old_release(self, _sleep):
        expected = {"release_id": "new", "generation": "2"}
        old = {"release_id": "old", "generation": "1"}
        with mock.patch.object(MODULE, "current_pointer", return_value=old):
            with self.assertRaises(SystemExit):
                MODULE.verify_pointer_after_write(expected, attempts=2, delay=0)

    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_get_does_not_retry_not_found(self, urlopen, _sleep):
        urlopen.side_effect = urllib.error.HTTPError("https://example.test", 404, "missing", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            MODULE.get("https://example.test", attempts=4, delay=0)
        urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
