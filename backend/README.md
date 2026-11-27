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

**PLC**: PLC CPUs (compact, modular, micro). I/O or expansion modules on their own, HMI panels,
programming cables, VFDs and hobby boards are skipped as "wrong kind of product". Specs: PLC type, digital and analog inputs and outputs built into the CPU (minimums), output type (relay,
transistor sink / NPN, transistor source / PNP; "transistor" without sink or source is flagged, not
guessed), power supply, communication (all of the ports ticked), high-speed counter (kHz), pulse outputs
(axes) and expandable. The brand and series (e.g. Siemens, S7-1200) are read and shown in results but are not search requirements.

**QR code scanner**: 2D scanners that read QR codes (handheld, presentation / desktop, fixed mount, OEM
scan engine). 1D-only laser or CCD barcode scanners, barcode printers, RFID readers, payment terminals and
apps are skipped as "wrong kind of product". Specs: scanner type, codes it reads (all of the ones ticked:
QR Code, Data Matrix, PDF417, Aztec, DotCode, MaxiCode, 1D barcodes), reads phone screens, interface (any of
the ones ticked), finest code (a maximum, in mil: smaller reads smaller codes), reading distance (a minimum,
in mm; "30 cm" on a page is converted) and IP rating.

Encoder specs: encoder type, resolution (PPR for incremental, single-turn bits for absolute), multi-turn,
output / interface, shaft type, shaft or bore diameter, housing diameter (a maximum: the space it must fit),
your supply voltage (kept when it falls inside the encoder's range), max speed and IP rating.

To add another device, write a module like `app/devices/encoder.py` (criteria, spec, extraction model,
normalisation, checks, form fields) and register it in `app/devices/__init__.py`. Its checks use the
comparisons in `app/devices/compare.py`; the search, filter, ranking, form and CSV pick it up automatically.
Add its key specs to `frontend/src/devices.js` for the results table.

### Speed

On Groq's free tier, each model may use 8,000 tokens a minute, and reading one page takes about
3,000. That limit, not the code, sets how fast a search runs. To get the most out of it:

- **Pacing** (`GROQ_TOKENS_PER_MINUTE`, default 8000): the tokens each model used in the last minute
  are counted, and a call waits just long enough for room instead of hitting the limit and failing
  the page. Set it to 0 on a paid plan.
- **Both models** (`GROQ_SPREAD_MODELS`, default 1): when the main model has no room this minute,
  the page goes to `GROQ_FALLBACK_MODEL`, which has its own allowance. That makes page reading about
  twice as fast for the same number of tokens. The total for the day is shared across both models'
  daily allowances. Set it to 0 to keep the backup only for when the main model's daily allowance
  runs out.
- **Searches and downloads**: the planned queries run on Tavily at the same time. Pages download
  10 at a time (`FETCH_WORKERS`), a site gets 8 seconds to answer (`FETCH_TIMEOUT`) and robots.txt
  gets 4 seconds.

### Saving model calls

Before a page goes to the model, `app/services/triage.py` skips the obvious ones in plain Python:
blog, news, guide, company and policy pages (by their address), pages that never mention the device
and show no price, and shop listings (many product links and prices), whose product links are followed
directly. The progress panel counts them as "skipped without a model call". When unsure, the page is read.

### Shipping time

The results table shows a **Shipping time** column whenever at least one result has one, and the CSV always
has it. It holds the delivery or lead time as the page writes it, e.g.
"Delivery: 3-5 working days", "Ships in 2 weeks", "Lead time 4-6 weeks". It is read from the downloaded
page in Python (`app/services/shipping.py`): no model call, no tokens. A product's own lead time is
preferred over a store-wide delivery promise; return, refund and warranty periods are ignored. It is empty
when the page states none, or when the site only works it out in the browser (e.g. from your location).

### Search Pakistan market only

Ticking **Search Pakistan market only** sends `"pakistan_only": true`. Then:

- every search query targets sellers in Pakistan ("... price in Pakistan", Karachi, Lahore), and Tavily is
  asked to prefer results from Pakistan (older tavily-python versions without that option still work);
- a seller counts as Pakistani only when its page shows evidence, checked in Python (`app/services/pakistan.py`):
  a .pk website, a Pakistani phone number (+92 / 03xx), a price in PKR (or "Rs" with no sign of India), or an
  address in a Pakistani city. "We ship to Pakistan" does not count;
- pages without that evidence are skipped before the model reads them, and products without it are dropped
  ("No sign the seller is in Pakistan"); foreign sellers are never shown as closest matches.

The CSV's **Seller in Pakistan** column lists the evidence found for each product.
