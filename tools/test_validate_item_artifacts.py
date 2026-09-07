import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate_item_artifacts.py")
SPEC = importlib.util.spec_from_file_location("validate_item_artifacts", SCRIPT)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class ReleaseMetadataContractTest(unittest.TestCase):
    def test_release_metadata_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            assets = root / "assets"
            (source / "data/item").mkdir(parents=True)
            (assets / "data/item").mkdir(parents=True)
            content = '{"value":true}\n'
            (source / "data/item/example.json").write_text(content, encoding="utf-8")
            (assets / "data/item/example.json").write_text(content, encoding="utf-8")
            (assets / "item-artifact-contract.json").write_text(json.dumps({
                "kv_value_limit_bytes": 1048576,
                "source_repository": "Ws-Web",
                "asset_repository": "Ws-Web-assets",
                "artifacts": [{
                    "id": "example",
                    "source_path": "data/item/example.json",
                    "asset_path": "data/item/example.json",
                    "delivery": "kv-and-assets",
                }],
            }), encoding="utf-8")
            (assets / "data/item/item-release.json").write_text(json.dumps({
                "artifacts": {"example": {"sha256": "stale", "bytes": 0}},
            }), encoding="utf-8")

            result = subprocess.run([
                sys.executable, str(SCRIPT), "--source-root", str(source), "--assets-root", str(assets),
            ], text=True, capture_output=True, check=False)

            self.assertEqual(result.returncode, 1)
            self.assertIn("example: release metadata differs from assets mirror", result.stdout)

    def test_release_metadata_uses_lf_published_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.json"
            path.write_bytes(b'{\r\n  "value": true\r\n}\r\n')
            self.assertEqual(VALIDATOR.release_bytes(path), b'{\n  "value": true\n}\n')


if __name__ == "__main__":
    unittest.main()
