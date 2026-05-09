from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request


BASE_DIR = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "up_valuation_config.json"


def _run_powershell_script(script_name: str, args: list[str] | None = None) -> int:
    script_path = BASE_DIR / "program" / "powershell" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Missing script: {script_path}")

    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
    ]
    if args:
        command.extend(args)

    result = subprocess.run(command, cwd=BASE_DIR, check=False)
    return result.returncode


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Invalid config JSON: {CONFIG_PATH}") from exc


def _save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def _default_python_path() -> str:
    return sys.executable


def _load_git_remote_url(remote_name: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(BASE_DIR), "remote", "get-url", remote_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to resolve git remote '{remote_name}'.")
    remote_url = (result.stdout or "").strip()
    if not remote_url:
        raise RuntimeError(f"Git remote '{remote_name}' returned an empty URL.")
    return remote_url


def _normalize_repo_slug(repo_slug: str) -> str:
    normalized = repo_slug.strip()
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("https://github.com/"):
        normalized = normalized.removeprefix("https://github.com/")
    elif normalized.startswith("http://github.com/"):
        normalized = normalized.removeprefix("http://github.com/")
    elif normalized.startswith("git@github.com:"):
        normalized = normalized.removeprefix("git@github.com:")
    if normalized.count("/") != 1:
        raise RuntimeError(f"Unsupported GitHub repository slug: {repo_slug}")
    return normalized


def _parse_github_repo(remote_url: str) -> tuple[str, str]:
    normalized = remote_url.strip()
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@github.com:"):
        normalized = normalized.removeprefix("git@github.com:")
    elif normalized.startswith("https://github.com/"):
        normalized = normalized.removeprefix("https://github.com/")
    elif normalized.startswith("http://github.com/"):
        normalized = normalized.removeprefix("http://github.com/")
    parts = normalized.split("/")
    if len(parts) != 2 or not all(parts):
        raise RuntimeError(f"Unsupported GitHub remote URL: {remote_url}")
    return parts[0], parts[1]


def _github_dispatch_workflow(remote_name: str, workflow: str, ref: str, inputs: dict[str, str], repo_slug: str | None = None) -> None:
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Missing GITHUB_TOKEN or GH_TOKEN for GitHub Actions dispatch.")

    if repo_slug:
        owner, repo = _normalize_repo_slug(repo_slug).split("/", 1)
    else:
        remote_url = _load_git_remote_url(remote_name)
        owner, repo = _parse_github_repo(remote_url)
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    payload = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs

    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=30):
            return
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub dispatch failed ({exc.code}): {body}") from exc


def _workflow_dispatch_payload(args: argparse.Namespace) -> tuple[str, str, dict[str, str]]:
    remote_name = args.github_remote or args.remote_name or "origin"
    config = _load_config()
    ref = args.ref or config.get("githubBranch") or "main"
    inputs: dict[str, str] = {}

    for key, value in [
        ("start", args.start),
        ("end", args.end),
        ("years", str(args.years) if args.years is not None else ""),
        ("max_days", str(args.max_days) if args.max_days is not None else ""),
        ("force", "true" if args.force else ""),
        ("stop_on_error", "true" if args.stop_on_error else ""),
    ]:
        if value not in (None, "", False):
            inputs[key] = str(value)

    return remote_name, ref, inputs


