"""Polished local Streamlit UI for the AWS China Cost Analysis Agent."""
from __future__ import annotations

import base64
import html
import json
import os
import uuid
from datetime import date, datetime, timedelta

import streamlit as st
import streamlit.components.v1 as components

from backend import FrontendError, RuntimeClient, build_prompt
from history import HistoryStore

st.set_page_config(page_title="Cost Agent · AWS 中國區", layout="wide", initial_sidebar_state="expanded")

ACCENT = "#0e7c66"
NAVY = "#10233f"
CURRENT_MODEL = os.getenv("COST_AGENT_CURRENT_MODEL", "glm-5.3-flash")
QUICK_PROMPTS = {
    "上月 Top 5 服務及環比": "上個月成本 Top 5 服務及環比。",
    "本月至今成本與預測": "分析本月至今成本，並提供本月剩餘期間與整月成本預測。",
    "RI·SP 覆蓋率與使用率": "分析上個完整月的 RI 與 Savings Plans 覆蓋率及使用率。",
    "最近 30 天成本異常": "查詢最近 30 天成本異常，只報告工具證實的異常。",
    "指定服務按 USAGE_TYPE 拆分": "請將我指定的服務按 USAGE_TYPE 拆分並列出 Top 5；若未指定服務，先詢問服務名稱。",
}

st.markdown(
    f"""
<style>
html, body, [class*="css"] {{ font-family: "IBM Plex Sans", "Noto Sans TC", "Microsoft JhengHei", "PingFang TC", system-ui, sans-serif; color: {NAVY}; }}
.stApp {{ background: #f6f7f9; }}
.block-container {{ max-width: 1160px; padding-top: 1.35rem; padding-bottom: 2rem; }}
[data-testid="stSidebar"] {{ background: #ffffff; border-right: 1px solid #d9dee5; }}
[data-testid="stSidebar"] .block-container {{ padding-top: 1rem; }}
h1, h2, h3 {{ color: {NAVY}; letter-spacing: -0.015em; }}
h1 {{ margin-bottom: .15rem; }}
.status-line {{ border: 1px solid #d9dee5; background: #fff; padding: .55rem .75rem; margin: .35rem 0 1rem; font-size: .84rem; color: #4d596b; }}
.status-ok {{ color: {ACCENT}; font-weight: 650; }}
.notice {{ border-left: 3px solid {ACCENT}; padding: .55rem .7rem; background: #edf6f3; color: #334155; font-size: .82rem; margin: .75rem 0; }}
.stButton > button {{ border-radius: 999px; border: 1px solid #cbd5df; background: #fff; color: {NAVY}; padding: .28rem .75rem; min-height: 2.1rem; }}
.stButton > button:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
[data-testid="stChatMessage"] {{ background: #fff; border: 1px solid #e0e5eb; border-radius: 6px; padding: .15rem .5rem; margin-bottom: .55rem; }}
[data-testid^="stChatMessageAvatar"] {{ display: none; }}
[data-testid="stToolbar"], #MainMenu, footer {{ visibility: hidden; }}
.meta-row {{ display:flex; flex-wrap:wrap; gap:.3rem; margin:.25rem 0 .1rem; }}
.meta-chip {{ display:inline-block; border:1px solid #d5dce4; border-radius:999px; padding:.08rem .48rem; background:#f8fafb; color:#536174; font-size:.72rem; }}
.session-fact {{ color:#687386; font-size:.72rem; line-height:1.3; margin:-.25rem 0 .35rem .15rem; }}
.old-model {{ color:#8a5a00; border:1px solid #dfc48b; border-radius:999px; padding:0 .35rem; font-size:.65rem; }}
.stMarkdown table {{ display:block; overflow-x:auto; white-space:nowrap; width:100%; border-collapse:collapse; }}
.stMarkdown th {{ background:#eef2f5; color:{NAVY}; }}
.stMarkdown th, .stMarkdown td {{ padding:.35rem .55rem !important; border-bottom:1px solid #dfe4ea !important; }}
hr {{ margin:.7rem 0; }}
</style>
""",
    unsafe_allow_html=True,
)


def new_session_id() -> str:
    return "ui-" + uuid.uuid4().hex


def parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min


def grouped_sessions(sessions: list[dict]) -> dict[str, list[dict]]:
    today = date.today()
    groups = {"今天": [], "昨天": [], "更早": []}
    for session in sessions:
        updated = parse_time(session.get("updated_at", "")).date()
        key = "今天" if updated == today else "昨天" if updated == today - timedelta(days=1) else "更早"
        groups[key].append(session)
    return groups


