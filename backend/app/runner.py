"""Runs one search through the agent graph and records everything in the store."""
import logging
from functools import lru_cache

from .graph.build import build_graph
from .services import store

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _graph():
    return build_graph()  # compiled once; each search uses its own thread_id


def run_search(search_id: str) -> None:
    """Runs in a background thread. Never raises: failures are stored on the search."""
    search = store.get_search(search_id)
    if search is None:
        return
    store.set_status(search_id, "running")
    try:
        graph = _graph()
        config = {"configurable": {"thread_id": search_id}}
        inputs = {
            "search_id": search_id,
            "device_type": search["device_type"],
            "raw_criteria": search["criteria"],
        }
        for *_, event in graph.stream(inputs, config, stream_mode=["custom"], subgraphs=True):
            store.add_event(search_id, event)

        final = graph.get_state(config).values
        store.save_products(search_id, final.get("ranked", []))
        error = final.get("error")
        store.set_status(search_id, "failed" if error else "done", error)
    except Exception as e:
        log.exception("Search %s crashed", search_id)
        message = f"{type(e).__name__}: {e}"
        store.add_event(search_id, {"step": "rank", "status": "failed", "message": message, "done": None, "total": None})
        store.set_status(search_id, "failed", message)