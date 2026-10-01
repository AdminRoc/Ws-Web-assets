import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "scripts"))
from workflow_freshness_guard import (
    latest_producer_success,
    select_latest_producer_success,
    should_run_capture,
)


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class WorkflowFreshnessGuardTests(unittest.TestCase):
    def test_manual_dispatch_bypasses_gate(self):
        run, _ = should_run_capture(
            "workflow_dispatch", "false", {"conclusion": "success", "updated_at": "2026-10-01T11:59:00Z"},
            NOW, timedelta(minutes=50)
        )
        self.assertTrue(run)

    def test_unflagged_manual_dispatch_is_not_treated_as_fallback(self):
        run, _ = should_run_capture("workflow_dispatch", "", None, NOW, timedelta(minutes=50))
        self.assertTrue(run)

    def test_flagged_cloudflare_dispatch_uses_freshness_gate(self):
        recent = {"conclusion": "success", "updated_at": "2026-10-01T11:30:00Z"}
        run, reason = should_run_capture(
            "workflow_dispatch", "true", recent, NOW, timedelta(minutes=50)
        )
        self.assertFalse(run)
        self.assertIn("30 minutes old", reason)

    def test_schedule_event_uses_same_gate(self):
        recent = {"conclusion": "success", "updated_at": "2026-10-01T11:30:00Z"}
        run, _ = should_run_capture("schedule", "false", recent, NOW, timedelta(minutes=50))
        self.assertFalse(run)

    def test_exact_threshold_allows_recovery(self):
        old = {"conclusion": "success", "updated_at": "2026-10-01T11:10:00Z"}
        run, _ = should_run_capture("workflow_dispatch", "true", old, NOW, timedelta(minutes=50))
        self.assertTrue(run)

    def test_failed_or_missing_success_allows_retry(self):
        for latest in (None, {"conclusion": "failure"}):
            run, _ = should_run_capture("schedule", "false", latest, NOW, timedelta(minutes=50))
            self.assertTrue(run)

    def test_invalid_or_future_success_timestamp_fails_closed(self):
        for latest in (
            {"conclusion": "success", "updated_at": "bad"},
            {"conclusion": "success", "updated_at": "2026-10-01T12:10:00Z"},
        ):
            with self.subTest(latest=latest), self.assertRaises(ValueError):
                should_run_capture("schedule", "false", latest, NOW, timedelta(minutes=50))

    def test_freshness_skip_does_not_count_as_producer_success(self):
        skipped = {"id": 2, "conclusion": "success", "updated_at": "2026-10-01T11:55:00Z"}
        completed = {"id": 1, "conclusion": "success", "updated_at": "2026-10-01T11:00:00Z"}
        jobs = {
            2: [{"name": "build", "conclusion": "skipped"}],
            1: [{"name": "build", "conclusion": "success"}],
        }
        result = select_latest_producer_success([skipped, completed], lambda run: jobs[run["id"]], "build")
        self.assertEqual(result, completed)

    def test_cancelled_before_job_creation_does_not_hide_last_producer_success(self):
        cancelled_before_start = {"id": 3, "conclusion": "cancelled"}
        completed = {"id": 2, "conclusion": "success", "updated_at": "2026-10-01T10:00:00Z"}
        jobs = {3: [], 2: [{"name": "build", "conclusion": "success"}]}
        result = select_latest_producer_success(
            [cancelled_before_start, completed], lambda run: jobs[run["id"]], "build"
        )
        self.assertEqual(result, completed)

    def test_cancelled_after_producer_job_started_requires_recovery(self):
        cancelled_during_producer = {"id": 3, "conclusion": "cancelled"}
        completed = {"id": 2, "conclusion": "success", "updated_at": "2026-10-01T10:00:00Z"}
        jobs = {
            3: [{"name": "build", "conclusion": "cancelled"}],
            2: [{"name": "build", "conclusion": "success"}],
        }
        result = select_latest_producer_success(
            [cancelled_during_producer, completed], lambda run: jobs[run["id"]], "build"
        )
        self.assertIsNone(result)

    def test_latest_failed_producer_allows_retry_instead_of_hiding_behind_old_success(self):
        failed = {"id": 2, "conclusion": "failure"}
        older = {"id": 1, "conclusion": "success"}
        jobs = {
            2: [{"name": "harvest", "conclusion": "failure"}],
            1: [{"name": "harvest", "conclusion": "success"}],
        }
        self.assertIsNone(
            select_latest_producer_success([failed, older], lambda run: jobs[run["id"]], "harvest")
        )

    @patch("workflow_freshness_guard.api_json")
    def test_queries_workflow_runs_and_producer_job(self, api_json):
        run = {"id": 123, "conclusion": "success", "updated_at": "2026-10-01T11:00:00Z"}
        api_json.side_effect = [
            {"workflow_runs": [run]},
            {"jobs": [{"name": "publish", "conclusion": "success"}]},
        ]
        found = latest_producer_success(
            "AdminRoc/Ws-Web-assets", "https://api.github.com", "dummy", "sync-item-kv.yml", "publish"
        )
        self.assertEqual(found, run)
        self.assertEqual(
            api_json.call_args_list[1].args[0],
            "https://api.github.com/repos/AdminRoc/Ws-Web-assets/actions/runs/123/jobs?per_page=100",
        )


if __name__ == "__main__":
    unittest.main()
