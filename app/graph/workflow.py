from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.graph.state import AgentState
from app.nodes import build_nodes
from app.services.container import WorkflowServices, build_services

NODE_ORDER = [
    "receive_incident",
    "search_parcle",
    "analyze_incident",
    "generate_enterpro_prompt",
    "create_git_branch",
    "execute_enterpro",
    "validate_changes",
    "update_decision_log",
    "sync_decision_to_parcle",
    "commit_changes",
    "return_summary",
]


def create_graph(services: WorkflowServices | None = None):
    nodes = build_nodes(services or build_services())
    builder = StateGraph(AgentState)
    for name in NODE_ORDER:
        builder.add_node(name, nodes[name])
    builder.set_entry_point(NODE_ORDER[0])
    for source, destination in zip(NODE_ORDER, NODE_ORDER[1:]):
        builder.add_edge(source, destination)
    builder.add_edge(NODE_ORDER[-1], END)
    return builder.compile()


graph = create_graph()
