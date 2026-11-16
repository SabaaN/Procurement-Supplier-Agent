# Procurement & Supplier Agent: backend

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
pytest -v          # unit tests (graph tests need langgraph)
python run_demo.py # one camera search through the stub graph
```

## Layout

```
app/devices/   what each device type is: criteria, spec, form fields (+ registry)
app/graph/     state, nodes (plain functions), build.py (LangGraph wiring), progress events
tests/
```

## Tuning how wide a search is (backend/.env)

| Variable | Default | What it does |
|---|---|---|
| `MAX_PAGES_PER_ATTEMPT` | `12` | Pages read per search attempt (up to 3 attempts). More pages = more results, but each page is one Groq call; lower it if the progress panel shows many "failed" extractions. |
| `FLEXIBLE_TOLERANCE` | `0.2` | How far short a **Flexible** number may be: `0.2` means 5 MP flexible accepts 4 MP and up. |
| `BUDGET_TOLERANCE` | `0.15` | With **Flexible budget** ticked, products up to 15% over the maximum are kept, flagged. |
| `CHEAP_RATIO` | `0.5` | Products cheaper than the minimum are kept; below half of it they are flagged "unusually cheap". |
| `CLOSEST_MATCHES` | `5` | When nothing matches fully, this many closest products are shown, each saying what it misses. `0` turns this off. |
| `LISTING_LINKS_PER_PAGE` | `4` | Product links read from each shop listing page ("5MP cameras – 24 items"). |
| `MAX_FOLLOWED_PER_ATTEMPT` | `12` | Cap on listing links read per attempt (each is one Groq call). |
| `STRICT_REQUIREMENTS` | `0` | `0`: a required spec the page doesn't mention keeps the product, flagged "not found on page" and ranked lower. `1`: such products are dropped. A product whose page shows it *fails* a requirement is always dropped. |

The Filter step in the progress panel lists why products were dropped, e.g. `3 of 9 products kept (dropped: 5 price outside budget, 1 frame rate: does not meet requirement)`.

### Must have, Flexible, Nice to have

Every spec in the form has three levels:

- **Must have**: the product is dropped if its page shows it fails.
- **Flexible**: close is fine. Numbers up to `FLEXIBLE_TOLERANCE` short are kept as close matches
  (marked ≈ and ranked below full matches); other values that differ are kept as compromises.
  Flexible specs are left out of the web searches, so pages for nearby values are found too.
- **Nice to have**: only affects the ranking.

Searches look for **industrial / machine-vision cameras** only; CCTV, security and consumer cameras
are recognised on the page and skipped ("wrong kind of product" in the progress panel).
