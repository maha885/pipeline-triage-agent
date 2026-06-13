# Pipeline Incident Triage Agent

**An AI agent that investigates failed data pipelines and tells you what went wrong, why, and how to fix it - before you even open a log file.**

Built for **Microsoft Build AI 2026**, theme: **AI at Work - Productivity & Teamwork Reimagined**.

---

## The idea, in plain terms

Data pipelines (the automated jobs that move and transform data between systems)
fail constantly - a column gets renamed upstream, an API changes its response
format, a server runs out of memory. When this happens, an on-call engineer gets
paged with nothing but a raw error message and a stack trace.

What usually follows is 30-90 minutes of manual detective work:
- Reading the error and stack trace
- Checking GitHub for recent code changes to that pipeline
- Checking whether any upstream data source changed its schema recently
- Searching old tickets/Slack for "has this happened before, and how was it fixed?"
- Finally figuring out who actually owns the broken pipeline

**This project automates that entire investigation.** You give it the error
message and stack trace, and within seconds it returns a structured report:
what most likely caused the failure, the evidence supporting that conclusion,
a concrete suggested fix, how urgent it is, and who should be notified.

It's powered by a large language model (Llama 3.3 70B) running on Azure AI
Foundry, which reasons over the gathered evidence the same way an experienced
engineer would - just much faster.

---

## How it works (high level)

1. **An incident comes in** - an error message and stack trace from a failed
   pipeline run.
2. **The system gathers context automatically**, using plain Python (no AI
   needed for this part):
   - Information about the pipeline itself (who owns it, what tables it reads/writes)
   - Code changes made to that pipeline in the last 7 days
   - Schema or data changes on its source tables in the last 14 days
   - Past incidents with similar error messages, and how they were resolved
3. **All of that context, plus the incident, is sent to the AI model in one
   request.** The model reads everything and reasons about what's actually
   going on.
4. **The model returns a structured report**: root cause, supporting evidence,
   a suggested fix, a confidence level, a severity rating, and the person to
   notify.
5. **The report is shown on a dashboard** where an engineer can review it
   instantly.

A diagram of this flow is included in the project (`architecture.png` /
`architecture.svg`) and in the project deck.

---

## Demo

Live URL: `https://pipeline-triage-app-hkeqdmgudag2h5cq.westus2-01.azurewebsites.net/`

The dashboard ships with 4 realistic incident scenarios, each representing a
different category of real-world pipeline failure:

| Incident | Pipeline | What went wrong |
|---|---|---|
| INC-2001 | customer_orders_etl | An upstream API changed how it formats a status field (schema drift) |
| INC-2002 | finance_revenue_aggregation | A vendor data feed was missing data for one day (data gap) |
| INC-2003 | inventory_sync | A recent code change caused the pipeline to run out of memory (resource limit) |
| INC-2004 | marketing_campaign_attribution | An upstream API added new fields that aren't fatal but should be handled (benign schema change) |

### Example output (INC-2003)

```
Root cause: Ingestion pod memory limit exceeded due to increased SAP export
file size and batch size

Evidence:
> Recent commit d4a8b71 increased batch size from 5000 to 20000 rows without
  adjusting memory allocation
> SAP export file size increased ~4x due to new warehouse locations added in
  EMEA region
> Similar past incident INC-1103 had a similar root cause and resolution

Suggested fix: Increase ingestion pod memory limit and consider switching to
streaming/chunked file parsing instead of loading the full file into memory,
as done in INC-1103

Confidence: high | Severity: medium | Notify: Arjun Mehta
```

This is a real, live response from the deployed agent - not a hardcoded example.

---

## Architecture

```
Pipeline incident (error message + stack trace)
        |
        v
Context gathering (Python, no AI involved)
  - Pipeline info (owner, source/target tables)
  - Recent commits (last 7 days)
  - Schema/data changes on source tables (last 14 days)
  - Similar past incidents (similarity search)
        |
        v
Llama 3.3 70B (Azure AI Foundry) - single call
  - Analyzes all gathered context + incident together
  - Produces a structured triage report
        |
        v
Triage report (shown on dashboard)
  - Root cause, evidence, suggested fix
  - Confidence, severity, owner to notify
```

### Why gather context first, then make one AI call?

