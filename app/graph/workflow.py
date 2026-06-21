from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.graph.state import AgentState
from app.nodes import build_nodes
from app.services.container import WorkflowServices, build_services

NODE_ORDER = [
    "receive_incident",
    "search_parcle",
    "classify_request",
    "return_information",
    "analyze_incident",
    "generate_enterpro_prompt",
    "preflight_git_push",
    "create_git_branch",
    "execute_enterpro",
    "validate_changes",
    "repair_validation",
    "update_decision_log",
    "sync_decision_to_parcle",
    "commit_changes",
    "push_branch",
    "create_pull_request",
    "return_summary",
]

CODE_CHANGE_ORDER = [
    "analyze_incident",
    "generate_enterpro_prompt",
    "preflight_git_push",
    "create_git_branch",
    "execute_enterpro",
    "validate_changes",
    "repair_validation",
    "update_decision_log",
    "sync_decision_to_parcle",
    "commit_changes",
    "push_branch",
    "create_pull_request",
    "return_summary",
]


def route_request(state: AgentState) -> str:
    return "code_change" if state.get("request_kind") == "code_change" else "information"


def create_graph(services: WorkflowServices | None = None):
    nodes = build_nodes(services or build_services())
    builder = StateGraph(AgentState)
    for name in NODE_ORDER:
        builder.add_node(name, nodes[name])
    builder.set_entry_point(NODE_ORDER[0])
    builder.add_edge("receive_incident", "search_parcle")
    builder.add_edge("search_parcle", "classify_request")
    builder.add_conditional_edges(
        "classify_request",
        route_request,
        {
            "information": "return_information",
            "code_change": CODE_CHANGE_ORDER[0],
        },
    )
    builder.add_edge("return_information", END)
    for source, destination in zip(CODE_CHANGE_ORDER, CODE_CHANGE_ORDER[1:]):
        builder.add_edge(source, destination)
    builder.add_edge(CODE_CHANGE_ORDER[-1], END)
    return builder.compile()


graph = create_graph()
