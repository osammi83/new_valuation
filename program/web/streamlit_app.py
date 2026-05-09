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

BASE_DIR = Path(__file__).resolve().parents[2]
PYTHON_DIR = BASE_DIR / "program" / "python"
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
PUBLIC_VIEW_ONLY_MODE = PUBLIC_APP_MODE

REPORT_PATTERNS = {
    "?곸꽭由ы룷??: "?곸꽭由ы룷??*.csv",
    "?듭떖洹쇨굅": "醫낅ぉ?좎젙_?듭떖洹쇨굅_*.csv",
    "理쒖쥌留ㅼ닔??꾨씪??: "理쒖쥌留ㅼ닔_30?쇳??꾨씪??*.csv",
    "?꾩씪鍮꾧탳": "理쒖쥌留ㅼ닔_?꾩씪鍮꾧탳_*.csv",
    "愿?ъ쥌紐⑹슂??: "愿?ъ쥌紐⑹슂??*.csv",
    "吏꾩엯?꾨낫?붿빟": "吏꾩엯?꾨낫?붿빟_*.csv",
    "?좏샇?깃낵?붿빟": "?좏샇?깃낵?붿빟_*.csv",
    "?좏샇諛쒖깮?곸꽭": "?좏샇諛쒖깮?곸꽭_*.csv",
    "醫낅ぉ?좎젙?먮떒蹂댁“": "醫낅ぉ?좎젙_?먮떒蹂댁“_*.csv",
    "?좏샇吏?쒓??대뱶": "?좏샇吏??珥덈낫?먭??대뱶_*.csv",
    "?곗꽑寃??: "醫낅ぉ?좎젙_?곗꽑寃??*.csv",
    "?고엳?ㅽ넗由?: "run_history.csv",
    "?먮윭濡쒓렇": "error_log.csv",
    "?쇰툝由ъ떆?덉뒪?좊━": "output/publish_history.csv",
    "諛깊븘?덉뒪?좊━": "output/history_backfill_runs.csv",
    "紐⑤뜽?덉??ㅽ듃由?: "model_registry.csv",
    "?쇱쿂以묒슂??: "feature_importance.csv",
    "諛깊뀒?ㅽ듃?붿빟": "output/backtest_summary_*.csv",
    "諛깊뀒?ㅽ듃嫄곕옒": "output/backtest_trades_*.csv",
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
        dates = {date for file_info in _drive_match_files("?곸꽭由ы룷??*.csv") if (date := _extract_report_date(Path(str(file_info.get("name", ""))))) }
        return sorted(dates, reverse=True)
    if not OUTPUT_DIR.exists():
        return []
    dates = {date for path in OUTPUT_DIR.glob("?곸꽭由ы룷??*.csv") if (date := _extract_report_date(path))}
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
    if "寃고빀?≪뀡" in df.columns:
        summary["寃고빀?≪뀡"] = df["寃고빀?≪뀡"].value_counts(dropna=False).to_dict()
    if "留덉폆?덉쭚" in df.columns:
        summary["留덉폆?덉쭚"] = df["留덉폆?덉쭚"].value_counts(dropna=False).to_dict()
    if "?뱁꽣洹몃９" in df.columns:
        summary["?뱁꽣洹몃９ ??] = int(df["?뱁꽣洹몃９"].nunique(dropna=True))
    if "?곸옄?щ?" in df.columns:
        summary["?곸옄?щ?=1"] = int((pd.to_numeric(df["?곸옄?щ?"], errors="coerce") == 1).sum())
    if "沅뚯옣鍮꾩쨷(%)" in df.columns:
        summary["沅뚯옣鍮꾩쨷 ?됯퇏"] = float(pd.to_numeric(df["沅뚯옣鍮꾩쨷(%)"], errors="coerce").fillna(0).mean())
    if "湲곗??? in df.columns:
        summary["湲곗???] = str(df["湲곗???].iloc[0])
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
    cols[1].metric("?뱁꽣 ??, str(summary.get("?뱁꽣洹몃９ ??, 0)))
    cols[2].metric("?곸옄?щ?=1", str(summary.get("?곸옄?щ?=1", 0)))
    cols[3].metric("沅뚯옣鍮꾩쨷 ?됯퇏", f"{float(summary.get('沅뚯옣鍮꾩쨷 ?됯퇏', 0.0)):.2f}%")
    cols[4].metric("湲곗???, str(summary.get("湲곗???, "-")))


