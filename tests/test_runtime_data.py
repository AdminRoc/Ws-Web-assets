import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import validate_runtime_data as runtime_data  # noqa: E402


class RuntimeDataContractTests(unittest.TestCase):
    def test_groups_are_disjoint_and_only_contain_non_item_outputs(self):
        baseline = set(runtime_data.paths_for("baseline"))
        translations = set(runtime_data.paths_for("translations"))
        rotation = set(runtime_data.paths_for("rotation"))
        self.assertTrue(baseline)
        self.assertTrue(translations)
        self.assertTrue(rotation)
        self.assertFalse(baseline & translations)
        self.assertFalse(baseline & rotation)
        self.assertFalse(translations & rotation)
        self.assertTrue(all(not path.startswith("data/item/") for path in runtime_data.paths_for("all")))
        self.assertEqual(len(runtime_data.paths_for("all")),
                         len(baseline) + len(translations) + len(rotation))

    def test_generated_assignment_parser_rejects_trailing_code(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "generated.js"
            source.write_text("window.WF_TR = {\"A\":\"甲\"};\n", encoding="utf-8")
            self.assertEqual(runtime_data.parse_assignment(source, "window.WF_TR = "), {"A": "甲"})
            source.write_text("window.WF_TR = {\"A\":\"甲\"};evil();\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "trailing JavaScript"):
                runtime_data.parse_assignment(source, "window.WF_TR = ")

    def test_changed_paths_reject_any_non_contract_or_item_write(self):
        with patch.object(runtime_data, "changed_paths", return_value={
                "data/item/wm-items.json", "data/tenet-coda-rotation.json"}):
            with self.assertRaisesRegex(ValueError, "outside the all runtime-data contract"):
                runtime_data.validate_scope("all", "worktree")

    def test_artifacts_match_current_core_and_item_inputs(self):
        core = Path(__file__).resolve().parents[2] / "Ws-Web-core"
        runtime_data.validate_translations(core)
        runtime_data.validate_baseline()
        runtime_data.validate_rotation()

    def test_release_workflow_passes_inputs_to_repeated_validation_gates(self):
        workflow = (runtime_data.ROOT / ".github/workflows/publish-runtime-data.yml").read_text(encoding="utf-8")
        import yaml
        parsed = yaml.load(workflow, Loader=yaml.BaseLoader)
        target_input = parsed["on"]["workflow_dispatch"]["inputs"]["target"]
        self.assertEqual(target_input["options"], ["all", "baseline", "translations", "rotation"])
        self.assertIn("- cron: '7 */2 * * *'", workflow)
        self.assertIn("runtime_schedule_guard.py", workflow)
        self.assertIn("needs.schedule_guard.outputs.target", workflow)
        self.assertIn("cf_schedule_fallback", workflow)
        guard = (runtime_data.ROOT / ".github/scripts/runtime_schedule_guard.py").read_text(encoding="utf-8")
        self.assertIn('"7 */2 * * *": "baseline"', guard)
        self.assertIn('"17 4 * * *": "translations"', guard)
        self.assertIn('"17 6 * * *": "rotation"', guard)
        self.assertIn(
            'python3 tools/validate_runtime_data.py --target "$TARGET" --core-root .runtime-core '
            '--item-names "$ITEM_NAMES_PATH" --check-staged',
            workflow,
        )
        self.assertIn(
            'python3 tools/validate_runtime_data.py --target "$TARGET" --core-root .runtime-core '
            '--item-names "$ITEM_NAMES_PATH" --verify-public',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