def short_tool_name(name: str) -> str:
    return name.split("___", 1)[-1]


def scrub(text: str, account_id: str | None) -> str:
    if os.getenv("COST_AGENT_MASK_ACCOUNT") == "1" and account_id:
        return text.replace(account_id, "<ACCOUNT_ID>")
    return text


def meta_html(turn: dict) -> str:
    chips = []
    if turn.get("latency") is not None:
        chips.append(f"耗時 {float(turn['latency']):.3f}s")
    for name, count in turn.get("tool_counts", {}).items():
        chips.append(f"{short_tool_name(name)} ×{count}")
    if turn.get("model"):
        chips.append(str(turn["model"]))
    return '<div class="meta-row">' + "".join(
        f'<span class="meta-chip">{html.escape(chip)}</span>' for chip in chips
    ) + "</div>"


def copy_button(text: str, key: str) -> None:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    button_id = html.escape(key)
    components.html(
        f"""<button id="{button_id}" style="border:1px solid #cbd5df;background:#fff;color:#10233f;border-radius:4px;padding:4px 10px;font:12px system-ui;cursor:pointer">複製答案</button>
<script>
const bytes = Uint8Array.from(atob("{encoded}"), c => c.charCodeAt(0));
const answer = new TextDecoder("utf-8").decode(bytes);
document.getElementById("{button_id}").addEventListener("click", function() {{
  navigator.clipboard.writeText(answer).then(() => this.textContent = "已複製");
}});
</script>""",
        height=34,
    )


def conversation_markdown(session: dict, account_id: str | None) -> str:
    lines = [f"# {session.get('summary', {}).get('title', 'Cost Agent 對話')}", ""]
    for turn in session.get("turns", []):
        lines.extend(["## 使用者", scrub(turn["prompt"], account_id), "", "## Cost Agent", scrub(turn["answer"], account_id), ""])
    return "\n".join(lines)


@st.cache_data(ttl=60, show_spinner=False)
def cached_runtime_status() -> dict:
    return RuntimeClient().status()


store = HistoryStore()
sessions = store.list_sessions()
if "active_session_id" not in st.session_state:
    st.session_state.active_session_id = sessions[0]["session_id"] if sessions else new_session_id()
store.ensure_session(st.session_state.active_session_id)
sessions = store.list_sessions()
session_map = {session["session_id"]: session for session in sessions}
if st.session_state.active_session_id not in session_map:
    st.session_state.active_session_id = sessions[0]["session_id"] if sessions else new_session_id()
    store.ensure_session(st.session_state.active_session_id)
    sessions = store.list_sessions()
    session_map = {session["session_id"]: session for session in sessions}
active = session_map[st.session_state.active_session_id]

status_error = None
try:
    status = cached_runtime_status()
except Exception as exc:
    status = {"account_id": None, "region": "cn-north-1", "runtime_status": "UNKNOWN", "runtime_version": "?"}
    status_error = f"狀態查詢失敗（{type(exc).__name__}）"
account_id = status.get("account_id")
display_account = "<ACCOUNT_ID>" if os.getenv("COST_AGENT_MASK_ACCOUNT") == "1" else account_id or "未知"
returned_model = active.get("model") or "尚未回傳"

st.title("Cost Agent · AWS 中國區")
status_class = "status-ok" if status.get("runtime_status") == "READY" else ""
st.markdown(
    f'<div class="status-line">帳號 {html.escape(str(display_account))} &nbsp;·&nbsp; 區域 {status["region"]} &nbsp;·&nbsp; Runtime v{status["runtime_version"]} <span class="{status_class}">{status["runtime_status"]}</span> &nbsp;·&nbsp; 回傳模型 {html.escape(str(returned_model))}</div>',
    unsafe_allow_html=True,
)
if status_error:
    st.error(status_error)