def _render_file_preview(title: str, path: Path | None, limit: int) -> None:
    st.subheader(title)
    if path is None:
        st.info("?좏깮???뚯씪??李얠? 紐삵뻽?듬땲??")
        return

    st.caption(str(path))
    df = _load_preview(path, limit=limit)
    if df.empty:
        st.info("?쒖떆???곗씠?곌? ?놁뒿?덈떎.")
        return
    st.dataframe(df, use_container_width=True)
    st.download_button(
        label=f"{title} ?ㅼ슫濡쒕뱶",
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
st.caption("理쒖떊 ?곗텧臾? ?좏깮 ?좎쭨, ?ㅽ뻾 ?대젰, ?ㅻ쪟 濡쒓렇, 紐⑤뜽 湲곕줉?????붾㈃?먯꽌 ?뺤씤?⑸땲??")

available_dates = _available_report_dates()
default_date = available_dates[0] if available_dates else None

with st.sidebar:
    st.header("??쒕낫???ㅼ젙")
    file_options = list(REPORT_PATTERNS.keys())
    selected_key = st.selectbox("蹂닿린", file_options, index=0)
    selected_date = st.selectbox("湲곗???, ["理쒖떊"] + available_dates if available_dates else ["理쒖떊"], index=0)
    limit = st.slider("誘몃━蹂닿린 ????, min_value=10, max_value=200, value=50, step=10)
    st.write(f"留덉?留?媛깆떊: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if st.button("?덈줈怨좎묠"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

resolved_date = None if selected_date == "理쒖떊" else selected_date
pattern = REPORT_PATTERNS[selected_key]
target_path = _resolve_file(pattern, resolved_date)

if PUBLIC_APP_MODE:
    if _drive_available():
        st.info("怨듭슜?깆? Google Drive????λ맂 CSV瑜??쎌뼱??蹂댁뿬二쇨퀬, ?ㅼ슫濡쒕뱶???쒓났?⑸땲??")
    else:
        st.warning("怨듭슜??secrets??GOOGLE_DRIVE_FOLDER_ID? GOOGLE_SERVICE_ACCOUNT_JSON???덉뼱??Google Drive ?뚯씪???쎌쓣 ???덉뒿?덈떎.")

if target_path is None:
    st.warning(f"????뚯씪??李얠? 紐삵뻽?듬땲?? {pattern}")
    st.stop()

st.subheader(f"?좏깮 ?뚯씪: {selected_key}")
st.write(str(target_path))
st.write(f"?섏젙 ?쒓컖: {datetime.fromtimestamp(target_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
st.download_button(
    label="?꾩옱 ?뚯씪 ?ㅼ슫濡쒕뱶",
    data=target_path.read_bytes(),
    file_name=target_path.name,
    mime="text/csv",
    key=f"download_current_{target_path.name}",
)

if selected_key == "?곸꽭由ы룷??:
    report_df = _load_csv(str(target_path))
    summary = _summarize_report(report_df)
    _render_metric_grid(summary)
    tab_preview, tab_summary, tab_columns = st.tabs(["誘몃━蹂닿린", "?붿빟", "而щ읆"])
    with tab_preview:
        st.dataframe(report_df.head(limit), use_container_width=True)
        if "醫낇빀?먯닔" in report_df.columns:
            st.line_chart(pd.to_numeric(report_df["醫낇빀?먯닔"], errors="coerce"))
    with tab_summary:
        st.json(summary)
        if "寃고빀?≪뀡" in report_df.columns:
            st.bar_chart(report_df["寃고빀?≪뀡"].value_counts())
    with tab_columns:
        st.write(list(report_df.columns))
        st.write(f"???? {len(report_df)}")
elif selected_key in {"?듭떖洹쇨굅", "理쒖쥌留ㅼ닔??꾨씪??, "?꾩씪鍮꾧탳", "愿?ъ쥌紐⑹슂??, "吏꾩엯?꾨낫?붿빟", "?좏샇?깃낵?붿빟", "?좏샇諛쒖깮?곸꽭", "醫낅ぉ?좎젙?먮떒蹂댁“", "?좏샇吏?쒓??대뱶", "?곗꽑寃??}:
    st.dataframe(_load_preview(target_path, limit=limit), use_container_width=True)
else:
    st.dataframe(_load_csv(str(target_path)).head(limit), use_container_width=True)

st.divider()

tab_overview, tab_run, tab_reports, tab_ops, tab_files = st.tabs(["媛쒖슂", "?ㅽ뻾", "由ы룷??, "?댁쁺", "?뚯씪紐⑸줉"])

with tab_overview:
    cols = st.columns(4)
    latest_report = _latest_file(REPORT_PATTERNS["?곸꽭由ы룷??])
    latest_run = _latest_file(REPORT_PATTERNS["?고엳?ㅽ넗由?])
    latest_error = _latest_file(REPORT_PATTERNS["?먮윭濡쒓렇"])
    latest_model = _latest_file(REPORT_PATTERNS["紐⑤뜽?덉??ㅽ듃由?])
    cols[0].metric("蹂닿퀬??, default_date or "-", help=str(latest_report) if latest_report else "")
    cols[1].metric("?ㅽ뻾 ?대젰", "ON" if latest_run else "OFF")
    cols[2].metric("?ㅻ쪟 濡쒓렇", "ON" if latest_error else "OFF")
    cols[3].metric("紐⑤뜽 ?덉??ㅽ듃由?, "ON" if latest_model else "OFF")

    if latest_report:
        report_df = _load_csv(str(latest_report))
        summary = _summarize_report(report_df)
        _render_metric_grid(summary)
        st.dataframe(report_df.head(limit), use_container_width=True)
    else:
        st.info("?곸꽭由ы룷?멸? ?놁뒿?덈떎.")

with tab_run:
    st.subheader("?ㅽ뻾 諛⑹떇")
    if PUBLIC_VIEW_ONLY_MODE:
        st.caption("怨듭슜?깆? 議고쉶 ?꾩슜?대떎. ?앹꽦? GitHub Actions媛 ?섑뻾?섍퀬, 寃곌낵??Google Drive????λ맂??")
        st.info(
            "???붾㈃?먯꽌???뚯씪 ?앹꽦?대굹 ?먭꺽 ?ㅽ뻾???섏? ?딅뒗?? GitHub Actions??GitHub ??μ냼?먯꽌 ?ㅽ뻾?섍퀬, "
            "???깆? Drive????λ맂 CSV留??쎌뼱??蹂댁뿬以??"
        )
        st.markdown(
            "- ?쇱씪 ?앹꽦: GitHub Actions `auto-sync.yml`\n"
            "- 怨쇨굅 ?앹꽦: GitHub Actions `backfill_5y.yml`\n"
            "- 議고쉶: Google Drive????λ맂 CSV瑜????깆뿉???쎄린"
        )
    else:
        st.caption("???붾㈃? 濡쒖뺄 Streamlit?먯꽌 Python ?ㅽ겕由쏀듃瑜?吏곸젒 ?ㅽ뻾?쒕떎. GitHub 諛섏쁺? ?숆린??踰꾪듉?쇰줈 ?섑뻾?쒕떎.")

        col_daily, col_sync = st.columns(2)
        with col_daily:
            st.markdown("#### ?쇱씪 ?ㅽ뻾")
            st.write("`run_pipeline.py daily`瑜??꾩옱 ?뚰겕?ㅽ럹?댁뒪?먯꽌 ?ㅽ뻾?쒕떎.")
            if st.button("?쇱씪 ?ㅽ뻾 ?쒖옉", type="primary", key="run_daily_button"):
                with st.spinner("?쇱씪 ?뚯씠?꾨씪???ㅽ뻾 以?.."):
                    exit_code, output = _run_local_command([sys.executable, str(PYTHON_DIR / "run_pipeline.py"), "daily"])
                st.session_state["last_daily_run"] = {"exit_code": exit_code, "output": output}

            daily_result = st.session_state.get("last_daily_run")
            if daily_result:
                if daily_result["exit_code"] == 0:
                    st.success("?쇱씪 ?ㅽ뻾 ?꾨즺")
                else:
                    st.error(f"?쇱씪 ?ㅽ뻾 ?ㅽ뙣: exit code {daily_result['exit_code']}")
                st.code(daily_result["output"], language="text")

        with col_sync:
            st.markdown("#### GitHub ?뚯뒪 諛섏쁺")
            st.write("`sync_github.ps1`瑜??듯빐 ?꾩옱 蹂寃쎈텇??GitHub濡?push ?쒕떎.")
            if st.button("GitHub 諛섏쁺 ?쒖옉", key="run_sync_button"):
                with st.spinner("GitHub 諛섏쁺 以?.."):
                    exit_code, output = _run_local_command([sys.executable, str(PYTHON_DIR / "ops_admin.py"), "sync-github"])
                st.session_state["last_github_sync"] = {"exit_code": exit_code, "output": output}

            sync_result = st.session_state.get("last_github_sync")
            if sync_result:
                if sync_result["exit_code"] == 0:
                    st.success("GitHub 諛섏쁺 ?꾨즺")
                else:
                    st.warning(f"GitHub 諛섏쁺 ?ㅽ뙣: exit code {sync_result['exit_code']}")
                st.code(sync_result["output"], language="text")

    st.divider()
    if not PUBLIC_VIEW_ONLY_MODE:
        st.markdown("#### GitHub Actions ?ㅽ뻾")
        st.caption("?먭꺽 ??μ냼?먯꽌 workflow_dispatch瑜??몄텧?쒕떎. ?ㅽ뻾?먮뒗 `GITHUB_TOKEN` ?먮뒗 `GH_TOKEN`???꾩슂?섎떎.")

        workflow_key = st.selectbox(
            "?뚰겕?뚮줈??,
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

        if st.button("GitHub Actions ?ㅽ뻾", key="run_github_dispatch_button"):
            command = [
                sys.executable,
                str(PYTHON_DIR / "ops_admin.py"),
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
            with st.spinner("GitHub Actions dispatch 以?.."):
                exit_code, output = _run_local_command(command)
            st.session_state["last_github_dispatch"] = {"exit_code": exit_code, "output": output}

        dispatch_result = st.session_state.get("last_github_dispatch")
        if dispatch_result:
            if dispatch_result["exit_code"] == 0:
                st.success("GitHub Actions ?ㅽ뻾 ?붿껌 ?꾨즺")
            else:
                st.error(f"GitHub Actions ?ㅽ뻾 ?붿껌 ?ㅽ뙣: exit code {dispatch_result['exit_code']}")
            st.code(dispatch_result["output"], language="text")

        st.divider()

        st.markdown("#### 諛깊븘 ?ㅽ뻾")
        backfill_cols = st.columns(4)
        with backfill_cols[0]:
            backfill_days = st.number_input("max days", min_value=1, max_value=365, value=5, step=1)
        with backfill_cols[1]:
            backfill_limit = st.number_input("limit", min_value=0, max_value=2000, value=1, step=1)
        with backfill_cols[2]:
            backfill_force = st.checkbox("force", value=False)
        with backfill_cols[3]:
            backfill_stop_on_error = st.checkbox("stop on error", value=True)

        if st.button("諛깊븘 ?쒖옉", key="run_backfill_button"):
            command = [sys.executable, str(PYTHON_DIR / "history_backfill.py"), "--max-days", str(int(backfill_days))]
            if int(backfill_limit) > 0:
                command.extend(["--limit", str(int(backfill_limit))])
            if backfill_force:
                command.append("--force")
            if backfill_stop_on_error:
                command.append("--stop-on-error")
            with st.spinner("諛깊븘 ?ㅽ뻾 以?.."):
                exit_code, output = _run_local_command(command)
            st.session_state["last_backfill_run"] = {"exit_code": exit_code, "output": output}

        backfill_result = st.session_state.get("last_backfill_run")
        if backfill_result:
            if backfill_result["exit_code"] == 0:
                st.success("諛깊븘 ?ㅽ뻾 ?꾨즺")
            else:
                st.error(f"諛깊븘 ?ㅽ뻾 ?ㅽ뙣: exit code {backfill_result['exit_code']}")
            st.code(backfill_result["output"], language="text")

with tab_reports:
    report_cards = [
        ("?곸꽭由ы룷??, REPORT_PATTERNS["?곸꽭由ы룷??]),
        ("?듭떖洹쇨굅", REPORT_PATTERNS["?듭떖洹쇨굅"]),
        ("理쒖쥌留ㅼ닔??꾨씪??, REPORT_PATTERNS["理쒖쥌留ㅼ닔??꾨씪??]),
        ("?꾩씪鍮꾧탳", REPORT_PATTERNS["?꾩씪鍮꾧탳"]),
        ("?좏샇?깃낵?붿빟", REPORT_PATTERNS["?좏샇?깃낵?붿빟"]),
    ]
    for title, pattern_name in report_cards:
        _render_file_preview(title, _resolve_file(pattern_name, resolved_date), limit=limit)

with tab_ops:
    run_history = _latest_file(REPORT_PATTERNS["?고엳?ㅽ넗由?])
    error_log = _latest_file(REPORT_PATTERNS["?먮윭濡쒓렇"])
    publish_history = _latest_file(REPORT_PATTERNS["?쇰툝由ъ떆?덉뒪?좊━"])
    backfill_history = _latest_file(REPORT_PATTERNS["諛깊븘?덉뒪?좊━"])
    model_registry = _latest_file(REPORT_PATTERNS["紐⑤뜽?덉??ㅽ듃由?])
    feature_importance = _latest_file(REPORT_PATTERNS["?쇱쿂以묒슂??])

    st.subheader("?ㅽ뻾/?ㅻ쪟/諛고룷")
    st.columns(2)
    _render_file_preview("?ㅽ뻾 ?대젰", run_history, limit=limit)
    _render_file_preview("?ㅻ쪟 濡쒓렇", error_log, limit=limit)
    _render_file_preview("諛고룷 ?대젰", publish_history, limit=limit)
    _render_file_preview("諛깊븘 ?대젰", backfill_history, limit=limit)
    _render_file_preview("紐⑤뜽 ?덉??ㅽ듃由?, model_registry, limit=limit)
    _render_file_preview("?쇱쿂 以묒슂??, feature_importance, limit=limit)

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
        selected_download_name = st.selectbox("?ㅼ슫濡쒕뱶???뚯씪", [path.name for path in output_files], key="file_download_select")
        selected_download_path = next((path for path in output_files if path.name == selected_download_name), None)
        if selected_download_path is not None:
            st.download_button(
                label="?좏깮 ?뚯씪 ?ㅼ슫濡쒕뱶",
                data=selected_download_path.read_bytes(),
                file_name=selected_download_path.name,
                mime="text/csv",
                key=f"download_file_list_{selected_download_path.name}",
            )
    else:
        st.info("output ?대뜑??CSV媛 ?놁뒿?덈떎.")

