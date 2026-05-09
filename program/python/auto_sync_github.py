from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "up_valuation_config.json"


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Invalid config JSON: {CONFIG_PATH}") from exc


def _resolve_git_executable() -> str:
    git_override = os.environ.get("GIT_EXE", "").strip()
    if git_override:
        override_path = Path(git_override)
        if override_path.exists():
            return str(override_path)

    git_exe = shutil.which("git") or shutil.which("git.exe")
    if not git_exe:
        common_locations = [
            Path(r"C:\Program Files\Git\cmd\git.exe"),
            Path(r"C:\Program Files\Git\bin\git.exe"),
            Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
            Path(r"C:\Program Files (x86)\Git\bin\git.exe"),
            Path.home() / r"AppData\Local\Programs\Git\cmd\git.exe",
            Path.home() / r"AppData\Local\Programs\Git\bin\git.exe",
        ]
        for candidate in common_locations:
            if candidate.exists():
                return str(candidate)
        raise RuntimeError("git executable not found. Install Git or set GIT_EXE to the full git.exe path.")
    return git_exe


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    git_exe = _resolve_git_executable()
    return subprocess.run([git_exe, "-C", str(BASE_DIR), *args], check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _print_output(result: subprocess.CompletedProcess[str]) -> None:
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Add, commit, and push workspace changes to GitHub")
    parser.add_argument("--remote", default="", help="Git remote name (default: config githubRemoteName or origin)")
    parser.add_argument("--branch", default="", help="Git branch name (default: config githubBranch or main)")
    parser.add_argument("--commit-prefix", default="", help="Commit message prefix (default: config githubCommitPrefix)")
    parser.add_argument("--message", default="", help="Optional full commit message override")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without changing git state")
    args = parser.parse_args()

    config = _load_config()
    remote = args.remote or str(config.get("githubRemoteName") or "origin")
    branch = args.branch or str(config.get("githubBranch") or "main")
    commit_prefix = args.commit_prefix or str(config.get("githubCommitPrefix") or "auto: sync generated changes")

    status_result = _run_git(["status", "--porcelain"])
    if status_result.returncode != 0:
        _print_output(status_result)
        print("[Git] status failed.")
        return status_result.returncode

    if not (status_result.stdout or "").strip():
        print("[Git] No changes to sync.")
        return 0

    if args.dry_run:
        print(f"[Git] dry-run: add -A, commit, push {remote}/{branch}")
        return 0

    add_result = _run_git(["add", "-A"])
    if add_result.returncode != 0:
        _print_output(add_result)
        print("[Git] git add failed.")
        return add_result.returncode

    if args.message:
        message = args.message
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"{commit_prefix} {timestamp}"

    commit_result = _run_git(["commit", "-m", message])
    if commit_result.returncode != 0:
        _print_output(commit_result)
        print("[Git] git commit failed.")
        return commit_result.returncode

    push_result = _run_git(["push", remote, branch])
    if push_result.returncode != 0:
        _print_output(push_result)
        print("[Git] git push failed.")
        return push_result.returncode

    print(f"[Git] Synced to {remote}/{branch} with message: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
