"""Full graph run. Skipped automatically if LangGraph is not installed."""
import pytest

pytest.importorskip("langgraph")

from app.graph.build import build_graph  # noqa: E402


def run(raw, device="camera"):
    graph = build_graph()
    config = {"configurable": {"thread_id": "t1"}}
    events = [chunk[-1] for chunk in graph.stream(
        {"search_id": "t1", "device_type": device, "raw_criteria": raw},
        config, stream_mode=["custom"], subgraphs=True,
    )]
    return graph.get_state(config).values, events


def test_camera_search_end_to_end():
    state, events = run({"budget_max": 20000})
    assert state["error"] is None
    assert len(state["ranked"]) >= 5
    assert {e["step"] for e in events} >= {"parse", "search", "extract", "filter", "rank"}


def test_bad_input_stops_with_error():
    state, events = run({"shutter": {"value": "electronic"}})
    assert state["error"]
    assert not state.get("ranked")
    assert events[-1]["status"] == "failed"


def test_unsupported_device_stops_with_error():
    state, _ = run({}, device="plc")
    assert "not supported" in state["error"]
