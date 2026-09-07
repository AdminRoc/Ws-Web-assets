import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WRITERS = [
    "build-arb-baseline.yml", "build-wm-data.yml", "cache-item-icons.yml",
    "gen-i18n.yml", "gen-item-names-zh.yml", "gen-shared-translations.yml",
    "harvest-auction-dicts.yml", "harvest-calamity-i18n.yml",
    "harvest-drop-table-i18n.yml", "harvest-item-i18n.yml", "harvest-pinyin.yml",
    "harvest-wiki-icons.yml", "harvest-wm-items-i18n.yml", "tenet-coda-rotation.yml",
]
CORE_SHA = "17f4edb881ae478d93bf978824a1c0608bf8ba1b"


class CrossRepositoryWorkflowGateTest(unittest.TestCase):
    def test_all_private_ws_web_writers_use_the_same_stale_producer_gate(self):
        for name in WRITERS:
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertIn(f"ref: {CORE_SHA}", text, name)
            self.assertIn("retry_attempt:", text, name)
            self.assertIn("actions: write", text, name)
            self.assertIn("verify_ws_web_target_revision.py", text, name)
            private_commit = text.split("- name: 同步产物到 assets 镜像", 1)[0]
            self.assertNotIn("git pull --rebase --autostash origin main || true", private_commit, name)

    def test_item_kv_reader_is_not_a_private_ws_web_writer(self):
        text = (WORKFLOWS / "sync-item-kv.yml").read_text(encoding="utf-8")
        self.assertIn("path: _source", text)
        self.assertNotIn(CORE_SHA, text)
        self.assertNotIn("retry_attempt:", text)


if __name__ == "__main__":
    unittest.main()
