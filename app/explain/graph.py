"""LangGraph explanation agent:

    load_score_payload -> draft_explanation -> grounding_check -> format_response

The detector has already decided the score; this graph only turns it into prose. If no LLM is
configured, the LLM errors, or its text fails the grounding check, the deterministic template
is used instead. The path taken ("llm" or "fallback") is logged and returned.
"""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.constants import DISCLAIMER
from app.core.logging import get_logger
from app.explain.grounding import check_grounding
from app.explain.llm import SYSTEM_PROMPT, LLMClient, build_user_prompt
from app.explain.payload import REQUIRED_KEYS
from app.explain.templates import template_explanation

log = get_logger(__name__)


class ExplainState(TypedDict, total=False):
    payload: dict[str, Any]
    draft: str | None
    llm_error: str | None
    text: str
    path: str
    problems: list[str]
    explanation: str
    disclaimer: str


def build_explain_graph(llm: LLMClient | None = None) -> Any:
    def load_score_payload(state: ExplainState) -> ExplainState:
        payload = state["payload"]
        missing = [k for k in REQUIRED_KEYS if k not in payload]
        if missing:
            raise ValueError(f"score payload missing keys: {missing}")
        return {"payload": payload}

    def draft_explanation(state: ExplainState) -> ExplainState:
        if llm is None:
            return {"draft": None, "llm_error": "no LLM configured"}
        try:
            return {
                "draft": llm.complete(SYSTEM_PROMPT, build_user_prompt(state["payload"])),
                "llm_error": None,
            }
        except Exception as exc:  # network, quota, parsing...
            return {"draft": None, "llm_error": str(exc)[:300]}

    def grounding_check(state: ExplainState) -> ExplainState:
        draft = state.get("draft")
        if draft:
            result = check_grounding(draft, state["payload"])
            if result.ok:
                return {"text": draft, "path": "llm", "problems": []}
            problems = result.problems
        else:
            problems = [state.get("llm_error") or "empty draft"]
        return {
            "text": template_explanation(state["payload"]),
            "path": "fallback",
            "problems": problems,
        }

    def format_response(state: ExplainState) -> ExplainState:
        log.info(
            "explanation generated",
            extra={
                "path": state["path"],
                "symbol": state["payload"]["symbol"],
                "problems": state["problems"],
            },
        )
        return {"explanation": f"{state['text']}\n\n{DISCLAIMER}", "disclaimer": DISCLAIMER}

    graph = StateGraph(ExplainState)
    graph.add_node("load_score_payload", load_score_payload)
    graph.add_node("draft_explanation", draft_explanation)
    graph.add_node("grounding_check", grounding_check)
    graph.add_node("format_response", format_response)
    graph.add_edge(START, "load_score_payload")
    graph.add_edge("load_score_payload", "draft_explanation")
    graph.add_edge("draft_explanation", "grounding_check")
    graph.add_edge("grounding_check", "format_response")
    graph.add_edge("format_response", END)
    return graph.compile()


def explain(payload: dict[str, Any], llm: LLMClient | None = None) -> dict[str, Any]:
    state = build_explain_graph(llm).invoke({"payload": payload})
    return {
        "text": state["text"],
        "explanation": state["explanation"],
        "path": state["path"],
        "problems": state["problems"],
        "disclaimer": state["disclaimer"],
    }