def cmd_env_set(args: argparse.Namespace) -> int:
    config = _load_config()

    if args.dart_key is not None:
        config["dartApiKey"] = args.dart_key
        os.environ["DART_API_KEY"] = args.dart_key
    if args.krx_id is not None:
        config["krxId"] = args.krx_id
        os.environ["KRX_ID"] = args.krx_id
    if args.krx_pw is not None:
        config["krxPw"] = args.krx_pw
        os.environ["KRX_PW"] = args.krx_pw
    if args.google_drive_folder_id is not None:
        config["googleDriveFolderId"] = args.google_drive_folder_id
        os.environ["GOOGLE_DRIVE_FOLDER_ID"] = args.google_drive_folder_id
    if args.google_service_account_json is not None:
        config["googleServiceAccountJsonPath"] = args.google_service_account_json
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = args.google_service_account_json
    if args.disable_google_drive_upload:
        config["enableGoogleDriveUpload"] = False
    elif args.enable_google_drive_upload:
        config["enableGoogleDriveUpload"] = True
    if args.github_remote is not None:
        config["githubRemoteName"] = args.github_remote
    if args.github_branch is not None:
        config["githubBranch"] = args.github_branch
    if args.github_commit_prefix is not None:
        config["githubCommitPrefix"] = args.github_commit_prefix
    if args.disable_github_auto_sync:
        config["enableGithubAutoSync"] = False
    elif args.enable_github_auto_sync:
        config["enableGithubAutoSync"] = True

    _save_config(config)
    print(f"[OK] Updated config: {CONFIG_PATH}")
    return 0


def cmd_init_config(args: argparse.Namespace) -> int:
    config = _load_config()
    config["pythonPath"] = args.python_path or _default_python_path()
    config["dailyTime"] = args.daily_time
    config["monthlyTime"] = args.monthly_time
    config["assumptionsMonthlyTime"] = args.assumptions_monthly_time
    config["taskPrefix"] = args.task_prefix
    config.setdefault("enableGoogleDriveUpload", False)
    config.setdefault("googleDriveFolderId", "")
    config.setdefault("googleServiceAccountJsonPath", "")
    config.setdefault("enableGithubAutoSync", False)
    config.setdefault("githubRemoteName", "origin")
    config.setdefault("githubBranch", "main")
    config.setdefault("githubCommitPrefix", "auto: sync generated changes")
    config.setdefault("dartApiKey", os.environ.get("DART_API_KEY", ""))
    config.setdefault("krxId", os.environ.get("KRX_ID", ""))
    config.setdefault("krxPw", os.environ.get("KRX_PW", ""))
    _save_config(config)
    print(f"[OK] Saved config: {CONFIG_PATH}")
    return 0


def cmd_install_automation(args: argparse.Namespace) -> int:
    return _run_powershell_script(
        "install_automation.ps1",
        ["-DailyTime", args.daily_time, "-MonthlyTime", args.monthly_time, "-AssumptionsMonthlyTime", args.assumptions_monthly_time, "-TaskPrefix", args.task_prefix],
    )


def cmd_schedule_install(args: argparse.Namespace) -> int:
    return _run_powershell_script(
        "setup_scheduled_tasks.ps1",
        ["-DailyTime", args.daily_time, "-MonthlyTime", args.monthly_time, "-AssumptionsMonthlyTime", args.assumptions_monthly_time, "-TaskPrefix", args.task_prefix],
    )


def cmd_schedule_remove(args: argparse.Namespace) -> int:
    return _run_powershell_script("remove_scheduled_tasks.ps1", ["-TaskPrefix", args.task_prefix])


def cmd_check_drive(_: argparse.Namespace) -> int:
    return _run_powershell_script("check_drive_config.ps1")


def cmd_sync_github(args: argparse.Namespace) -> int:
    config = _load_config()
    github_remote = args.github_remote or config.get("githubRemoteName") or "origin"
    github_branch = args.github_branch or config.get("githubBranch") or "main"
    github_commit_prefix = args.github_commit_prefix or config.get("githubCommitPrefix") or "auto: sync generated changes"
    return _run_powershell_script(
        "sync_github.ps1",
        ["-RemoteName", str(github_remote), "-Branch", str(github_branch), "-CommitPrefix", str(github_commit_prefix)],
    )


