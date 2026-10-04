import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "scripts"))
from runtime_schedule_guard import (
    RUN_TITLE_PREFIX,
    recent_target_runs,
    resolve_target,
    should_run_capture,
)


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def tagged_run(target, started_at, conclusion="success"):
    return {
        "display_title": f"{RUN_TITLE_PREFIX} [{target}]",
        "run_started_at": started_at.isoformat().replace("+00:00", "Z"),
        "conclusion": conclusion,
        "status": "completed",
    }


class RuntimeScheduleGuardTests(unittest.TestCase):
    def test_schedule_and_manual_target_resolution(self):
        self.assertEqual(resolve_target("schedule", "17 4 * * *", ""), "translations")
        self.assertEqual(resolve_target("schedule", "17 6 * * *", ""), "rotation")
        self.assertEqual(resolve_target("workflow_dispatch", "", "all"), "all")
        self.assertEqual(resolve_target("workflow_run", "", ""), "translations")

    def test_unknown_schedule_or_target_fails_closed(self):
        with self.assertRaises(ValueError):
            resolve_target("schedule", "0 * * * *", "")
        with self.assertRaises(ValueError):
            resolve_target("schedule", "7 */2 * * *", "")
        with self.assertRaises(ValueError):
            resolve_target("workflow_dispatch", "", "unknown")
        with self.assertRaises(ValueError):
            resolve_target("workflow_dispatch", "", "baseline")

    def test_recent_success_of_same_target_skips_but_other_target_does_not(self):
        recent_translation = tagged_run("translations", NOW - timedelta(minutes=2))
        run, _ = should_run_capture("schedule", "false", "translations", [recent_translation], NOW)
        self.assertFalse(run)
        run, _ = should_run_capture("schedule", "false", "rotation", [recent_translation], NOW)
        self.assertTrue(run)

    def test_daily_family_deduplicates_by_utc_date_not_rolling_23_hours(self):
        same_day = tagged_run("rotation", NOW - timedelta(hours=2))
        previous_day_late = tagged_run("rotation", NOW - timedelta(hours=22, minutes=59))
        self.assertFalse(should_run_capture("schedule", "false", "rotation", [same_day], NOW)[0])
        self.assertTrue(should_run_capture("schedule", "false", "rotation", [previous_day_late], NOW)[0])

    def test_recent_all_family_success_counts_for_each_daily_target(self):
        all_family = tagged_run("all", NOW - timedelta(minutes=5))
        self.assertFalse(
            should_run_capture("schedule", "false", "translations", [all_family], NOW)[0]
        )

    def test_failed_target_run_does_not_hide_behind_an_older_success(self):
        failed = tagged_run("rotation", NOW - timedelta(minutes=5), "failure")
        older_success = tagged_run("rotation", NOW - timedelta(minutes=10), "success")
        run, _ = should_run_capture("schedule", "false", "rotation", [failed, older_success], NOW)
        self.assertTrue(run)

    def test_recent_in_progress_target_run_suppresses_duplicate_dispatch(self):
        active = tagged_run("translations", NOW - timedelta(minutes=15), conclusion=None)
        active["status"] = "in_progress"
        run, reason = should_run_capture("workflow_dispatch", "true", "translations", [active], NOW)
        self.assertFalse(run)
        self.assertIn("still in progress", reason)

    def test_previous_day_in_progress_daily_run_does_not_hold_next_daily_cycle(self):
        active = tagged_run("translations", NOW - timedelta(hours=17), conclusion=None)
        active["status"] = "in_progress"
        self.assertTrue(
            should_run_capture("workflow_dispatch", "true", "translations", [active], NOW)[0]
        )

    def test_current_run_is_excluded_from_in_progress_duplicate_detection(self):
        current = tagged_run("translations", NOW - timedelta(seconds=10), conclusion=None)
        current.update({"id": 1234, "status": "in_progress"})
        self.assertTrue(
            should_run_capture(
                "workflow_dispatch", "true", "translations", [current], NOW, "1234"
            )[0]
        )

    def test_legacy_untagged_runs_do_not_mask_first_recovery(self):
        old_generic = {"display_title": RUN_TITLE_PREFIX, "conclusion": "success"}
        run, _ = should_run_capture("workflow_dispatch", "true", "translations", [old_generic], NOW)
        self.assertTrue(run)

    def test_manual_and_workflow_run_events_bypass_schedule_lookup(self):
        self.assertTrue(should_run_capture("workflow_dispatch", "false", "translations", None, NOW)[0])
        self.assertTrue(should_run_capture("workflow_run", "false", "translations", None, NOW)[0])

    @patch("runtime_schedule_guard.api_json")
    def test_queries_current_workflow_run_names(self, api_json):
        api_json.return_value = {"workflow_runs": []}
        result = recent_target_runs(
            "AdminRoc/Ws-Web-assets", "https://api.github.com", "dummy", "publish-runtime-data.yml"
        )
        self.assertEqual(result, [])
        self.assertEqual(
            api_json.call_args.args[0],
            "https://api.github.com/repos/AdminRoc/Ws-Web-assets/actions/workflows/publish-runtime-data.yml/runs?per_page=100",
        )


if __name__ == "__main__":
    unittest.main()
