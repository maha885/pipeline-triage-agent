"""
Tools available to the Pipeline Incident Triage Agent.

Each tool is a plain Python function operating on synthetic JSON data
(simulating Airflow/ADF logs, git history, schema registry, and incident DB).

TOOL_SCHEMA below is the function-calling schema passed to the LLM.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from difflib import SequenceMatcher

DATA_DIR = Path(__file__).parent.parent / "data"


def _load(filename: str):
    with open(DATA_DIR / filename) as f:
        return json.load(f)


PIPELINES = _load("pipelines.json")
COMMITS = _load("commits.json")
SCHEMA_CHANGES = _load("schema_changes.json")
PAST_INCIDENTS = _load("past_incidents.json")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def get_recent_commits(pipeline_name: str, days: int = 7) -> dict:
    """Get recent code commits affecting a given pipeline within the last `days` days."""
    # Note: our synthetic data is dated relative to 2026-06-12, so we use a fixed "now"
    now = datetime(2026, 6, 12, 16, 0, 0)
    cutoff = now - timedelta(days=days)

    results = []
    for c in COMMITS:
        if c["pipeline_name"] != pipeline_name:
            continue
        ts = datetime.fromisoformat(c["timestamp"].replace("Z", ""))
        if ts >= cutoff:
            results.append(c)

    return {
        "pipeline_name": pipeline_name,
        "lookback_days": days,
        "commits_found": len(results),
        "commits": results,
    }


def get_schema_history(table_name: str, days: int = 14) -> dict:
    """Get recent schema/data changes for a given table within the last `days` days."""
    now = datetime(2026, 6, 12, 16, 0, 0)
    cutoff = now - timedelta(days=days)

    results = []
    for s in SCHEMA_CHANGES:
        if s["table_name"] != table_name:
            continue
        ts = datetime.fromisoformat(s["timestamp"].replace("Z", ""))
        if ts >= cutoff:
            results.append(s)

    return {
        "table_name": table_name,
        "lookback_days": days,
        "changes_found": len(results),
        "changes": results,
    }


def get_similar_incidents(error_message: str, pipeline_name: str = None, top_k: int = 3) -> dict:
    """
    Find past incidents with similar error signatures and their resolutions.
    Uses simple text similarity over error messages/signatures.
    """
    scored = []
    for inc in PAST_INCIDENTS:
        text = inc["error_signature"] + " " + inc["error_message"]
        sim = SequenceMatcher(None, error_message.lower(), text.lower()).ratio()
        # Boost score if same pipeline
        if pipeline_name and inc["pipeline_name"] == pipeline_name:
            sim += 0.15
        scored.append((sim, inc))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    return {
        "query_error_message": error_message,
        "matches": [
            {
                "incident_id": inc["incident_id"],
                "pipeline_name": inc["pipeline_name"],
                "similarity_score": round(score, 3),
                "error_signature": inc["error_signature"],
                "root_cause": inc["root_cause"],
                "resolution": inc["resolution"],
                "resolved_by": inc["resolved_by"],
                "time_to_resolve_minutes": inc["time_to_resolve_minutes"],
            }
            for score, inc in top
        ],
    }


def get_pipeline_owner(pipeline_name: str) -> dict:
    """Get the owning team/person and source/target tables for a pipeline."""
    for p in PIPELINES:
        if p["pipeline_name"] == pipeline_name:
            return {
                "pipeline_name": p["pipeline_name"],
                "description": p["description"],
                "owner": p["owner"],
                "owner_team": p["owner_team"],
                "owner_contact": p["owner_contact"],
                "source_tables": p["source_tables"],
                "target_table": p["target_table"],
                "schedule": p["schedule"],
            }
    return {"error": f"Pipeline '{pipeline_name}' not found"}


# ---------------------------------------------------------------------------
# Function-calling tool schema (OpenAI / Foundry compatible format)
# ---------------------------------------------------------------------------

TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_recent_commits",
            "description": "Get recent code commits affecting a given pipeline. Useful for checking if a recent code change may have caused the failure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_name": {
                        "type": "string",
                        "description": "Name of the pipeline, e.g. 'customer_orders_etl'",
                    },
                    "days": {
                        "type": "integer",
                        "description": "How many days to look back (default 7)",
                    },
                },
                "required": ["pipeline_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schema_history",
            "description": "Get recent schema or data changes for a given source/target table. Useful for checking if upstream schema drift or data gaps caused the failure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Fully-qualified table name, e.g. 'raw.shopify_orders'",
                    },
                    "days": {
                        "type": "integer",
                        "description": "How many days to look back (default 14)",
                    },
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_similar_incidents",
            "description": "Search past resolved incidents for ones with similar error messages/signatures. Returns root causes and resolutions that may apply here.",
            "parameters": {
                "type": "object",
                "properties": {
                    "error_message": {
                        "type": "string",
                        "description": "The error message or stack trace from the current incident",
                    },
                    "pipeline_name": {
                        "type": "string",
                        "description": "Name of the pipeline currently failing (used to boost relevance)",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of top matches to return (default 3)",
                    },
                },
                "required": ["error_message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pipeline_owner",
            "description": "Get the owning team/person, description, and source/target tables for a pipeline. Use this to determine who should be notified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_name": {
                        "type": "string",
                        "description": "Name of the pipeline, e.g. 'customer_orders_etl'",
                    },
                },
                "required": ["pipeline_name"],
            },
        },
    },
]


# Map tool name -> python function, for dispatch
TOOL_FUNCTIONS = {
    "get_recent_commits": get_recent_commits,
    "get_schema_history": get_schema_history,
    "get_similar_incidents": get_similar_incidents,
    "get_pipeline_owner": get_pipeline_owner,
}


def call_tool(name: str, arguments: dict) -> dict:
    """Dispatch a tool call by name with given arguments."""
    if name not in TOOL_FUNCTIONS:
        return {"error": f"Unknown tool: {name}"}
    try:
        return TOOL_FUNCTIONS[name](**arguments)
    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}"}


if __name__ == "__main__":
    # Quick smoke test
    print("=== get_recent_commits ===")
    print(json.dumps(get_recent_commits("customer_orders_etl"), indent=2))

    print("\n=== get_schema_history ===")
    print(json.dumps(get_schema_history("raw.shopify_orders"), indent=2))

    print("\n=== get_similar_incidents ===")
    print(json.dumps(
        get_similar_incidents(
            "ValueError: invalid literal for OrderStatus enum: 'paid'",
            pipeline_name="customer_orders_etl"
        ), indent=2
    ))

    print("\n=== get_pipeline_owner ===")
    print(json.dumps(get_pipeline_owner("customer_orders_etl"), indent=2))