def cmd_github_dispatch(args: argparse.Namespace) -> int:
    config = _load_config()
    remote_name = args.github_remote or config.get("githubRemoteName") or "origin"
    ref = args.ref or config.get("githubBranch") or "main"
    repo_slug = args.repo_slug or config.get("githubRepoSlug") or ""
    inputs: dict[str, str] = {}

    if args.start:
        inputs["start"] = args.start
    if args.end:
        inputs["end"] = args.end
    if args.years is not None:
        inputs["years"] = str(args.years)
    if args.max_days is not None:
        inputs["max_days"] = str(args.max_days)
    if args.force:
        inputs["force"] = "true"
    if args.stop_on_error:
        inputs["stop_on_error"] = "true"

    try:
        _github_dispatch_workflow(remote_name, args.workflow, ref, inputs, repo_slug=repo_slug or None)
    except Exception as exc:
        print(f"[GitHub] dispatch failed: {exc}")
        return 1

    print(f"[GitHub] dispatched {args.workflow} on {remote_name}@{ref}")
    if inputs:
        print(f"[GitHub] inputs: {json.dumps(inputs, ensure_ascii=False)}")
    return 0


def cmd_github_check(_: argparse.Namespace) -> int:
    config = _load_config()
    required_env = [
        "DART_API_KEY",
        "KRX_ID",
        "KRX_PW",
        "GOOGLE_DRIVE_FOLDER_ID",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
    ]
    required_config = ["githubRemoteName", "githubBranch", "githubCommitPrefix", "enableGithubAutoSync"]
    missing_env = [name for name in required_env if not (os.environ.get(name) or config.get(name) or "").strip()]
    print(f"[GitHub] repo root: {BASE_DIR}")
    print(f"[GitHub] remote: {config.get('githubRemoteName', 'origin')}")
    print(f"[GitHub] branch: {config.get('githubBranch', 'main')}")
    print(f"[GitHub] commit prefix: {config.get('githubCommitPrefix', 'auto: sync generated changes')}")
    print(f"[GitHub] auto sync enabled: {config.get('enableGithubAutoSync', False)}")
    print(f"[GitHub] missing env: {', '.join(missing_env) if missing_env else 'none'}")
    print(f"[GitHub] config keys: {', '.join(required_config)}")
    return 0 if not missing_env else 1


def cmd_run_web(_: argparse.Namespace) -> int:
    return _run_powershell_script("run_web.ps1")


def cmd_backfill_history(args: argparse.Namespace) -> int:
    command = [sys.executable, str(SCRIPT_DIR / "history_backfill.py")]
    if args.start:
        command.extend(["--start", str(args.start)])
    if args.end:
        command.extend(["--end", str(args.end)])
    command.extend(["--years", str(args.years)])
    command.extend(["--period", str(args.period)])
    command.extend(["--output-mode", str(args.output_mode)])
    if args.limit and args.limit > 0:
        command.extend(["--limit", str(args.limit)])
    if args.max_days and args.max_days > 0:
        command.extend(["--max-days", str(args.max_days)])
    if args.force:
        command.append("--force")
    if args.stop_on_error:
        command.append("--stop-on-error")
    result = subprocess.run(command, cwd=BASE_DIR, check=False)
    return result.returncode


def cmd_status(_: argparse.Namespace) -> int:
    config = _load_config()
    print(f"[Status] config: {CONFIG_PATH}")
    print(f"[Status] pythonPath: {config.get('pythonPath', '')}")
    print(f"[Status] dailyTime: {config.get('dailyTime', '')}")
    print(f"[Status] monthlyTime: {config.get('monthlyTime', '')}")
    print(f"[Status] assumptionsMonthlyTime: {config.get('assumptionsMonthlyTime', '')}")
    print(f"[Status] taskPrefix: {config.get('taskPrefix', '')}")
    print(f"[Status] enableGoogleDriveUpload: {config.get('enableGoogleDriveUpload', False)}")
    print(f"[Status] googleDriveFolderId: {config.get('googleDriveFolderId', '')}")
    print(f"[Status] googleServiceAccountJsonPath: {config.get('googleServiceAccountJsonPath', '')}")

    for script_name in [
        "run_daily.ps1",
        "run_web.ps1",
        "run_backfill.ps1",
        "history_backfill.py",
        "run_eps_cache_refresh.ps1",
        "run_assumptions_refresh.ps1",
        "train_models.py",
        "setup_scheduled_tasks.ps1",
        "remove_scheduled_tasks.ps1",
        "check_drive_config.ps1",
        "install_automation.ps1",
    ]:
        script_path = BASE_DIR / "program" / "powershell" / script_name
        print(f"[Status] script {script_name}: {'OK' if script_path.exists() else 'MISSING'}")
    return 0


