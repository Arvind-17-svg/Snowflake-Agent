"""Simple UI for the Snowflake agent.

Run from the project root:  streamlit run streamlit_app.py

The agent is defined in the notebook, so this app executes the notebook's code cells
(skipping the example ask() cell) instead of keeping a second copy of the code.
"""

import json
import time
from pathlib import Path

import pandas as pd
import streamlit as st

NOTEBOOK = Path(__file__).parent / "src/snowflake_agent/Notebooks/Snowflake_Agent.ipynb"

NODE_LABELS = {
    "select_tables": "Picking relevant tables",
    "describe": "Reading table columns",
    "generate_sql": "Writing SQL",
    "validate": "Compiling with EXPLAIN (no warehouse cost)",
    "optimize_sql": "Checking for cost optimizations",
    "execute": "Running query on Snowflake",
    "write_answer": "Writing answer",
    "fail": "Stopped",
}

SAMPLE_QUESTIONS = [
    "Which 5 countries had the highest life expectancy for both sexes in the most recent year?",
    "In the TPC-H SF100 sample data, what was total revenue (extended price * (1 - discount)) by ship mode in 1995?",
    "How many Tesla cars were sold in Norway last month?",
]


@st.cache_resource(show_spinner="Loading agent from notebook...")
def load_agent() -> dict:
    nb = json.loads(NOTEBOOK.read_text())
    namespace: dict = {}
    for cell in nb["cells"]:
        src = "".join(cell["source"])
        # skip markdown, empty cells and cells that run the agent on import
        if cell["cell_type"] != "code" or not src.strip() or src.lstrip().startswith("state = ask("):
            continue
        exec(compile(src, f"notebook cell {cell.get('id')}", "exec"), namespace)
    return namespace


def escape_md(text: str) -> str:
    # Streamlit renders $...$ as LaTeX, which mangles currency amounts
    return text.replace("$", r"\$")


def run_agent(agent: dict, question: str, status) -> tuple[dict, list[dict]]:
    state: dict = {"question": question, "attempts": 0}
    steps = []
    start = time.time()
    try:
        for update in agent["graph"].stream(state, {"recursion_limit": 30}, stream_mode="updates"):
            for node, changes in update.items():
                changes = changes or {}
                state.update(changes)
                note = changes.get("error") or changes.get("last_error")
                if node == "generate_sql":
                    note = f"attempt {changes.get('attempts')}"
                elif node == "optimize_sql":
                    note = changes.get("optimization", {}).get("status")
                steps.append({"elapsed_s": round(time.time() - start, 1), "step": node,
                              "label": NODE_LABELS.get(node, node), "note": note or ""})
                icon = "⚠️" if changes.get("last_error") else ("❌" if changes.get("error") else "✅")
                status.write(f"{icon} **{NODE_LABELS.get(node, node)}** · {steps[-1]['elapsed_s']}s"
                             + (f" — {str(note)[:200]}" if note else ""))
    except agent["GraphRecursionError"]:
        state["answer"] = "Sorry, the agent got stuck in a loop and was stopped."
        state["error"] = state["answer"]
    except Exception as e:  # anything the nodes didn't catch
        state["answer"] = f"Sorry, something went wrong: {type(e).__name__}: {e}"
        state["error"] = state["answer"]
    return state, steps


