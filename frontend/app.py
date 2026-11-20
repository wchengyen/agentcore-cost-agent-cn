"""Streamlit UI for the deployed AWS China Cost Analysis Agent."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import streamlit as st

from backend import FrontendError, RuntimeClient, build_prompt

st.set_page_config(page_title="AWS 成本分析 Agent", page_icon="¥", layout="wide")

QUICK_PROMPTS = {
    "上月 Top 5 服務及環比": "上個月成本 Top 5 服務及環比。",
    "本月至今成本與預測": "分析本月至今成本，並提供本月剩餘期間與整月成本預測。",
    "RI·SP 覆蓋率與使用率": "分析上個完整月的 RI 與 Savings Plans 覆蓋率及使用率。",
    "最近 30 天成本異常": "查詢最近 30 天成本異常，只報告工具證實的異常。",
    "指定服務按 USAGE_TYPE 拆分": "請將我指定的服務按 USAGE_TYPE 拆分並列出 Top 5；若未指定服務，先詢問服務名稱。",
}


def new_session_id() -> str:
    return "ui-" + uuid.uuid4().hex


if "sessions" not in st.session_state:
    st.session_state.sessions = {}
if "session_id" not in st.session_state:
    st.session_state.session_id = new_session_id()
if st.session_state.session_id not in st.session_state.sessions:
    st.session_state.sessions[st.session_state.session_id] = []

st.title("AWS 中國區成本分析 Agent")
st.caption("結果只報告工具證實的事實變化；任何原因假設均標記為「待確認」。")

with st.sidebar:
    st.subheader("會話")
    session_ids = list(st.session_state.sessions)
    selected_session = st.selectbox(
        "歷史會話",
        session_ids,
        index=session_ids.index(st.session_state.session_id),
    )
    if selected_session != st.session_state.session_id:
        st.session_state.session_id = selected_session
        st.rerun()
    st.code(st.session_state.session_id)
    if st.button("新會話", use_container_width=True):
        st.session_state.session_id = new_session_id()
        st.session_state.sessions.setdefault(st.session_state.session_id, [])
        st.rerun()
    use_range = st.checkbox("加入指定日期與分組")
    start_value = date.today() - timedelta(days=30)
    end_value = date.today()
    group_by = None
    if use_range:
        start_value = st.date_input("開始日期（包含）", start_value)
        end_value = st.date_input("結束日期（不包含）", end_value)
        group_by = st.selectbox("Group by", ["SERVICE", "USAGE_TYPE", "REGION", "LINKED_ACCOUNT", "TAG:<key>"])

st.subheader("快速問題")
columns = st.columns(3)
selected_prompt = None
for index, (label, prompt) in enumerate(QUICK_PROMPTS.items()):
    if columns[index % 3].button(label, use_container_width=True):
        selected_prompt = prompt

history = st.session_state.sessions[st.session_state.session_id]
for item in history:
    with st.chat_message(item["role"]):
        st.markdown(item["content"])
        if item["role"] == "assistant":
            details = []
            if item.get("latency_seconds") is not None:
                details.append(f"耗時 {item['latency_seconds']:.3f}s")
            if item.get("tool_calls"):
                details.append("工具：" + ", ".join(f"{name} ×{count}" for name, count in item["tool_calls"].items()))
            if item.get("models_returned"):
                details.append("模型：" + ", ".join(item["models_returned"]))
            if details:
                st.caption(" | ".join(details))

chat_prompt = st.chat_input("輸入成本分析問題")
prompt = selected_prompt or chat_prompt
if prompt:
    final_prompt = build_prompt(
        prompt,
        start_value.isoformat() if use_range else None,
        end_value.isoformat() if use_range else None,
        group_by if use_range else None,
    )
    history.append({"role": "user", "content": final_prompt})
    with st.chat_message("user"):
        st.markdown(final_prompt)
    with st.chat_message("assistant"):
        with st.spinner("正在分析，可能需要數分鐘……"):
            try:
                response = RuntimeClient().invoke(final_prompt, st.session_state.session_id)
                answer = response.get("result", "Runtime 未返回文字結果。")
                st.markdown(answer)
                tool_calls = response.get("tool_calls", {})
                models = response.get("models_returned", [])
                latency = response["latency_seconds"]
                st.caption(
                    f"耗時 {latency:.3f}s | 工具：" +
                    (", ".join(f"{name} ×{count}" for name, count in tool_calls.items()) or "無") +
                    (" | 模型：" + ", ".join(models) if models else "")
                )
                history.append({
                    "role": "assistant",
                    "content": answer,
                    "latency_seconds": latency,
                    "tool_calls": tool_calls,
                    "models_returned": models,
                })
            except FrontendError as exc:
                st.error(str(exc))