def cmd_train_models(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "train_models.py"),
        "--task",
        args.task,
    ]
    result = subprocess.run(command, cwd=BASE_DIR, check=False)
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operational admin CLI for UP Valuation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-config", help="Create or update up_valuation_config.json")
    init_parser.add_argument("--python-path", default="", help="Python executable path to store in config")
    init_parser.add_argument("--daily-time", default="08:30", help="Daily task schedule time")
    init_parser.add_argument("--monthly-time", default="08:00", help="Monthly EPS task time")
    init_parser.add_argument("--assumptions-monthly-time", default="08:10", help="Monthly assumptions task time")
    init_parser.add_argument("--task-prefix", default="UPValuation", help="Task Scheduler prefix")
    init_parser.set_defaults(func=cmd_init_config)

    env_parser = subparsers.add_parser("env-set", help="Update runtime environment values in config")
    env_parser.add_argument("--dart-key", default=None, help="DART API key")
    env_parser.add_argument("--krx-id", default=None, help="KRX ID")
    env_parser.add_argument("--krx-pw", default=None, help="KRX password")
    env_parser.add_argument("--google-drive-folder-id", default=None, help="Google Drive folder ID")
    env_parser.add_argument("--google-service-account-json", default=None, help="Google service account JSON path")
    env_parser.add_argument("--enable-google-drive-upload", action="store_true", help="Enable Google Drive upload")
    env_parser.add_argument("--disable-google-drive-upload", action="store_true", help="Disable Google Drive upload")
    env_parser.add_argument("--github-remote", default=None, help="Git remote name for sync")
    env_parser.add_argument("--github-branch", default=None, help="Git branch for sync")
    env_parser.add_argument("--github-commit-prefix", default=None, help="Git commit prefix for sync")
    env_parser.add_argument("--enable-github-auto-sync", action="store_true", help="Enable GitHub auto sync")
    env_parser.add_argument("--disable-github-auto-sync", action="store_true", help="Disable GitHub auto sync")
    env_parser.set_defaults(func=cmd_env_set)

    install_parser = subparsers.add_parser("install-automation", help="Run install_automation.ps1")
    install_parser.add_argument("--daily-time", default="08:30", help="Daily task schedule time")
    install_parser.add_argument("--monthly-time", default="08:00", help="Monthly EPS task time")
    install_parser.add_argument("--assumptions-monthly-time", default="08:10", help="Monthly assumptions task time")
    install_parser.add_argument("--task-prefix", default="UPValuation", help="Task Scheduler prefix")
    install_parser.set_defaults(func=cmd_install_automation)

    schedule_install_parser = subparsers.add_parser("schedule-install", help="Register scheduled tasks")
    schedule_install_parser.add_argument("--daily-time", default="08:30", help="Daily task schedule time")
    schedule_install_parser.add_argument("--monthly-time", default="08:00", help="Monthly EPS task time")
    schedule_install_parser.add_argument("--assumptions-monthly-time", default="08:10", help="Monthly assumptions task time")
    schedule_install_parser.add_argument("--task-prefix", default="UPValuation", help="Task Scheduler prefix")
    schedule_install_parser.set_defaults(func=cmd_schedule_install)

    schedule_remove_parser = subparsers.add_parser("schedule-remove", help="Remove scheduled tasks")
    schedule_remove_parser.add_argument("--task-prefix", default="UPValuation", help="Task Scheduler prefix")
    schedule_remove_parser.set_defaults(func=cmd_schedule_remove)

    drive_parser = subparsers.add_parser("check-drive", help="Validate Google Drive configuration")
    drive_parser.set_defaults(func=cmd_check_drive)

    sync_parser = subparsers.add_parser("sync-github", help="Sync workspace changes to GitHub")
    sync_parser.add_argument("--github-remote", default=None, help="Git remote name for sync")
    sync_parser.add_argument("--github-branch", default=None, help="Git branch for sync")
    sync_parser.add_argument("--github-commit-prefix", default=None, help="Git commit prefix for sync")
    sync_parser.set_defaults(func=cmd_sync_github)

    github_check_parser = subparsers.add_parser("github-check", help="Check GitHub automation readiness")
    github_check_parser.set_defaults(func=cmd_github_check)

    github_dispatch_parser = subparsers.add_parser("github-dispatch", help="Dispatch a GitHub Actions workflow")
    github_dispatch_parser.add_argument("--workflow", required=True, help="Workflow file name under .github/workflows")
    github_dispatch_parser.add_argument("--github-remote", default=None, help="Git remote name for repo lookup")
    github_dispatch_parser.add_argument("--repo-slug", default=None, help="Explicit GitHub repository slug (owner/repo)")
    github_dispatch_parser.add_argument("--ref", default=None, help="Git ref/branch to dispatch")
    github_dispatch_parser.add_argument("--start", default="", help="Dispatch input: start date")
    github_dispatch_parser.add_argument("--end", default="", help="Dispatch input: end date")
    github_dispatch_parser.add_argument("--years", type=int, default=None, help="Dispatch input: historical years")
    github_dispatch_parser.add_argument("--max-days", type=int, default=None, help="Dispatch input: max days")
    github_dispatch_parser.add_argument("--force", action="store_true", help="Dispatch input: force")
    github_dispatch_parser.add_argument("--stop-on-error", action="store_true", help="Dispatch input: stop on error")
    github_dispatch_parser.set_defaults(func=cmd_github_dispatch)

    web_parser = subparsers.add_parser("web-run", help="Launch the Streamlit dashboard")
    web_parser.set_defaults(func=cmd_run_web)

    backfill_parser = subparsers.add_parser("backfill-history", help="Generate historical daily snapshots")
    backfill_parser.add_argument("--start", default="", help="Start date in YYYY-MM-DD")
    backfill_parser.add_argument("--end", default="", help="End date in YYYY-MM-DD")
    backfill_parser.add_argument("--years", type=int, default=5, help="Historical range in years when start is omitted")
    backfill_parser.add_argument("--period", default="1y", help="yfinance period passed to build_daily_report.py")
    backfill_parser.add_argument("--output-mode", default="compact", choices=["compact", "full"], help="Report output mode")
    backfill_parser.add_argument("--limit", type=int, default=0, help="Optional ticker limit for quick testing")
    backfill_parser.add_argument("--max-days", type=int, default=0, help="Optional cap on the number of business days to process")
    backfill_parser.add_argument("--force", action="store_true", help="Regenerate dates even if report files already exist")
    backfill_parser.add_argument("--stop-on-error", action="store_true", help="Stop when a backfill day fails")
    backfill_parser.set_defaults(func=cmd_backfill_history)

    status_parser = subparsers.add_parser("status", help="Show current operational config and script availability")
    status_parser.set_defaults(func=cmd_status)

    train_parser = subparsers.add_parser("train-models", help="Run baseline model training")
    train_parser.add_argument("--task", choices=["alpha", "entry", "both"], default="both", help="Which model task to train")
    train_parser.set_defaults(func=cmd_train_models)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
