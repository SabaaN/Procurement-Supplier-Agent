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
| `MAX_PAGE_CHARS` | `6000` | Characters of page text sent to the model per page (about 1 token per 4 characters). Spec tables and the price box are kept first. |
| `EXTRACTION_CACHE_DAYS` | `7` | How long what the model read off a page is reused before reading it again. Prices in results can be up to this old; lower it if prices move fast. Downloads still refresh daily (no model call). |
| `GROQ_REASONING_EFFORT` | `low` | For gpt-oss models: how much hidden reasoning before each answer. Those tokens count towards Groq's daily limit, and reading specs off a page needs little. `medium`/`high` for more care, empty for Groq's default. |
| `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-120b` | When a model hits Groq's daily token limit, calls move to this one (it has its own allowance). When every model is out, the search stops reading pages, keeps what it has, and says when to try again. Empty turns the backup off. |
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

Camera searches prioritize **industrial / machine-vision cameras** and also include ordinary digital,
photo/video, webcam, action and CCTV/security cameras. Camera products from any of these categories can be returned.

### Device types

**Camera**: all camera categories, with industrial / machine-vision cameras prioritized. **Encoder**: industrial rotary encoders (incremental or
absolute, solid or hollow shaft). Video encoders, hobby rotary knobs (KY-040, EC11) and linear encoders are
recognised on the page and skipped as "wrong kind of product".

**Photoelectric sensor**: industrial photoelectric sensors (through-beam, retro-reflective, diffuse,
background suppression, fiber optic). Proximity sensors, light curtains, PIR motion detectors and hobby IR
modules are skipped as "wrong kind of product". Specs: sensing method, sensing distance (a minimum, in mm;
"2 m" or "20 cm" on a page is converted), output, light-on / dark-on (sensors with a selector count for
either), light source, housing, connection, your supply voltage, response time (a maximum, in ms) and IP rating.

Encoder specs: encoder type, resolution (PPR for incremental, single-turn bits for absolute), multi-turn,
output / interface, shaft type, shaft or bore diameter, housing diameter (a maximum: the space it must fit),
your supply voltage (kept when it falls inside the encoder's range), max speed and IP rating.

To add another device, write a module like `app/devices/encoder.py` (criteria, spec, extraction model,
normalisation, checks, form fields) and register it in `app/devices/__init__.py`. Its checks use the
comparisons in `app/devices/compare.py`; the search, filter, ranking, form and CSV pick it up automatically.
Add its key specs to `frontend/src/devices.js` for the results table.

### Saving model calls

Before a page goes to the model, `app/services/triage.py` skips the obvious ones in plain Python:
blog, news, guide, company and policy pages (by their address), pages that never mention the device
and show no price, and shop listings (many product links and prices), whose product links are followed
directly. The progress panel counts them as "skipped without a model call". When unsure, the page is read.
