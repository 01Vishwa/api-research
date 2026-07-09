# API Research — Autonomous API Research & Verification System

> **Composio 100-App Research Assignment** · Built to automate the manual work of researching SaaS app integration readiness.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.1+-green.svg)](https://langchain-ai.github.io/langgraph/)
[![Composio](https://img.shields.io/badge/Composio-SDK-purple.svg)](https://composio.dev)

---

## What This Is

API-Research is an autonomous research pipeline that investigates 100 SaaS applications and answers:
- What auth method does each app use (OAuth2, API Key, etc.)?
- Is developer access self-serve or gated behind sales/partnerships?
- Does a public REST/GraphQL API exist?
- Can an AI agent toolkit be built today?
- Are there existing MCP servers?

It does this **without human input** — and then verifies its own output with an independent second agent pass.

---

## Architecture & Models

The pipeline uses state-of-the-art LLMs via GitHub Models (with OpenAI fallbacks) to process web data.
- **Research Pass:** Uses `openai/gpt-5` for deep web extraction.
- **Verification Pass:** Uses `gpt-4o-mini` to independently verify the researcher's claims.

```text
100 apps (apps.json)
       │
       ▼
[Planning Agent]        ← generates search queries per app
       │
       ▼
[Research Worker]       ← web search + doc fetch + LLM extraction
  (LangGraph DAG)         gpt-5 | Composio
       │
       ▼
[raw_pass1.json]        ← 100 structured records + confidence scores
       │
       ▼
[Verification Agent]    ← independently re-fetches evidence, re-derives answers
  (LangGraph DAG)         gpt-4o-mini (Never sees researcher's answers)
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

---

## Verification & Proof

The system maintains a comprehensive log of its execution and generates a detailed HTML report for review.

- **Pipeline Log:** [View pipeline.log](./pipeline.log)
- **Final Report:** [View report.html](./report.html)

### Pipeline Run Proof

Below is the execution summary demonstrating a complete and successful run of all 100 applications, including pass 1 vs pass 2 verifications and final metrics:

![Pipeline Final Output](./pipeline_proof.png)

*(Note: The above image placeholder points to `pipeline_proof.png` in the repository root. Please ensure your attached screenshot is saved there with this name.)*

```text
=== Final Verification Summary ===
Total Apps Processed: 100
Total Corrected: 65
Total Failed: 1
Average Confidence: 0.87
Pass1 -> Pass2 match: 35.0%

Phase 3: Generating insights...
INFO        💡 Insights saved -> E:\api-research\output\insights.json

Pipeline complete!
Auth dominant: API Key
Buildable today: 87/100
Easy wins: 65
MCP coverage: 30/100
Avg confidence: 0.87
```

---

## Composio SDK Usage

The pipeline primarily relies on **Composio as the tool-execution layer** for web search and URL fetching operations.

```python
from composio import Composio
from composio_langchain import LangchainProvider

composio = Composio(
    provider=LangchainProvider(),
    api_key=COMPOSIO_API_KEY
)

session = composio.create(
    user_id=COMPOSIO_USER_ID, # Ensure this matches your playground bound user
    manage_connections={
        "wait_for_connections": True,
    },
)

tools = session.tools()  # LangChain-compatible tool list
```

**What tools are used?**
- **Search**: We fuzzy-match the available tools for `TAVILY_SEARCH` or equivalent `search` tools.
- **Fetch**: We fuzzy-match for `BROWSER_FETCH`, `scrape`, or equivalent fetching tools.

If Composio is unavailable (e.g., API key not set, playground user ID mismatch, or rate limits), the pipeline falls back gracefully to `TavilyClient` for search and `httpx` + `BeautifulSoup4` for content fetching.

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
#   GITHUB_TOKEN      (required)    - For GitHub Models (gpt-5, gpt-4o-mini)
#   OPENAI_API_KEY    (optional)    - Fallback LLM provider
#   TAVILY_API_KEY    (recommended) - Web search
#   COMPOSIO_API_KEY  (optional)    - Composio SDK tools
```

### 3. Run the full pipeline

```bash
python main.py run
```

This runs all stages end-to-end and produces the `report.html`.

### 4. View the report

Open `report.html` in any browser — it's fully self-contained.

---

## CLI Commands

```bash
# Full pipeline (research → verify → insights → report)
python main.py run

# Research only (faster, no verification)
python main.py research

# Verify existing pass-1 results
python main.py verify

# Generate insights from verified results
python main.py insights

# Generate HTML report
python main.py report

# Export to CSV
python main.py export

# Skip verification (faster, less accurate)
python main.py run --skip-verify
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
| `pipeline.log` / `logs/pipeline.log` | Full execution logs |

---

## Verification Methodology

1. **Pass 1** — Research agent extracts from web search + docs using `gpt-5`.
2. **Pass 2** — Verifier agent re-fetches the same evidence URL independently using `gpt-4o-mini`.
3. The verifier uses a different system prompt and **never sees the researcher's answers**.
4. Corrections are applied based on confidence scores.
5. Remaining `needs-human` rows are **flagged, not hidden**.

This structure ensures a robust and measurable accuracy delta from Pass 1 to Pass 2.
