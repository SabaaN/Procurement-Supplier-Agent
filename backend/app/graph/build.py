"""Wires the nodes into LangGraph graphs.

parse_requirements -> route_device -> <device>_agent (subgraph) -> finalize
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ..devices import DEVICES
from . import nodes
from .state import SearchState


def build_device_subgraph(device_key: str):
    """plan_queries -> search -> fetch_clean -> extract -> filter -> score,
    looping back to plan_queries when too few products survive the filter.

    The nodes read the device from state, so every device reuses them. When a device needs
    its own step (e.g. NVR compatibility for cameras), add a node here for that key only.
    """
    g = StateGraph(SearchState)
    g.add_node("plan_queries", nodes.plan_queries)
    g.add_node("search", nodes.search)
    g.add_node("fetch_clean", nodes.fetch_clean)
    g.add_node("extract", nodes.extract)
    g.add_node("filter", nodes.filter_products)
    g.add_node("score", nodes.score)

    g.add_edge(START, "plan_queries")
    g.add_edge("plan_queries", "search")
    g.add_edge("search", "fetch_clean")
    g.add_edge("fetch_clean", "extract")
    g.add_edge("extract", "filter")
    g.add_conditional_edges("filter", nodes.route_after_filter, {"score": "score", "plan_queries": "plan_queries"})
    g.add_edge("score", END)
    return g.compile()


def build_graph(checkpointer=None):
    g = StateGraph(SearchState)
    g.add_node("parse_requirements", nodes.parse_requirements)
    g.add_node("finalize", nodes.finalize)

    routes = {"error": END}
    for key in DEVICES:
        g.add_node(f"{key}_agent", build_device_subgraph(key))
        g.add_edge(f"{key}_agent", "finalize")
        routes[key] = f"{key}_agent"

    g.add_edge(START, "parse_requirements")
    g.add_conditional_edges("parse_requirements", nodes.route_device, routes)
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())
