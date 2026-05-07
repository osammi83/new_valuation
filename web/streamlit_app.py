from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from google_drive_browser import build_drive_service, download_file_bytes, list_files

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
DRIVE_CACHE_DIR = BASE_DIR / ".drive_cache"


def _setting(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            value = st.secrets[name]
        else:
            value = st.secrets.get(name, default)
    except Exception:
        value = os.environ.get(name, default)
    if value is None:
        return default
    return str(value)


def _setting_bool(name: str, default: bool = False) -> bool:
    raw_value = _setting(name, "true" if default else "false").strip().lower()
    return raw_value in {"1", "true", "t", "yes", "y", "on"}


PUBLIC_APP_MODE = _setting_bool("PUBLIC_APP_MODE")
PUBLIC_GITHUB_REPO_SLUG = _setting("GITHUB_REPO_SLUG") or _setting("GITHUB_REPOSITORY")
PUBLIC_GOOGLE_DRIVE_FOLDER_ID = _setting("GOOGLE_DRIVE_FOLDER_ID")
PUBLIC_GOOGLE_SERVICE_ACCOUNT_JSON = _setting("GOOGLE_SERVICE_ACCOUNT_JSON")

REPORT_PATTERNS = {
    "상세리포트": "상세리포트_*.csv",
    "핵심근거": "종목선정_핵심근거_*.csv",
    "최종매수타임라인": "최종매수_30일타임라인_*.csv",
    "전일비교": "최종매수_전일비교_*.csv",
    "관심종목요약": "관심종목요약_*.csv",
    "진입후보요약": "진입후보요약_*.csv",
    "신호성과요약": "신호성과요약_*.csv",
    "신호발생상세": "신호발생상세_*.csv",
    "종목선정판단보조": "종목선정_판단보조_*.csv",
    "신호지표가이드": "신호지표_초보자가이드_*.csv",
    "우선검토": "종목선정_우선검토_*.csv",
    "런히스토리": "run_history.csv",
    "에러로그": "error_log.csv",
    "퍼블리시히스토리": "output/publish_history.csv",
    "백필히스토리": "output/history_backfill_runs.csv",
    "모델레지스트리": "model_registry.csv",
    "피처중요도": "feature_importance.csv",
    "백테스트요약": "output/backtest_summary_*.csv",
    "백테스트거래": "output/backtest_trades_*.csv",
}

REPORT_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})(?:_vs_.+)?\.csv$")


def _find_files(pattern: str) -> list[Path]:
    if _drive_available():
        return _mirror_drive_matches(pattern)
    if pattern.startswith("output/"):
        return sorted(OUTPUT_DIR.glob(pattern.removeprefix("output/")), key=lambda path: path.stat().st_mtime)
    if pattern.startswith("*.csv"):
        return sorted(BASE_DIR.glob(pattern), key=lambda path: path.stat().st_mtime)
    if "*" in pattern:
        return sorted(BASE_DIR.glob(pattern), key=lambda path: path.stat().st_mtime)
    path = BASE_DIR / pattern
    return [path] if path.exists() else []


