import csv
import io

from fastapi.testclient import TestClient

from app.main import _cell, app
from app.services import store, web_search

client = TestClient(app)  # runs background tasks before returning, so a search is finished after the POST
CRIT = {"budget_max": 20000}


def new_search(criteria=CRIT, device="camera"):
    return client.post("/api/searches", json={"device_type": device, "criteria": criteria})


# ---- devices ----

def test_devices_endpoints():
    devices = {d["key"]: d["enabled"] for d in client.get("/api/devices").json()}
    assert devices == {"camera": True, "sensor": False, "plc": False}
    form = client.get("/api/devices/camera").json()
    assert "min_megapixels" in {f["name"] for f in form["fields"]}
    assert client.get("/api/devices/plc").status_code == 404


# ---- creating a search ----

def test_search_runs_in_the_background_and_results_are_saved():
    r = new_search()
    assert r.status_code == 202
    sid = r.json()["id"]
    assert client.get(f"/api/searches/{sid}").json()["status"] == "done"
    data = client.get(f"/api/searches/{sid}/results").json()
    assert len(data["products"]) >= 5
    assert data["products"][0]["rank"] == 1 and data["products"][0]["explanation"]
    assert data["search"]["product_count"] == len(data["products"])


def test_invalid_criteria_returns_field_errors():
    r = new_search({"shutter": {"value": "electronic"}})
    assert r.status_code == 422
    assert r.json()["detail"][0]["field"].startswith("shutter")


def test_unsupported_device_is_rejected():
    assert new_search(device="plc").status_code == 400


def test_unknown_search_is_404():
    for path in ("", "/results", "/stream", "/export.csv"):
        assert client.get(f"/api/searches/nope{path}").status_code == 404


def test_history_lists_newest_first():
    first = new_search().json()["id"]
    second = new_search().json()["id"]
    ids = [s["id"] for s in client.get("/api/searches").json()]
    assert ids[:2] == [second, first]


# ---- progress stream ----

def test_stream_replays_progress_and_can_resume():
    sid = new_search().json()["id"]
    text = client.get(f"/api/searches/{sid}/stream").text
    assert "event: progress" in text and "event: end" in text and '"status": "done"' in text
    ids = [int(line.split(": ")[1]) for line in text.splitlines() if line.startswith("id: ")]
    assert ids == sorted(ids) and len(ids) > 3

    resumed = client.get(f"/api/searches/{sid}/stream", headers={"Last-Event-ID": str(ids[-1])}).text
    assert "event: progress" not in resumed and "event: end" in resumed


def test_failed_search_is_recorded(monkeypatch):
    def down(query, max_results=None):
        raise web_search.SearchError("TAVILY_API_KEY is not set")

    monkeypatch.setattr(web_search, "search_web", down)
    sid = new_search().json()["id"]
    meta = client.get(f"/api/searches/{sid}").json()
    assert meta["status"] == "failed" and "Search failed" in meta["error"]
    assert '"status": "failed"' in client.get(f"/api/searches/{sid}/stream").text


def test_interrupted_searches_are_failed_on_startup():
    sid = store.create_search("camera", {})
    store.set_status(sid, "running")
    assert store.fail_interrupted() == 1
    assert store.get_search(sid)["status"] == "failed"


# ---- shortlist and CSV ----

def read_csv(text):
    return list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))


def test_shortlist_and_csv_export():
    sid = new_search().json()["id"]
    products = client.get(f"/api/searches/{sid}/results").json()["products"]
    star = products[1]["id"]
    r = client.post(f"/api/searches/{sid}/shortlist", json={"product_id": star, "shortlisted": True})
    assert r.status_code == 200

    everything = read_csv(client.get(f"/api/searches/{sid}/export.csv").text)
    starred = read_csv(client.get(f"/api/searches/{sid}/export.csv?shortlist_only=true").text)
    assert len(everything) == len(products) + 1  # header + rows
    assert len(starred) == 2 and starred[1][1] == products[1]["title"]
    assert "title" in starred[0] and "megapixels" in starred[0]  # core and device-specific columns

    client.post(f"/api/searches/{sid}/shortlist", json={"product_id": star, "shortlisted": False})
    assert len(read_csv(client.get(f"/api/searches/{sid}/export.csv?shortlist_only=true").text)) == 1


def test_shortlisting_another_searchs_product_is_404():
    a, b = new_search().json()["id"], new_search().json()["id"]
    product_of_a = client.get(f"/api/searches/{a}/results").json()["products"][0]["id"]
    r = client.post(f"/api/searches/{b}/shortlist", json={"product_id": product_of_a, "shortlisted": True})
    assert r.status_code == 404


def test_csv_cells_cannot_run_as_formulas():
    assert _cell("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert _cell("@SUM(A1)") == "'@SUM(A1)"
    assert _cell(["a", "b"]) == "a; b" and _cell(-5) == -5 and _cell(None) is None