def render_result(state: dict, steps: list[dict]) -> None:
    failed = bool(state.get("error")) or state.get("answer", "").startswith("Sorry")
    (st.error if failed else st.markdown)(escape_md(state.get("answer", "(no answer)")))

    tabs = st.tabs(["Result", "SQL", "Optimization", "Trace"])

    with tabs[0]:
        result = state.get("result")
        if result and result.get("rows"):
            st.dataframe(pd.DataFrame(result["rows"]), use_container_width=True, hide_index=True)
            st.caption(f"{result['row_count']} rows" + (" (truncated)" if result.get("truncated") else "")
                       + f" · query id {result.get('query_id')}")
        else:
            st.caption("No rows.")

    with tabs[1]:
        if state.get("sql"):
            st.code(state["sql"], language="sql")
            if state.get("explanation"):
                st.caption(state["explanation"])
            if state.get("tables"):
                st.caption("Tables: " + ", ".join(state["tables"]))
        else:
            st.caption("No SQL was generated.")

    with tabs[2]:
        plan = state.get("plan")
        if plan:
            c1, c2, c3 = st.columns(3)
            c1.metric("GB scanned", plan.get("gb_scanned"))
            c2.metric("Partitions pruned", f"{plan['pruning_pct']}%" if plan.get("pruning_pct") is not None else "n/a")
            c3.metric("Partitions read", f"{plan.get('partitions_assigned')} / {plan.get('partitions_total')}")
        opt = state.get("optimization") or {}
        if opt:
            st.write(f"**Rewrite:** {opt.get('status')} — {opt.get('reason') or opt.get('changes') or ''}")
            if opt.get("status") == "applied" and opt.get("original_sql"):
                with st.expander("Original SQL (before rewrite)"):
                    st.code(opt["original_sql"], language="sql")
        findings = state.get("findings") or []
        if findings:
            st.dataframe(pd.DataFrame(findings)[["severity", "rule", "detail", "suggestion"]],
                         use_container_width=True, hide_index=True)
        elif plan:
            st.caption("No findings.")
        if not plan and not opt:
            st.caption("The query didn't reach the optimization step.")

    with tabs[3]:
        if steps:
            st.dataframe(pd.DataFrame(steps)[["elapsed_s", "label", "note"]], use_container_width=True, hide_index=True)
        st.caption(f"SQL attempts: {state.get('attempts', 0)}")


st.set_page_config(page_title="Snowflake Agent", page_icon="❄️", layout="wide")
st.title("❄️ Snowflake Agent")
st.caption("Ask a question in plain English. The agent picks tables, writes SQL, checks it with EXPLAIN, "
           "optimizes it for cost, runs it, and explains the result.")

try:
    agent = load_agent()
except Exception as e:
    st.error(f"Couldn't load the agent from the notebook: {type(e).__name__}: {e}")
    st.stop()

with st.sidebar:
    st.subheader("Settings")
    st.write(f"**Model:** `{agent['GROQ_MODEL']}`")
    st.write(f"**Fallback:** `{agent['GROQ_FALLBACK_MODEL']}`")
    st.write(f"**Max SQL attempts:** {agent['MAX_SQL_ATTEMPTS']}")

    if st.button("Test Snowflake connection", use_container_width=True):
        with st.spinner("Connecting..."):
            r = agent["query"].invoke({"sql": "SELECT CURRENT_USER() AS user_name, CURRENT_ROLE() AS role, "
                                              "CURRENT_WAREHOUSE() AS warehouse"})
        if "error" in r:
            st.error(r["error"])
        else:
            st.success("Connected")
            st.json(r["rows"][0])

    if st.button("Reload agent code from notebook", use_container_width=True):
        load_agent.clear()
        st.rerun()

    if st.button("Clear chat", use_container_width=True):
        st.session_state.history = []
        st.rerun()

    st.subheader("Try")
    for q in SAMPLE_QUESTIONS:
        if st.button(q, use_container_width=True):
            st.session_state.pending = q

st.session_state.setdefault("history", [])

for item in st.session_state.history:
    with st.chat_message("user"):
        st.write(item["question"])
    with st.chat_message("assistant"):
        render_result(item["state"], item["steps"])

question = st.chat_input("Ask about your Snowflake data...") or st.session_state.pop("pending", None)
if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.status("Working...", expanded=True) as status:
            state, steps = run_agent(agent, question, status)
            total = steps[-1]["elapsed_s"] if steps else 0
            status.update(label=f"Done in {total}s", state="error" if state.get("error") else "complete",
                          expanded=False)
        render_result(state, steps)
    st.session_state.history.append({"question": question, "state": state, "steps": steps})
