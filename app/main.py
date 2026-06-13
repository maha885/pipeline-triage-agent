"""
FastAPI backend for the Pipeline Incident Triage Agent.

Endpoints:
  GET  /api/incidents              - list all demo incidents (without triage)
  GET  /api/incidents/{incident_id} - get raw incident details
  POST /api/triage/{incident_id}   - run the triage agent on an incident, returns report
  GET  /                            - serves the dashboard (static/index.html)
"""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .agent_single_call import triage_incident

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

app = FastAPI(title="Pipeline Incident Triage Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory cache so re-clicking the same incident during a demo
# doesn't burn extra API calls (helpful given low rate limits).
_triage_cache: dict[str, dict] = {}


def _load_incidents() -> list[dict]:
    with open(DATA_DIR / "incoming_incidents.json") as f:
        return json.load(f)


@app.get("/api/incidents")
def list_incidents():
    """List all demo incidents with basic info (no triage run yet)."""
    incidents = _load_incidents()
    return [
        {
            "incident_id": inc["incident_id"],
            "pipeline_name": inc["pipeline_name"],
            "timestamp": inc["timestamp"],
            "error_message": inc["error_message"],
            "triaged": inc["incident_id"] in _triage_cache,
        }
        for inc in incidents
    ]


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    """Get full raw details for one incident."""
    incidents = _load_incidents()
    for inc in incidents:
        if inc["incident_id"] == incident_id:
            return inc
    raise HTTPException(status_code=404, detail="Incident not found")


@app.post("/api/triage/{incident_id}")
def triage(incident_id: str, force: bool = False):
    """
    Run the triage agent on the given incident and return the structured report.
    Results are cached; pass ?force=true to re-run.
    """
    if not force and incident_id in _triage_cache:
        return _triage_cache[incident_id]

    incidents = _load_incidents()
    incident = next((i for i in incidents if i["incident_id"] == incident_id), None)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        report = triage_incident(incident, verbose=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Triage failed: {str(e)}")

    # Strip large internal fields before caching/returning to keep payload small,
    # but keep evidence/context summary for the dashboard
    public_report = {k: v for k, v in report.items() if not k.startswith("_raw")}

    _triage_cache[incident_id] = public_report
    return public_report


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the dashboard static files (built in the next step)
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
