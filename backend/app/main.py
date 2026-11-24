"""FastAPI app: starts searches as background jobs, streams progress over SSE, serves results.

Run from backend/:   uvicorn app.main:app --reload
Interactive docs:    http://127.0.0.1:8000/docs
"""
import csv
import io
import json
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ValidationError

from .devices import UnsupportedDevice, get_device, list_devices
from .devices.base import ProductBase
from .runner import run_search
from .services import datasheets, store
from .services.contacts import enrich

TERMINAL = {"done", "failed"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.fail_interrupted()  # searches left running by a crash would otherwise hang their streams
    yield


app = FastAPI(title="Procurement & Supplier Agent", lifespan=lifespan)
app.add_middleware(  # the React dev server (Vite) runs on port 5173
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    device_type: str
    criteria: dict = {}


class ShortlistRequest(BaseModel):
    product_id: int
    shortlisted: bool


def _search_or_404(search_id: str) -> dict:
    search = store.get_search(search_id)
    if search is None:
        raise HTTPException(404, "Search not found")
    return search


# ---- devices (drives the dropdown and the dynamic form) ----

@app.get("/api/devices")
def devices():
    return list_devices()


@app.get("/api/devices/{key}")
def device_form(key: str):
    try:
        device = get_device(key)
    except UnsupportedDevice as e:
        raise HTTPException(404, str(e))
    return {"key": device.key, "label": device.label, "fields": [f.model_dump() for f in device.fields]}


# ---- searches ----

@app.post("/api/searches", status_code=202)
def create_search(req: SearchRequest, background: BackgroundTasks):
    try:
        device = get_device(req.device_type)
    except UnsupportedDevice as e:
        raise HTTPException(400, str(e))
    try:  # reject bad form input now, with field names, instead of failing in the background
        device.criteria_model.model_validate(req.criteria)
    except ValidationError as e:
        raise HTTPException(422, [_field_error(err) for err in e.errors()])
    search_id = store.create_search(req.device_type, req.criteria)
    background.add_task(run_search, search_id)
    return {"id": search_id}


def _field_error(err: dict) -> dict:
    """One validation error as {field, message}. Errors about the whole form (no field) are pinned to
    the field they concern, so the form can highlight it."""
    field = ".".join(str(x) for x in err["loc"])
    message = err["msg"].removeprefix("Value error, ")
    if not field and "budget" in message:
        field, message = "budget_max", "Budget max must be at least Budget min"
    return {"field": field, "message": message}


@app.get("/api/searches")
def history():
    return store.list_searches()


@app.get("/api/searches/{search_id}")
def get_search(search_id: str):
    return _search_or_404(search_id)


@app.get("/api/searches/{search_id}/results")
def results(search_id: str):
    return {"search": _search_or_404(search_id), "products": store.get_products(search_id)}


# ---- live progress (server-sent events) ----

def _sse(event: str, data: dict, seq: int | None = None) -> str:
    head = f"id: {seq}\n" if seq is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/searches/{search_id}/stream")
def stream(search_id: str, last_event_id: str | None = Header(default=None), after: int = 0):
    """Replays saved progress events, then follows new ones until the search ends.
    A reconnecting EventSource sends Last-Event-ID, so it resumes where it left off."""
    _search_or_404(search_id)
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after

    def generate():
        seq, quiet = start, 0
        while True:
            # Read the status BEFORE the events: events are always saved before the status turns
            # terminal, so a terminal status means the events read next are complete.
            search = store.get_search(search_id)
            events = store.get_events(search_id, after=seq)
            for event_seq, event in events:
                seq = event_seq
                yield _sse("progress", event, event_seq)
            if search["status"] in TERMINAL:
                yield _sse("end", {"status": search["status"], "error": search["error"]})
                return
            quiet = 0 if events else quiet + 1
            if quiet >= 30:  # about 15 s of silence: keep proxies from closing the connection
                yield ": keepalive\n\n"
                quiet = 0
            time.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- shortlist and export ----

@app.post("/api/searches/{search_id}/shortlist")
def shortlist(search_id: str, req: ShortlistRequest):
    _search_or_404(search_id)
    if not store.set_shortlisted(search_id, req.product_id, req.shortlisted):
        raise HTTPException(404, "Product not found in this search")
    return {"product_id": req.product_id, "shortlisted": req.shortlisted}


# (product field, CSV header). The supplier-contact columns use the names buyers asked for.
CORE_COLUMNS = [
    ("rank", "rank"), ("title", "title"),
    ("company_name", "Company name"), ("email", "Email"), ("contact_no", "Contact no"),
    ("product_link", "Product link"), ("datasheet_url", "Datasheet (PDF)"),
    ("supplier", "supplier"), ("part_number", "part_number"), ("price", "price"), ("currency", "currency"),
    ("price_buyer", "price_buyer"), ("total_cost", "total_cost"), ("match_score", "match_score"),
    ("requirements_met", "requirements_met"), ("requirements_close", "requirements_close"),
    ("close_notes", "close_notes"), ("requirements_missed", "requirements_missed"),
    ("misses", "Not an exact match because"),
    ("flags", "flags"), ("fetched_at", "fetched_at"),
]


def _cell(value):
    """One CSV cell. Text from web pages must not run as a spreadsheet formula."""
    if isinstance(value, list):
        value = "; ".join(str(v) for v in value)
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@app.get("/api/searches/{search_id}/export.csv")
def export_csv(search_id: str, shortlist_only: bool = Query(False)):
    search = _search_or_404(search_id)
    products = store.get_products(search_id)
    if shortlist_only:
        products = [p for p in products if p["shortlisted"]]
    device = get_device(search["device_type"])
    spec_columns = sorted(set(device.spec_model.model_fields) - set(ProductBase.model_fields))
    columns = CORE_COLUMNS + [(c, c) for c in spec_columns]

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([header for _, header in columns])
    for p in products:
        if "product_link" not in p:  # saved before contact columns existed: fill what we can
            p = {**enrich(p, None), **{k: v for k, v in p.items() if v is not None}}
        writer.writerow([_cell(p.get(key)) for key, _ in columns])
    return Response(
        "\ufeff" + out.getvalue(),  # the BOM makes Excel read the file as UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="results-{search_id[:8]}.csv"'},
    )

# ---- datasheets ----

@app.get("/api/searches/{search_id}/products/{product_id}/datasheet")
def datasheet(search_id: str, product_id: int):
    """Downloads the product's datasheet PDF from the supplier and returns it as a file."""
    _search_or_404(search_id)
    product = store.get_product(search_id, product_id)
    if product is None:
        raise HTTPException(404, "Product not found in this search")
    url = product.get("datasheet_url")
    if not url:
        raise HTTPException(404, "No datasheet was found on this product's page")
    try:
        pdf = datasheets.download(url)
    except datasheets.DatasheetError as e:
        raise HTTPException(502, str(e))
    name = datasheets.filename_for(url, product.get("title"))
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