with st.sidebar:
    st.subheader("對話")
    if st.button("新對話", use_container_width=True, type="primary"):
        session_id = new_session_id()
        store.ensure_session(session_id)
        st.session_state.active_session_id = session_id
        st.rerun()

    for group, items in grouped_sessions(sessions).items():
        if not items:
            continue
        st.caption(group)
        for session in items:
            summary = session.get("summary", {})
            old_model = bool(session.get("model") and session.get("model") != CURRENT_MODEL)
            label = summary.get("title") or "新對話"
            if old_model:
                label += " · 舊模型"
            if st.button(label, key=f"open-{session['session_id']}", use_container_width=True):
                st.session_state.active_session_id = session["session_id"]
                st.rerun()
            facts = summary.get("facts", [])
            time_text = parse_time(session.get("updated_at", "")).astimezone().strftime("%H:%M") if session.get("updated_at") else ""
            fact_text = " · ".join(scrub(fact, account_id) for fact in facts[:2]) or "尚無摘要"
            st.markdown(
                f'<div class="session-fact">{html.escape(fact_text)}<br>{len(session.get("turns", []))} 輪 · {time_text}</div>',
                unsafe_allow_html=True,
            )

    if active.get("model") and active.get("model") != CURRENT_MODEL:
        st.warning(f"此對話建立於舊模型 {active['model']}，不建議繼續；可開新對話。")

    with st.expander("管理目前對話", expanded=False):
        rename_value = st.text_input("名稱", value=active.get("summary", {}).get("title", "新對話"), key=f"rename-{active['session_id']}")
        col_rename, col_delete = st.columns(2)
        if col_rename.button("重新命名", use_container_width=True):
            store.rename(active["session_id"], rename_value)
            st.rerun()
        if col_delete.button("刪除本機記錄", use_container_width=True):
            store.delete(active["session_id"])
            remaining = store.list_sessions()
            next_id = remaining[0]["session_id"] if remaining else new_session_id()
            store.ensure_session(next_id)
            st.session_state.active_session_id = next_id
            st.rerun()
        st.caption("只刪除本機歷史；AgentCore S3 session 不會刪除。")

    st.divider()
    st.subheader("查詢條件")
    use_range = st.checkbox("加入日期與分組")
    start_value = date.today() - timedelta(days=30)
    end_value = date.today()
    group_by = None
    if use_range:
        start_value = st.date_input("開始日期（包含）", start_value)
        end_value = st.date_input("結束日期（不包含）", end_value)
        group_by = st.selectbox("Group by", ["SERVICE", "USAGE_TYPE", "REGION", "LINKED_ACCOUNT", "TAG:<key>"])
    st.markdown('<div class="notice">只陳述事實變化，原因標示為待確認。</div>', unsafe_allow_html=True)

st.subheader("快速問題")
quick_columns = st.columns(len(QUICK_PROMPTS))
selected_prompt = None
for column, (label, quick_prompt) in zip(quick_columns, QUICK_PROMPTS.items()):
    if column.button(label, use_container_width=True):
        selected_prompt = quick_prompt

markdown_download = conversation_markdown(active, account_id)
st.download_button(
    "下載目前對話（Markdown）",
    data=markdown_download.encode("utf-8"),
    file_name=f"cost-agent-{active['session_id']}.md",
    mime="text/markdown",
)

for index, turn in enumerate(active.get("turns", [])):
    with st.chat_message("user"):
        st.markdown(scrub(turn["prompt"], account_id))
    with st.chat_message("assistant"):
        answer = scrub(turn["answer"], account_id)
        st.markdown(answer)
        st.markdown(meta_html(turn), unsafe_allow_html=True)
        copy_button(answer, f"copy-{active['session_id']}-{index}")
        with st.expander("詳細資料", expanded=False):
            st.json({
                "latency_seconds": turn.get("latency"),
                "tool_counts": turn.get("tool_counts", {}),
                "returned_model": turn.get("model"),
                "created_at": turn.get("created_at"),
            })

prompt = selected_prompt or st.chat_input("輸入成本分析問題")
if prompt:
    final_prompt = build_prompt(
        prompt,
        start_value.isoformat() if use_range else None,
        end_value.isoformat() if use_range else None,
        group_by if use_range else None,
    )
    with st.chat_message("user"):
        st.markdown(final_prompt)
    with st.chat_message("assistant"):
        with st.spinner("正在查詢成本資料，已耗時間", show_time=True):
            try:
                response = RuntimeClient().invoke(final_prompt, active["session_id"])
                answer = response.get("result", "Runtime 未返回文字結果。")
                tool_counts = response.get("tool_calls", {})
                models = response.get("models_returned", [])
                model = models[-1] if models else response.get("model_requested")
                store.append_turn(
                    active["session_id"], final_prompt, answer,
                    float(response["latency_seconds"]), tool_counts, model,
                )
                st.rerun()
            except FrontendError as exc:
                st.error(f"無法完成本次查詢：{exc}")
