# Pipeline Incident Triage Agent

An AI agent that triages data pipeline failures: it investigates recent code
changes, upstream schema/data drift, and similar past incidents, then produces
a structured root-cause analysis with a suggested fix and the right person to
notify.

## Status

- [x] Synthetic data (pipelines, commits, schema changes, past incidents, incoming incidents)
- [x] Tool functions + function-calling schema (`app/tools.py`)
- [x] Agent loop with tool-calling + structured output (`app/agent.py`)
- [ ] FastAPI endpoints
- [ ] Dashboard (frontend)
- [ ] Teams webhook integration
- [ ] Deployment

## Setup

1. Copy `.env.example` to `.env` and fill in your Azure AI Foundry endpoint/key
   (deploy Phi-4 via Foundry Models marketplace - no Limited Access approval needed).

```bash
cp .env.example .env
pip install -r requirements.txt  # (to be added)
```

2. Test the tool layer (no API key needed):

```bash
python -m app.tools
```

3. Test the full agent loop (requires Foundry endpoint configured in `.env`):

```bash
python -m app.agent
```

## Architecture

```
Incident (error message, pipeline, stack trace)
        |
        v
  Triage Agent (Phi-4 via Azure AI Foundry, function-calling)
        |
        |-- get_recent_commits(pipeline)
        |-- get_schema_history(table)
        |-- get_similar_incidents(error)
        |-- get_pipeline_owner(pipeline)
        |
        v
  Structured Triage Report
  { root_cause, confidence, evidence[], suggested_fix, owner, severity }
        |
        v
  Dashboard  +  Teams webhook
```

## Project structure

```
pipeline-triage-agent/
├── data/
│   ├── pipelines.json          # 6 pipelines: owners, tables, schedules
│   ├── commits.json            # recent code commits per pipeline
│   ├── schema_changes.json     # upstream schema/data drift events
│   ├── past_incidents.json     # resolved incidents (for similarity search)
│   └── incoming_incidents.json # 4 demo scenarios to triage live
├── app/
│   ├── tools.py                # tool functions + function-calling schema
│   └── agent.py                # agent loop (Phi-4, tool-calling, structured output)
├── .env.example
└── README.md
```

## AI tools disclosure

This project was developed with assistance from Claude (Anthropic) for code
generation, architecture design, and documentation, and GitHub Copilot for
in-editor coding assistance. All architectural decisions, prompt design, and
final integration were done by the author.
