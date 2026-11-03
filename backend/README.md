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
