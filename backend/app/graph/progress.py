"""Progress events for the live progress strip (later streamed over SSE)."""


def emit(step: str, status: str, message: str, done: int | None = None, total: int | None = None) -> dict:
    """Send one progress event to whoever is streaming the graph.

    step:   parse | search | extract | filter | rank
    status: running | done | failed
    Outside a running graph (plain unit tests) there is no stream writer, so this does nothing.
    """
    event = {"step": step, "status": status, "message": message, "done": done, "total": total}
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(event)
    except Exception:  # no langgraph, or not inside a graph run
        pass
    return event