def _latest_file(pattern: str) -> Path | None:
    files = [path for path in _find_files(pattern) if path.exists()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def _extract_report_date(path: Path) -> str | None:
    match = REPORT_DATE_RE.search(path.name)
    if not match:
        return None
    return match.group(1)


def _available_report_dates() -> list[str]:
    if _drive_available():
        dates = {date for file_info in _drive_match_files("상세리포트_*.csv") if (date := _extract_report_date(Path(str(file_info.get("name", ""))))) }
        return sorted(dates, reverse=True)
    if not OUTPUT_DIR.exists():
        return []
    dates = {date for path in OUTPUT_DIR.glob("상세리포트_*.csv") if (date := _extract_report_date(path))}
    return sorted(dates, reverse=True)


def _resolve_file(pattern: str, selected_date: str | None) -> Path | None:
    if not selected_date:
        return _latest_file(pattern)
    if "*" not in pattern:
        return _latest_file(pattern)
    exact = pattern.replace("*", selected_date)
    matches = _find_files(exact)
    if matches:
        return matches[-1]
    return _latest_file(pattern)


@st.cache_data(show_spinner=False)
def _load_csv(path_str: str) -> pd.DataFrame:
    path = Path(path_str)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def _drive_available() -> bool:
    return bool(PUBLIC_APP_MODE and PUBLIC_GOOGLE_DRIVE_FOLDER_ID and PUBLIC_GOOGLE_SERVICE_ACCOUNT_JSON)


@st.cache_resource(show_spinner=False)
def _drive_service():
    if not _drive_available():
        return None
    return build_drive_service(PUBLIC_GOOGLE_SERVICE_ACCOUNT_JSON)


@st.cache_data(show_spinner=False)
def _drive_file_index() -> list[dict[str, object]]:
    service = _drive_service()
    if service is None:
        return []
    return list_files(service, PUBLIC_GOOGLE_DRIVE_FOLDER_ID)


def _normalized_drive_pattern(pattern: str) -> str:
    return pattern.removeprefix("output/")


def _drive_match_files(pattern: str) -> list[dict[str, object]]:
    normalized_pattern = _normalized_drive_pattern(pattern)
    files = [file_info for file_info in _drive_file_index() if fnmatch.fnmatch(str(file_info.get("name", "")), normalized_pattern)]
    return sorted(files, key=lambda item: str(item.get("modifiedTime", "")))


def _drive_cache_path(file_name: str) -> Path:
    return DRIVE_CACHE_DIR / file_name


def _mirror_drive_file(file_info: dict[str, object]) -> Path:
    service = _drive_service()
    if service is None:
        raise RuntimeError("Google Drive service is not available")

    file_name = str(file_info.get("name", ""))
    file_id = str(file_info.get("id", ""))
    modified_time = str(file_info.get("modifiedTime", ""))
    cache_path = _drive_cache_path(file_name)
    metadata_path = cache_path.with_suffix(cache_path.suffix + ".meta.json")

    if cache_path.exists() and metadata_path.exists():
        try:
            cached_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            if str(cached_meta.get("modifiedTime", "")) == modified_time:
                return cache_path
        except Exception:
            pass

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(download_file_bytes(service, file_id))
    metadata_path.write_text(json.dumps({"modifiedTime": modified_time}, ensure_ascii=False), encoding="utf-8")
    return cache_path


def _mirror_drive_matches(pattern: str) -> list[Path]:
    return [_mirror_drive_file(file_info) for file_info in _drive_match_files(pattern)]


def _load_preview(path: Path, limit: int = 50) -> pd.DataFrame:
    df = _load_csv(str(path))
    if df.empty:
        return df
    return df.head(limit)


def _summarize_report(df: pd.DataFrame) -> dict[str, object]:
    if df.empty:
        return {"rows": 0}

    summary: dict[str, object] = {"rows": int(len(df))}
    if "결합액션" in df.columns:
        summary["결합액션"] = df["결합액션"].value_counts(dropna=False).to_dict()
    if "마켓레짐" in df.columns:
        summary["마켓레짐"] = df["마켓레짐"].value_counts(dropna=False).to_dict()
    if "섹터그룹" in df.columns:
        summary["섹터그룹 수"] = int(df["섹터그룹"].nunique(dropna=True))
    if "적자여부" in df.columns:
        summary["적자여부=1"] = int((pd.to_numeric(df["적자여부"], errors="coerce") == 1).sum())
    if "권장비중(%)" in df.columns:
        summary["권장비중 평균"] = float(pd.to_numeric(df["권장비중(%)"], errors="coerce").fillna(0).mean())
    if "기준일" in df.columns:
        summary["기준일"] = str(df["기준일"].iloc[0])
    return summary


def _list_output_files() -> list[Path]:
    if _drive_available():
        return sorted(_mirror_drive_matches("*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not OUTPUT_DIR.exists():
        return []
    return sorted([path for path in OUTPUT_DIR.glob("*.csv") if path.is_file()], key=lambda path: path.stat().st_mtime, reverse=True)


def _render_metric_grid(summary: dict[str, object]) -> None:
    cols = st.columns(5)
    cols[0].metric("rows", str(summary.get("rows", 0)))
    cols[1].metric("섹터 수", str(summary.get("섹터그룹 수", 0)))
    cols[2].metric("적자여부=1", str(summary.get("적자여부=1", 0)))
    cols[3].metric("권장비중 평균", f"{float(summary.get('권장비중 평균', 0.0)):.2f}%")
    cols[4].metric("기준일", str(summary.get("기준일", "-")))


def _render_file_preview(title: str, path: Path | None, limit: int) -> None:
    st.subheader(title)
    if path is None:
        st.info("선택한 파일을 찾지 못했습니다.")
        return

    st.caption(str(path))
    df = _load_preview(path, limit=limit)
    if df.empty:
        st.info("표시할 데이터가 없습니다.")
        return
    st.dataframe(df, use_container_width=True)
    st.download_button(
        label=f"{title} 다운로드",
        data=path.read_bytes(),
        file_name=path.name,
        mime="text/csv",
        key=f"download_{title}_{path.name}",
    )


def _run_local_command(command: list[str]) -> tuple[int, str]:
    env = os.environ.copy()
    github_token = _setting("GITHUB_TOKEN") or _setting("GH_TOKEN")
    if github_token:
        env["GITHUB_TOKEN"] = github_token
        env["GH_TOKEN"] = github_token
    if PUBLIC_GITHUB_REPO_SLUG:
        env["GITHUB_REPO_SLUG"] = PUBLIC_GITHUB_REPO_SLUG
    completed = subprocess.run(
        command,
        cwd=BASE_DIR,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    output = "".join([completed.stdout or "", completed.stderr or ""]).strip()
    return completed.returncode, output or "(no output)"


st.set_page_config(page_title="03.new_valuation Web Dashboard", layout="wide")
st.title("03.new_valuation Web Dashboard")
st.caption("최신 산출물, 선택 날짜, 실행 이력, 오류 로그, 모델 기록을 한 화면에서 확인합니다.")

available_dates = _available_report_dates()
default_date = available_dates[0] if available_dates else None

with st.sidebar:
    st.header("대시보드 설정")
    file_options = list(REPORT_PATTERNS.keys())
    selected_key = st.selectbox("보기", file_options, index=0)
    selected_date = st.selectbox("기준일", ["최신"] + available_dates if available_dates else ["최신"], index=0)
    limit = st.slider("미리보기 행 수", min_value=10, max_value=200, value=50, step=10)
    st.write(f"마지막 갱신: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if st.button("새로고침"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

resolved_date = None if selected_date == "최신" else selected_date
pattern = REPORT_PATTERNS[selected_key]
target_path = _resolve_file(pattern, resolved_date)

if PUBLIC_APP_MODE:
    if _drive_available():
        st.info("공용앱은 Google Drive에 저장된 CSV를 읽어서 보여주고, 다운로드도 제공합니다.")
    else:
        st.warning("공용앱 secrets에 GOOGLE_DRIVE_FOLDER_ID와 GOOGLE_SERVICE_ACCOUNT_JSON이 있어야 Google Drive 파일을 읽을 수 있습니다.")

if target_path is None:
    st.warning(f"대상 파일을 찾지 못했습니다: {pattern}")
    st.stop()

st.subheader(f"선택 파일: {selected_key}")
st.write(str(target_path))
st.write(f"수정 시각: {datetime.fromtimestamp(target_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
st.download_button(
    label="현재 파일 다운로드",
    data=target_path.read_bytes(),
    file_name=target_path.name,
    mime="text/csv",
    key=f"download_current_{target_path.name}",
)

if selected_key == "상세리포트":
    report_df = _load_csv(str(target_path))
    summary = _summarize_report(report_df)
    _render_metric_grid(summary)
    tab_preview, tab_summary, tab_columns = st.tabs(["미리보기", "요약", "컬럼"])
    with tab_preview:
        st.dataframe(report_df.head(limit), use_container_width=True)
        if "종합점수" in report_df.columns:
            st.line_chart(pd.to_numeric(report_df["종합점수"], errors="coerce"))
    with tab_summary:
        st.json(summary)
        if "결합액션" in report_df.columns:
            st.bar_chart(report_df["결합액션"].value_counts())
    with tab_columns:
        st.write(list(report_df.columns))
        st.write(f"행 수: {len(report_df)}")
elif selected_key in {"핵심근거", "최종매수타임라인", "전일비교", "관심종목요약", "진입후보요약", "신호성과요약", "신호발생상세", "종목선정판단보조", "신호지표가이드", "우선검토"}:
    st.dataframe(_load_preview(target_path, limit=limit), use_container_width=True)
else:
    st.dataframe(_load_csv(str(target_path)).head(limit), use_container_width=True)

st.divider()

tab_overview, tab_run, tab_reports, tab_ops, tab_files = st.tabs(["개요", "실행", "리포트", "운영", "파일목록"])

with tab_overview:
    cols = st.columns(4)
    latest_report = _latest_file(REPORT_PATTERNS["상세리포트"])
    latest_run = _latest_file(REPORT_PATTERNS["런히스토리"])
    latest_error = _latest_file(REPORT_PATTERNS["에러로그"])
    latest_model = _latest_file(REPORT_PATTERNS["모델레지스트리"])
    cols[0].metric("보고서", default_date or "-", help=str(latest_report) if latest_report else "")
    cols[1].metric("실행 이력", "ON" if latest_run else "OFF")
    cols[2].metric("오류 로그", "ON" if latest_error else "OFF")
    cols[3].metric("모델 레지스트리", "ON" if latest_model else "OFF")

    if latest_report:
        report_df = _load_csv(str(latest_report))
        summary = _summarize_report(report_df)
        _render_metric_grid(summary)
        st.dataframe(report_df.head(limit), use_container_width=True)
    else:
        st.info("상세리포트가 없습니다.")

with tab_run:
    st.subheader("웹에서 바로 실행")
    if PUBLIC_APP_MODE:
        st.caption("공용 배포 모드에서는 로컬 Windows 실행을 숨기고, GitHub Actions dispatch만 허용한다.")
        st.info("공용앱에서는 일일 실행/소스 반영을 직접 수행하지 않고, GitHub Actions로 원격 실행한다.")
    else:
        st.caption("이 화면은 로컬 Streamlit에서 Python 스크립트를 직접 실행한다. GitHub 반영은 동기화 버튼으로 수행한다.")

        col_daily, col_sync = st.columns(2)
        with col_daily:
            st.markdown("#### 일일 실행")
            st.write("`run_pipeline.py daily`를 현재 워크스페이스에서 실행한다.")
            if st.button("일일 실행 시작", type="primary", key="run_daily_button"):
                with st.spinner("일일 파이프라인 실행 중..."):
                    exit_code, output = _run_local_command([sys.executable, str(BASE_DIR / "run_pipeline.py"), "daily"])
                st.session_state["last_daily_run"] = {"exit_code": exit_code, "output": output}

            daily_result = st.session_state.get("last_daily_run")
            if daily_result:
                if daily_result["exit_code"] == 0:
                    st.success("일일 실행 완료")
                else:
                    st.error(f"일일 실행 실패: exit code {daily_result['exit_code']}")
                st.code(daily_result["output"], language="text")

        with col_sync:
            st.markdown("#### GitHub 소스 반영")
            st.write("`sync_github.ps1`를 통해 현재 변경분을 GitHub로 push 한다.")
            if st.button("GitHub 반영 시작", key="run_sync_button"):
                with st.spinner("GitHub 반영 중..."):
                    exit_code, output = _run_local_command([sys.executable, str(BASE_DIR / "ops_admin.py"), "sync-github"])
                st.session_state["last_github_sync"] = {"exit_code": exit_code, "output": output}

            sync_result = st.session_state.get("last_github_sync")
            if sync_result:
                if sync_result["exit_code"] == 0:
                    st.success("GitHub 반영 완료")
                else:
                    st.warning(f"GitHub 반영 실패: exit code {sync_result['exit_code']}")
                st.code(sync_result["output"], language="text")

    st.divider()

    st.markdown("#### GitHub Actions 실행")
    st.caption("원격 저장소에서 workflow_dispatch를 호출한다. 실행에는 `GITHUB_TOKEN` 또는 `GH_TOKEN`이 필요하다.")

    if PUBLIC_APP_MODE and not PUBLIC_GITHUB_REPO_SLUG:
        st.warning("공용앱 secrets에 GITHUB_REPO_SLUG(owner/repo)을 넣어야 GitHub Actions를 실행할 수 있다.")

    workflow_key = st.selectbox(
        "워크플로우",
        ["auto-sync.yml", "backfill_5y.yml", "ci.yml"],
        index=0,
        key="github_workflow_select",
    )
    github_ref = st.text_input("ref", value="main", key="github_workflow_ref")

    dispatch_inputs: dict[str, str] = {}
    if workflow_key == "backfill_5y.yml":
        dispatch_cols = st.columns(4)
        with dispatch_cols[0]:
            dispatch_start = st.text_input("start", value="", key="github_dispatch_start")
        with dispatch_cols[1]:
            dispatch_end = st.text_input("end", value="", key="github_dispatch_end")
        with dispatch_cols[2]:
            dispatch_years = st.number_input("years", min_value=1, max_value=10, value=5, step=1, key="github_dispatch_years")
        with dispatch_cols[3]:
            dispatch_max_days = st.number_input("max days", min_value=0, max_value=365, value=0, step=1, key="github_dispatch_max_days")
        dispatch_force = st.checkbox("force", value=False, key="github_dispatch_force")
        dispatch_stop_on_error = st.checkbox("stop on error", value=True, key="github_dispatch_stop_on_error")
        if dispatch_start:
            dispatch_inputs["--start"] = dispatch_start
        if dispatch_end:
            dispatch_inputs["--end"] = dispatch_end
        dispatch_inputs["--years"] = str(int(dispatch_years))
        if int(dispatch_max_days) > 0:
            dispatch_inputs["--max-days"] = str(int(dispatch_max_days))
        if dispatch_force:
            dispatch_inputs["--force"] = ""
        if dispatch_stop_on_error:
            dispatch_inputs["--stop-on-error"] = ""

    if st.button("GitHub Actions 실행", key="run_github_dispatch_button"):
        command = [
            sys.executable,
            str(BASE_DIR / "ops_admin.py"),
            "github-dispatch",
            "--workflow",
            workflow_key,
            "--ref",
            github_ref,
        ]
        if PUBLIC_GITHUB_REPO_SLUG:
            command.extend(["--repo-slug", PUBLIC_GITHUB_REPO_SLUG])
        for key, value in dispatch_inputs.items():
            command.append(key)
            if value:
                command.append(value)
        with st.spinner("GitHub Actions dispatch 중..."):
            exit_code, output = _run_local_command(command)
        st.session_state["last_github_dispatch"] = {"exit_code": exit_code, "output": output}

    dispatch_result = st.session_state.get("last_github_dispatch")
    if dispatch_result:
        if dispatch_result["exit_code"] == 0:
            st.success("GitHub Actions 실행 요청 완료")
        else:
            st.error(f"GitHub Actions 실행 요청 실패: exit code {dispatch_result['exit_code']}")
        st.code(dispatch_result["output"], language="text")

    st.divider()

    st.markdown("#### 백필 실행")
    backfill_cols = st.columns(4)
    with backfill_cols[0]:
        backfill_days = st.number_input("max days", min_value=1, max_value=365, value=5, step=1)
    with backfill_cols[1]:
        backfill_limit = st.number_input("limit", min_value=0, max_value=2000, value=1, step=1)
    with backfill_cols[2]:
        backfill_force = st.checkbox("force", value=False)
    with backfill_cols[3]:
        backfill_stop_on_error = st.checkbox("stop on error", value=True)

    if st.button("백필 시작", key="run_backfill_button"):
        command = [sys.executable, str(BASE_DIR / "history_backfill.py"), "--max-days", str(int(backfill_days))]
        if int(backfill_limit) > 0:
            command.extend(["--limit", str(int(backfill_limit))])
        if backfill_force:
            command.append("--force")
        if backfill_stop_on_error:
            command.append("--stop-on-error")
        with st.spinner("백필 실행 중..."):
            exit_code, output = _run_local_command(command)
        st.session_state["last_backfill_run"] = {"exit_code": exit_code, "output": output}

    backfill_result = st.session_state.get("last_backfill_run")
    if backfill_result:
        if backfill_result["exit_code"] == 0:
            st.success("백필 실행 완료")
        else:
            st.error(f"백필 실행 실패: exit code {backfill_result['exit_code']}")
        st.code(backfill_result["output"], language="text")

with tab_reports:
    report_cards = [
        ("상세리포트", REPORT_PATTERNS["상세리포트"]),
        ("핵심근거", REPORT_PATTERNS["핵심근거"]),
        ("최종매수타임라인", REPORT_PATTERNS["최종매수타임라인"]),
        ("전일비교", REPORT_PATTERNS["전일비교"]),
        ("신호성과요약", REPORT_PATTERNS["신호성과요약"]),
    ]
    for title, pattern_name in report_cards:
        _render_file_preview(title, _resolve_file(pattern_name, resolved_date), limit=limit)

with tab_ops:
    run_history = _latest_file(REPORT_PATTERNS["런히스토리"])
    error_log = _latest_file(REPORT_PATTERNS["에러로그"])
    publish_history = _latest_file(REPORT_PATTERNS["퍼블리시히스토리"])
    backfill_history = _latest_file(REPORT_PATTERNS["백필히스토리"])
    model_registry = _latest_file(REPORT_PATTERNS["모델레지스트리"])
    feature_importance = _latest_file(REPORT_PATTERNS["피처중요도"])

    st.subheader("실행/오류/배포")
    st.columns(2)
    _render_file_preview("실행 이력", run_history, limit=limit)
    _render_file_preview("오류 로그", error_log, limit=limit)
    _render_file_preview("배포 이력", publish_history, limit=limit)
    _render_file_preview("백필 이력", backfill_history, limit=limit)
    _render_file_preview("모델 레지스트리", model_registry, limit=limit)
    _render_file_preview("피처 중요도", feature_importance, limit=limit)

with tab_files:
    output_files = _list_output_files()
    if output_files:
        recent = pd.DataFrame(
            [
                {
                    "name": path.name,
                    "date": _extract_report_date(path) or "-",
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    "size_kb": round(path.stat().st_size / 1024.0, 1),
                }
                for path in output_files[:50]
            ]
        )
        st.dataframe(recent, use_container_width=True)
        selected_download_name = st.selectbox("다운로드할 파일", [path.name for path in output_files], key="file_download_select")
        selected_download_path = next((path for path in output_files if path.name == selected_download_name), None)
        if selected_download_path is not None:
            st.download_button(
                label="선택 파일 다운로드",
                data=selected_download_path.read_bytes(),
                file_name=selected_download_path.name,
                mime="text/csv",
                key=f"download_file_list_{selected_download_path.name}",
            )
    else:
        st.info("output 폴더에 CSV가 없습니다.")
