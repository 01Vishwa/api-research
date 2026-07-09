# AgentForge — Autonomous API Research & Verification System

> **Composio 100-App Research Assignment** · Built to automate the manual work of researching SaaS app integration readiness.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.1+-green.svg)](https://langchain-ai.github.io/langgraph/)
[![Composio](https://img.shields.io/badge/Composio-SDK-purple.svg)](https://composio.dev)

---

## What This Is

AgentForge is an autonomous research pipeline that investigates 100 SaaS applications and answers:
- What auth method does each app use (OAuth2, API Key, etc.)?
- Is developer access self-serve or gated behind sales/partnerships?
- Does a public REST/GraphQL API exist?
- Can an AI agent toolkit be built today?
- Are there existing MCP servers?

It does this **without human input** — and then verifies its own output with an independent second agent pass.

---

## Architecture

```
100 apps (apps.json)
       │
       ▼
[Planning Agent]        ← generates search queries per app
       │
       ▼
[Research Worker]       ← web search + doc fetch + LLM extraction
  (LangGraph DAG)         Gemini 2.0 Flash | Tavily | httpx
       │
       ▼
[raw_pass1.json]        ← 100 structured records + confidence scores
       │
       ▼
[Verification Agent]    ← independently re-fetches evidence, re-derives answers
  (LangGraph DAG)         Never sees researcher's answers — genuine independence
       │
       ▼
[pass2_verified.json]   ← corrections applied, verification status per app
       │
       ▼
[Insight Generator]     ← auth distribution, gating by category, easy wins
       │
       ▼
[HTML Report Generator] ← single self-contained report.html
```

Both LangGraph graphs are **strictly acyclic (DAGs)** — no cycles, no deadlocks, hard `recursion_limit` set.

---

## Composio SDK Usage

The pipeline uses [Composio's Python SDK](https://composio.dev) as the tool layer for search and fetch:

```python
from composio import Composio
from composio_langchain import LangchainProvider

composio = Composio(
    provider=LangchainProvider(),
    api_key=COMPOSIO_API_KEY
)

session = composio.create(
    user_id="agentforge-researcher",
    manage_connections={
        "wait_for_connections": True,
    },
)

tools = session.tools()  # LangChain-compatible tool list
```

Without `COMPOSIO_API_KEY`, the pipeline gracefully falls back to Tavily + httpx — the logic is identical.

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/your-username/api-research
cd api-research
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your API keys:
#   GEMINI_API_KEY   (required)  — https://aistudio.google.com
#   TAVILY_API_KEY   (recommended) — https://app.tavily.com
#   COMPOSIO_API_KEY (optional)  — https://app.composio.dev
```

### 3. Run the full pipeline

```bash
python -m agentforge.main run
```

This runs all stages end-to-end and produces `report.html`.

### 4. View the report

Open `report.html` in any browser — it's fully self-contained.

---

## CLI Commands

```bash
# Full pipeline (research → verify → insights → report)
python -m agentforge.main run

# Research only (faster, no verification)
python -m agentforge.main research

# Verify existing pass-1 results
python -m agentforge.main verify

# Generate insights from verified results
python -m agentforge.main insights

# Generate HTML report
python -m agentforge.main report

# Export to CSV
python -m agentforge.main export

# Skip verification (faster, less accurate)
python -m agentforge.main run --skip-verify
```

---

## Output Files

| File | Description |
|------|-------------|
| `output/raw_pass1.json` | Research agent output (100 rows, unverified) |
| `output/pass2_verified.json` | After verification agent corrections |
| `output/verification_log.json` | All corrections made by verifier |
| `output/insights.json` | Computed statistics and patterns |
| `report.html` | Self-contained interactive HTML report |
| `output/apps.csv` | CSV export of all records |
| `logs/pipeline.log` | Full execution log |

---

## Directory Structure

```
api-research/
├── agentforge/
│   ├── agents/
│   │   ├── researcher.py      # LangGraph research DAG
│   │   ├── verifier.py        # LangGraph verification DAG
│   │   └── insight_generator.py
│   ├── tools/
│   │   ├── composio_client.py # Composio SDK integration
│   │   ├── search.py          # Tavily + fallback
│   │   └── fetcher.py         # httpx page fetcher
│   ├── models/
│   │   └── schema.py          # Pydantic data models
│   ├── pipeline/
│   │   ├── runner.py          # Async batch orchestrator
│   │   └── normalizer.py      # Enum normalization
│   ├── report/
│   │   └── generator.py       # HTML report builder
│   ├── data/
│   │   └── apps.json          # 100-app input dataset
│   ├── config.py              # All settings from env vars
│   └── main.py                # CLI entrypoint
├── output/                    # Generated data files
├── logs/                      # Execution logs
├── requirements.txt
├── .env.example
└── README.md
```

---

## Verification Methodology

1. **Pass 1** — Research agent extracts from web search + docs
2. **Pass 2** — Verifier agent re-fetches the same evidence URL independently
3. The verifier uses a different system prompt and **never sees the researcher's answers**
4. Corrections are applied only at confidence ≥ 60%
5. Remaining `needs-human` rows are **flagged, not hidden**
6. Manual spot-check on 15–20 stratified rows (2 per category) records final ground truth

This produces a measurable accuracy delta: Pass 1 → Pass 2.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | ✅ Required | Gemini LLM for extraction and verification |
| `TAVILY_API_KEY` | ⭐ Recommended | Web search (1000 free/month) |
| `COMPOSIO_API_KEY` | Optional | Composio SDK tools (search/fetch layer) |
| `COMPOSIO_USER_ID` | Optional | Session user ID (default: `agentforge-researcher`) |
| `BATCH_SIZE` | Optional | Concurrent app batch size (default: 10) |
| `GEMINI_MODEL` | Optional | Model name (default: `gemini-2.0-flash-exp`) |

---

## Known Limitations

- Apps with no public developer docs (Fanbasis, iPayX, Paygent Connect) are flagged as `needs-human` — this is the correct finding, not a failure.
- Some enterprise platforms (DealCloud, Gladly, PitchBook) require partnership before API access — documented as `contact-sales`.
- Rate limits on Gemini free tier may slow batch processing; the pipeline is resumable.

---

## Live Report

→ **[View report.html](./report.html)** (deploy to GitHub Pages for live URL)

---

*Built with LangGraph + Gemini 2.0 Flash + Composio SDK + Tavily*
