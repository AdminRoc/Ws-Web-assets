import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = REPO_ROOT / "tools" / "sync_item_artifacts.py"
VALIDATE_SCRIPT = REPO_ROOT / "tools" / "validate_item_artifacts.py"


class SyncItemArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "Ws-Web"
        self.assets = self.root / "Ws-Web-assets"
        (self.source / "data" / "item").mkdir(parents=True)
        (self.assets / "data" / "item").mkdir(parents=True)
        self.contract = {
            "source_repository": "Ws-Web",
            "asset_repository": "Ws-Web-assets",
            "kv_value_limit_bytes": 1048576,
            "artifacts": [
                {
                    "id": "sample",
                    "source_path": "data/item/sample.json",
                    "asset_path": "data/item/sample.json",
                    "delivery": "assets-only",
                }
            ],
        }
        (self.assets / "item-artifact-contract.json").write_text(
            json.dumps(self.contract), encoding="utf-8"
        )
        self.source_file = self.source / "data" / "item" / "sample.json"
        self.asset_file = self.assets / "data" / "item" / "sample.json"
        self.release_file = self.assets / "data" / "item" / "item-release.json"

    def tearDown(self):
        self.temp.cleanup()

    def run_sync(self, dry_run=False):
        command = [
            sys.executable,
            str(SYNC_SCRIPT),
            "--source-root",
            str(self.source),
            "--assets-root",
            str(self.assets),
        ]
        if dry_run:
            command.append("--dry-run")
        return subprocess.run(command, check=True, capture_output=True, text=True)

    @staticmethod
    def release_digest(payload):
        return hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()

    def write_matching_release(self, payload):
        canonical = payload.replace(b"\r\n", b"\n")
        release = {
            "schema_version": 1,
            "source_repository": "Ws-Web",
            "assets_release_path": "data/item/item-release.json",
            "artifacts": {
                "sample": {
                    "path": "data/item/sample.json",
                    "sha256": hashlib.sha256(canonical).hexdigest(),
                    "bytes": len(canonical),
                    "delivery": "assets-only",
                    "kv_key": None,
                }
            },
        }
        identity = {
            "schema_version": release["schema_version"],
            "source_repository": release["source_repository"],
            "assets_release_path": release["assets_release_path"],
            "artifacts": release["artifacts"],
        }
        fingerprint = json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        release["release_id"] = hashlib.sha256(fingerprint).hexdigest()[:40]
        self.release_file.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")

    def test_windows_newlines_do_not_create_false_dry_run_diff(self):
        payload = b'{\r\n  "items": [1]\r\n}\r\n'
        self.source_file.write_bytes(payload)
        self.asset_file.write_bytes(payload)
        self.write_matching_release(payload)

        result = self.run_sync(dry_run=True)

        self.assertEqual(json.loads(result.stdout)["changed"], [])

    def test_sync_writes_canonical_bytes_and_validator_accepts_them(self):
        source_payload = b'{\r\n  "items": [1, 2]\r\n}\r\n'
        self.source_file.write_bytes(source_payload)
        self.asset_file.write_bytes(b'{"items": [0]}\n')

        self.run_sync()

        canonical = source_payload.replace(b"\r\n", b"\n")
        self.assertEqual(self.asset_file.read_bytes(), canonical)
        release = json.loads(self.release_file.read_text(encoding="utf-8"))
        self.assertEqual(release["artifacts"]["sample"]["sha256"], self.release_digest(source_payload))
        self.assertEqual(release["artifacts"]["sample"]["bytes"], len(canonical))
        self.assertRegex(release["release_id"], r"^[0-9a-f]{40}$")
        self.assertNotIn("source_commit_at", release)
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATE_SCRIPT),
                "--source-root",
                str(self.source),
                "--assets-root",
                str(self.assets),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["artifacts"][0]["asset_matches_source"])

    def test_unrelated_source_file_does_not_create_a_new_artifact_release(self):
        payload = b'{"items": [1, 2]}\n'
        self.source_file.write_bytes(payload)
        self.asset_file.write_bytes(payload)
        self.run_sync()
        release_id = json.loads(self.release_file.read_text(encoding="utf-8"))["release_id"]

        (self.source / "README.md").write_text("Workflow-only source change\n", encoding="utf-8")
        result = self.run_sync(dry_run=True)

        self.assertEqual(json.loads(result.stdout)["changed"], [])
        self.assertEqual(
            json.loads(self.release_file.read_text(encoding="utf-8"))["release_id"],
            release_id,
        )


if __name__ == "__main__":
    unittest.main()
