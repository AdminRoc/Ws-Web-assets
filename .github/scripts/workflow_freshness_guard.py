"""Fail-closed freshness gate for explicitly marked Cloudflare fallbacks."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def is_periodic_event(event_name: str, fallback_input: str) -> bool:
    return event_name == "schedule" or fallback_input.strip().lower() == "true"


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def should_run_capture(
    event_name: str,
    fallback_input: str,
    latest_run: dict | None,
    now: datetime,
    min_age: timedelta,
) -> tuple[bool, str]:
    if not is_periodic_event(event_name, fallback_input):
        return True, "manual workflow_dispatch bypasses the periodic freshness gate"
    if latest_run is None:
        return True, "no completed producer success found; allow recovery"
    if latest_run.get("conclusion") != "success":
        return True, "latest producer run did not complete successfully; allow recovery"

    completed_at = latest_run.get("updated_at") or latest_run.get("completed_at")
    if not completed_at:
        raise ValueError("latest successful producer run has no completion timestamp")
    age = now.astimezone(timezone.utc) - parse_utc(completed_at)
    if age < -timedelta(minutes=5):
        raise ValueError("latest successful producer run is unexpectedly in the future")
    if age < min_age:
        age_minutes = max(0, int(age.total_seconds() // 60))
        return False, f"last completed producer success is only {age_minutes} minutes old"
    return True, f"last completed producer success is at least {int(min_age.total_seconds() // 60)} minutes old"


def api_json(url: str, token: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Ws-Web-assets-workflow-freshness-guard",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def select_latest_producer_success(
    runs: list[dict], jobs_for_run, producer_job: str
) -> dict | None:
    for run in runs:
        run_id = run.get("id")
        if not isinstance(run_id, int):
            raise ValueError("completed workflow run has no valid ID")
        jobs = jobs_for_run(run)
        if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
            raise ValueError("GitHub Actions API returned an invalid job list")
        job = next((item for item in jobs if item.get("name") == producer_job), None)
        if job is None:
            if run.get("conclusion") == "cancelled":
                # GitHub can cancel a queued run before creating any jobs. It
                # cannot have changed producer data, so keep looking for the
                # latest run that actually executed the producer job.
                continue
            raise ValueError(f"completed workflow run is missing producer job {producer_job!r}")
        conclusion = job.get("conclusion")
        if run.get("conclusion") == "success" and conclusion == "success":
            return run
        if conclusion in {"failure", "cancelled", "timed_out", "action_required"}:
            # A failed/cancelled producer must be retried; older success cannot hide it.
            return None
        # A successful freshness-gate run with the producer job skipped is not fresh data.
    return None


def latest_producer_success(
    repository: str, api_url: str, token: str, workflow_file: str, producer_job: str
) -> dict | None:
    base = f"{api_url.rstrip('/')}/repos/{repository}/actions"
    document = api_json(
        f"{base}/workflows/{workflow_file}/runs?status=completed&per_page=30", token
    )
    runs = document.get("workflow_runs") if isinstance(document, dict) else None
    if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
        raise ValueError("GitHub Actions API returned an invalid workflow-run list")

    def jobs_for_run(run: dict) -> list[dict]:
        response = api_json(f"{base}/runs/{run['id']}/jobs?per_page=100", token)
        jobs = response.get("jobs") if isinstance(response, dict) else None
        if not isinstance(jobs, list):
            raise ValueError("GitHub Actions API returned an invalid job list")
        return jobs

    return select_latest_producer_success(runs, jobs_for_run, producer_job)


def write_output(run_capture: bool) -> int:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print("::error::GITHUB_OUTPUT is not set")
        return 1
    with open(output_path, "a", encoding="utf-8") as output:
        output.write(f"run_capture={str(run_capture).lower()}\n")
    return 0


def main() -> int:
    event_name = os.environ.get("EVENT_NAME", "")
    fallback_input = os.environ.get("CF_SCHEDULE_FALLBACK", "false")
    if not is_periodic_event(event_name, fallback_input):
        print(f"run_capture=true ({event_name or 'unknown'} manual run bypasses freshness gate)")
        return write_output(True)

    token = os.environ.get("GH_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    workflow_file = os.environ.get("WORKFLOW_FILE", "")
    producer_job = os.environ.get("PRODUCER_JOB", "")
    try:
        min_age = timedelta(minutes=int(os.environ.get("MIN_AGE_MINUTES", "0")))
        if min_age <= timedelta(0):
            raise ValueError("MIN_AGE_MINUTES must be positive")
        if not token or not repository or not workflow_file or not producer_job:
            raise ValueError("GitHub Actions API configuration is incomplete")
        latest = latest_producer_success(
            repository, api_url, token, workflow_file, producer_job
        )
        run_capture, reason = should_run_capture(
            event_name, fallback_input, latest, datetime.now(timezone.utc), min_age
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
        # Never start a producer when recency cannot be established.
        print(f"::error::Could not verify the last producer success ({type(error).__name__})")
        return 1

    print(f"run_capture={str(run_capture).lower()} ({reason})")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not run_capture and summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(f"### Periodic producer run skipped\n\n{reason}.\n")
    return write_output(run_capture)


if __name__ == "__main__":
    sys.exit(main())
