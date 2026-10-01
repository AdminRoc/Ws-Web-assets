"""Target-aware gate for the Core hourly fallback and GitHub cron backups."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHEDULE_TARGETS = {
    "7 */2 * * *": "baseline",
    "17 4 * * *": "translations",
    "17 6 * * *": "rotation",
}
TARGETS = {"baseline", "translations", "rotation"}
MIN_AGE_MINUTES = {"baseline": 110}
RUN_TITLE_PREFIX = "Publish non-item runtime data"


def resolve_target(event_name: str, schedule: str, requested_target: str) -> str:
    if event_name == "schedule":
        target = SCHEDULE_TARGETS.get(schedule)
        if target is None:
            raise ValueError("unknown runtime-data schedule")
        return target
    if event_name == "workflow_run":
        return "translations"
    if event_name == "workflow_dispatch":
        target = requested_target or "all"
        if target not in {"all", *TARGETS}:
            raise ValueError("invalid runtime-data target")
        return target
    raise ValueError("unsupported runtime-data event")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("run timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def should_run_capture(
    event_name: str,
    fallback_input: str,
    target: str,
    runs: list[dict] | None,
    now: datetime,
    current_run_id: str = "",
) -> tuple[bool, str]:
    periodic = event_name == "schedule" or fallback_input.strip().lower() == "true"
    if not periodic:
        return True, "manual or workflow-run publication bypasses the schedule freshness gate"
    if target == "all":
        raise ValueError("periodic runtime-data runs must select one family")
    if runs is None or any(not isinstance(run, dict) for run in runs):
        raise ValueError("workflow-run list is invalid")

    titles = {f"{RUN_TITLE_PREFIX} [{target}]", f"{RUN_TITLE_PREFIX} [all]"}
    target_runs = [
        run for run in runs
        if run.get("display_title") in titles
        and (not current_run_id or str(run.get("id", "")) != current_run_id)
    ]
    if not target_runs:
        return True, "no tagged producer run found; allow recovery"

    def run_time(run: dict) -> datetime:
        value = run.get("run_started_at") or run.get("created_at")
        if not value:
            raise ValueError("tagged workflow run has no start time")
        return parse_utc(value)

    latest = max(target_runs, key=run_time)
    conclusion = latest.get("conclusion")
    status = latest.get("status")
    now_utc = now.astimezone(timezone.utc)
    latest_time = run_time(latest)
    age = now_utc - latest_time
    if age < -timedelta(minutes=5):
        raise ValueError("latest tagged producer run is unexpectedly in the future")

    if target in {"translations", "rotation"}:
        if status == "in_progress":
            if latest_time.date() == now_utc.date() or age < timedelta(hours=2):
                age_minutes = max(0, int(age.total_seconds() // 60))
                return False, f"latest {target} producer run is still in progress ({age_minutes} minutes old)"
            return True, "daily producer run is stale and can be recovered"
        if conclusion != "success":
            return True, "latest tagged producer did not succeed; allow recovery"
        if latest_time.date() == now_utc.date():
            return False, f"latest {target} producer already succeeded on this UTC date"
        return True, f"no successful {target} producer run exists on this UTC date"

    min_age = timedelta(minutes=MIN_AGE_MINUTES[target])
    if status == "in_progress" and age < min_age:
        age_minutes = max(0, int(age.total_seconds() // 60))
        return False, f"latest {target} producer run is still in progress ({age_minutes} minutes old)"
    if conclusion != "success":
        return True, "latest tagged producer did not succeed; allow recovery"

    if age < min_age:
        age_minutes = max(0, int(age.total_seconds() // 60))
        return False, f"latest {target} producer run is only {age_minutes} minutes old"
    return True, f"latest {target} producer run is at least {MIN_AGE_MINUTES[target]} minutes old"


def api_json(url: str, token: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Ws-Web-assets-runtime-schedule-guard",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def recent_target_runs(repository: str, api_url: str, token: str, workflow_file: str) -> list[dict]:
    url = (
        f"{api_url.rstrip('/')}/repos/{repository}/actions/workflows/"
        f"{workflow_file}/runs?per_page=100"
    )
    document = api_json(url, token)
    runs = document.get("workflow_runs") if isinstance(document, dict) else None
    if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
        raise ValueError("GitHub Actions API returned an invalid workflow-run list")
    return runs


def write_outputs(target: str, run_capture: bool) -> int:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print("::error::GITHUB_OUTPUT is not set")
        return 1
    with open(output_path, "a", encoding="utf-8") as output:
        output.write(f"target={target}\n")
        output.write(f"run_capture={str(run_capture).lower()}\n")
        output.write(
            "item_names_path="
            + (".item-source/data/item/item-names-zh.json" if os.environ.get("EVENT_NAME") == "workflow_run" else "data/item/item-names-zh.json")
            + "\n"
        )
    return 0


def main() -> int:
    event_name = os.environ.get("EVENT_NAME", "")
    schedule = os.environ.get("SCHEDULE", "")
    requested_target = os.environ.get("REQUESTED_TARGET", "")
    fallback_input = os.environ.get("CF_SCHEDULE_FALLBACK", "false")
    try:
        target = resolve_target(event_name, schedule, requested_target)
        periodic = event_name == "schedule" or fallback_input.strip().lower() == "true"
        if periodic:
            token = os.environ.get("GH_TOKEN", "")
            repository = os.environ.get("GITHUB_REPOSITORY", "")
            api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
            workflow_file = os.environ.get("WORKFLOW_FILE", "")
            current_run_id = os.environ.get("CURRENT_RUN_ID", "")
            if not token or not repository or not workflow_file or not current_run_id:
                raise ValueError("GitHub Actions API configuration is incomplete")
            runs = recent_target_runs(repository, api_url, token, workflow_file)
        else:
            runs = None
        run_capture, reason = should_run_capture(
            event_name,
            fallback_input,
            target,
            runs,
            datetime.now(timezone.utc),
            os.environ.get("CURRENT_RUN_ID", ""),
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"::error::Could not verify runtime-data freshness ({type(error).__name__})")
        return 1

    print(f"target={target}; run_capture={str(run_capture).lower()} ({reason})")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not run_capture and summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(f"### Runtime-data schedule skipped ({target})\n\n{reason}.\n")
    return write_outputs(target, run_capture)


if __name__ == "__main__":
    sys.exit(main())
