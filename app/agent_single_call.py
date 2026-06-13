"""
Single-call triage agent (fallback architecture for rate-limited deployments).

Instead of an agentic tool-calling loop (multiple LLM calls), this version:
1. Runs ALL tool lookups upfront in Python (no LLM needed - it's just data access)
2. Makes ONE LLM call with all gathered context, asking for the structured triage report

This is friendly to very low RPM limits (works even at 1 request/minute) and is
still a legitimate, defensible architecture: "gather context deterministically,
then reason once" is a common production pattern.
"""

import os
import json
import time
from openai import OpenAI, RateLimitError
from dotenv import load_dotenv

from .tools import (
    get_recent_commits,
    get_schema_history,
    get_similar_incidents,
    get_pipeline_owner,
)

load_dotenv()

MODEL_BACKEND = os.getenv("MODEL_BACKEND", "foundry")

if MODEL_BACKEND == "azure_openai":
    _client = OpenAI(
        base_url=f"{os.getenv('AZURE_OPENAI_ENDPOINT')}/openai/deployments/{os.getenv('AZURE_OPENAI_DEPLOYMENT')}",
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        default_query={"api-version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")},
    )
    MODEL_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT")
else:
    _client = OpenAI(
        base_url=f"{os.getenv('FOUNDRY_ENDPOINT', '').rstrip('/')}/openai/v1",
        api_key=os.getenv("FOUNDRY_API_KEY", ""),
    )
    MODEL_NAME = os.getenv("FOUNDRY_MODEL_NAME", "Phi-4")


SYSTEM_PROMPT = """You are a Pipeline Incident Triage Agent for a data engineering team.

You will be given:
1. An incident report (error message, pipeline, stack trace)
2. Pre-gathered investigation context: recent code commits to the affected
   pipeline, recent schema/data changes to its source tables, similar past
   incidents with their resolutions, and the pipeline's ownership info.

Your job: analyze ALL of this evidence and produce a structured triage report.

Guidelines:
- Identify the MOST LIKELY root cause based on the evidence provided. If a
  recent commit or schema change plausibly explains the error, cite it
  explicitly (commit hash / change description).
- If a similar past incident's resolution applies here, reference it in your
  suggested fix.
- Severity: "low" for warnings/non-fatal issues, "medium" for failures
  affecting one pipeline, "high" for failures that could affect downstream
  financial/customer-facing data or indicate a systemic issue.
- Confidence: "high" only when evidence directly explains the error (e.g. a
  commit/schema change that matches exactly). "medium" when evidence is
  suggestive. "low" when evidence is thin or conflicting.

Respond with ONLY a JSON object (no markdown fences, no extra text) matching
this exact schema:

{
  "incident_id": "<from input>",
  "pipeline": "<pipeline name>",
  "root_cause": "<concise explanation of the most likely root cause>",
  "confidence": "high" | "medium" | "low",
  "evidence": ["<finding 1>", "<finding 2>", ...],
  "suggested_fix": "<concrete suggested fix, referencing past resolutions if applicable>",
  "owner": "<owner name>",
  "owner_contact": "<owner contact>",
  "severity": "low" | "medium" | "high"
}
"""


def gather_context(incident: dict) -> dict:
    """Run all tool lookups upfront (pure Python, no LLM calls)."""
    pipeline_name = incident["pipeline_name"]

    owner_info = get_pipeline_owner(pipeline_name)
    source_tables = owner_info.get("source_tables", [])

    commits = get_recent_commits(pipeline_name, days=7)

    schema_changes = []
    for table in source_tables:
        result = get_schema_history(table, days=14)
        if result["changes_found"] > 0:
            schema_changes.append(result)

    similar = get_similar_incidents(incident["error_message"], pipeline_name=pipeline_name, top_k=3)

    return {
        "owner_info": owner_info,
        "recent_commits": commits,
        "schema_changes": schema_changes,
        "similar_past_incidents": similar,
    }


def _call_with_retry(messages, max_retries=3, base_delay=65):
    """Call chat completions with retry for very low RPM limits (e.g. 1/min)."""
    for attempt in range(max_retries):
        try:
            return _client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=0.2,
            )
        except RateLimitError:
            if attempt == max_retries - 1:
                raise
            print(f"Rate limited. Waiting {base_delay}s before retry...")
            time.sleep(base_delay)


def triage_incident(incident: dict, verbose: bool = True) -> dict:
    """
    Triage a single incident using the single-call architecture.

    Returns the structured triage report dict, plus "_context" key containing
    all gathered evidence (for transparency / dashboard display).
    """
    if verbose:
        print(f"Gathering context for {incident['incident_id']} ({incident['pipeline_name']})...")

    context = gather_context(incident)

    user_message = f"""INCIDENT REPORT:
Incident ID: {incident['incident_id']}
Pipeline: {incident['pipeline_name']}
Timestamp: {incident['timestamp']}
Error message: {incident['error_message']}
Stack trace snippet:
{incident.get('stack_trace_snippet', '(none provided)')}

INVESTIGATION CONTEXT (pre-gathered):

Pipeline ownership & description:
{json.dumps(context['owner_info'], indent=2)}

Recent code commits (last 7 days):
{json.dumps(context['recent_commits'], indent=2)}

Recent schema/data changes on source tables (last 14 days):
{json.dumps(context['schema_changes'], indent=2)}

Similar past incidents:
{json.dumps(context['similar_past_incidents'], indent=2)}

Analyze the above and produce the triage report JSON."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    if verbose:
        print("Calling model for triage analysis...")

    response = _call_with_retry(messages)
    content = response.choices[0].message.content or ""

    report = _parse_final_report(content, incident)
    report["_context"] = context
    report["_raw_model_output"] = content
    return report


def _parse_final_report(content: str, incident: dict) -> dict:
    content = content.strip()

    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        report = json.loads(content)
        report.setdefault("incident_id", incident["incident_id"])
        report.setdefault("pipeline", incident["pipeline_name"])
        report.setdefault("confidence", "low")
        report.setdefault("severity", "medium")
        report.setdefault("evidence", [])
        return report
    except json.JSONDecodeError:
        return {
            "incident_id": incident["incident_id"],
            "pipeline": incident["pipeline_name"],
            "root_cause": "Could not parse structured output from model.",
            "confidence": "low",
            "evidence": [],
            "suggested_fix": "Manual review required.",
            "owner": "unknown",
            "owner_contact": "unknown",
            "severity": "medium",
            "_parse_error": True,
            "_raw_model_output": content,
        }


if __name__ == "__main__":
    from pathlib import Path

    incidents = json.loads((Path(__file__).parent.parent / "data" / "incoming_incidents.json").read_text())
    test_incident = incidents[0]

    result = triage_incident(test_incident)
    print("\n=== TRIAGE REPORT ===")
    print(json.dumps({k: v for k, v in result.items() if not k.startswith("_")}, indent=2))