All the context-gathering steps (checking commits, schema changes, past
incidents) are simple, deterministic lookups - there's never a question of
*whether* to check them, only *what* they return. So instead of having the AI
model decide step-by-step which tools to call (an "agentic loop", which takes
multiple back-and-forth AI calls), this system gathers everything up front in
plain Python and gives the model the complete picture in a single call.

This is faster, cheaper, and more reliable - especially important under the
rate limits of a serverless AI deployment - while still letting the model do
genuine analytical work: connecting a specific commit, a specific schema
change, and a specific past incident to explain *this* failure.

An alternate implementation using a multi-step agentic tool-calling loop is
also included (`app/agent.py`) for reference.

---

## Tech stack

- **Backend**: FastAPI (Python) - serves the API and dashboard
- **AI**: Llama 3.3 70B Instruct, deployed as a serverless model via Azure AI
  Foundry, accessed through the OpenAI-compatible chat completions API
- **Frontend**: Single-page HTML/CSS/JS dashboard (no build tools needed)
- **Data**: Synthetic JSON files simulating pipeline metadata, git commit
  history, schema change history, and a past-incidents database - designed to
  represent realistic data engineering scenarios
- **Deployment**: Azure App Service (Linux, Python 3.12), deployed via GitHub
  Actions CI/CD

---

## Project structure

```
pipeline-triage-agent/
├── data/
│   ├── pipelines.json          # 6 pipelines: owners, tables, schedules
│   ├── commits.json            # recent code commits per pipeline
│   ├── schema_changes.json     # upstream schema/data drift events
│   ├── past_incidents.json     # resolved incidents (for similarity search)
│   └── incoming_incidents.json # 4 demo scenarios
├── app/
│   ├── tools.py                # context-gathering functions
│   ├── agent_single_call.py    # core agent: gather context + single AI call
│   ├── agent.py                # alternate: multi-step agentic tool-calling version
│   └── main.py                 # FastAPI app + API endpoints
├── static/
│   └── index.html              # dashboard frontend
├── architecture.svg / .png     # architecture diagram
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup (run it yourself)

1. Clone the repo and install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in your Azure AI Foundry endpoint and
   API key. You'll need a model deployed via the Foundry Models marketplace
   that supports chat completions (this project uses Llama 3.3 70B Instruct
   as a serverless deployment):
```bash
cp .env.example .env
```

3. Run the server:
```bash
uvicorn app.main:app --reload --port 8000
```

4. Open `http://localhost:8000` in your browser.

---

## API endpoints

- `GET /api/incidents` - list all demo incidents
- `GET /api/incidents/{incident_id}` - get full incident details
- `POST /api/triage/{incident_id}` - run the triage agent on an incident,
  returns the structured report (cached after first run)
- `GET /api/health` - health check

---

## AI tools disclosure

This project was developed with assistance from:

- **Claude (Anthropic)** - used for architecture design, code generation
  (FastAPI backend, agent logic, dashboard frontend), debugging, and
  documentation throughout development.
- **GitHub Copilot** - in-editor coding assistance.
- **Llama 3.3 70B Instruct (Azure AI Foundry)** - this is not a development
  tool but the core AI component of the product itself: it's the model that
  performs the root-cause analysis described above.

All architectural decisions, prompt design, testing, and final integration
were done by the author. The synthetic datasets (pipelines, commits, schema
changes, and incidents) were designed by the author to represent realistic
data engineering scenarios based on real-world experience.

---

## Known limitations / future work

- **Severity calibration**: the model sometimes rates non-fatal warnings
  (e.g. INC-2004) as "medium" rather than "low" - a prompt refinement or a few
  example reports would tighten this.
- **Synthetic data**: this build uses realistic synthetic data instead of live
  connections to real systems. A production version would connect to actual
  Airflow/Azure Data Factory logs, a git provider's API, a schema registry, and
  an incident management tool (e.g. PagerDuty, Jira).
- **Notifications**: a Teams/Slack webhook integration was designed but not
  wired up in this build - the dashboard currently shows who *should* be
  notified, but doesn't send the notification automatically yet.
- **Agentic variant**: `app/agent.py` demonstrates a multi-step reasoning loop
  with function calling, which could be used if migrating to a model/deployment
  with higher rate limits than the single-call approach requires.

---

## Team

Solo build - Debasis Moharana, Data Engineer.
