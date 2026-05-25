# Transcript Intelligence

Extracts insights from 100 B2B SaaS meeting transcripts. Categorizes meetings by
call type, surfaces sentiment trends, identifies churn risks, tracks action items,
and detects recurring topics across the corpus.

Built as a take-home assignment for an Applied AI Developer role.

---

## Quick Start

### With Docker (recommended)

```bash
# 1. Copy and fill in your API key
cp .env.example .env
# Edit .env: set OPENAI_API_KEY=<your key>

# 2. Run the full pipeline
docker compose run --rm pipeline

# 3. Launch Jupyter to explore the notebook
docker compose up jupyter
# → open http://localhost:8888
```

### Without Docker (Python 3.10+)

```bash
pip install -r requirements.txt
cp .env.example .env  # add OPENAI_API_KEY

# Run pipeline modules (from project root)
python -m src.loader
python -m src.categorize
python -m src.sentiment
python -m src.churn_scorer
python -m src.action_tracker
python -m src.topic_analyzer

# Or open the notebook
jupyter notebook notebooks/analysis.ipynb
# → Cell → Run All
```

### Run tests

```bash
# With Docker
docker compose run --rm test

# Without Docker
pytest tests/ -v
```

### Run the MCP Server (Claude Desktop integration)

```bash
# 1. Start the MCP container
docker-compose up -d mcp

# 2. Add to Claude Desktop config at:
# ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "transcript-intelligence": {
      "command": "/usr/local/bin/docker",
      "args": ["exec", "-i", "transcript-intelligence", "python", "-m", "mcp_server.server"]
    }
  }
}

# 3. Restart Claude Desktop — look for the hammer icon
```

**Available MCP tools:**
| Tool | Description |
|------|-------------|
| `score_churn_risk` | Rank accounts by churn risk score |
| `search_meetings` | Keyword search across all 100 meetings |
| `get_sentiment_trends` | Sentiment by call type, sub-theme, or week |
| `find_recurring_topics` | Topics appearing in 3+ meetings |
| `get_action_items` | Filter action items by owner or keyword |

---

## What Gets Generated

| File | Description |
|------|-------------|
| `outputs/meetings_flat.csv` | Flattened dataset (one row per meeting) |
| `outputs/categorized.csv` | With call_type + sub_theme assigned |
| `outputs/sentiment_report.json` | Full sentiment analysis with insights |
| `outputs/churn_rankings.json` | Ranked at-risk accounts with evidence |
| `outputs/action_items.csv` | All extracted + parsed action items |
| `outputs/action_items_report.json` | Owner workload + recurring themes |
| `outputs/topic_report.json` | Recurring topics + sentiment correlation |
| `outputs/charts/*.html` | 11 interactive Plotly charts |

---

## What This Does

### Required Tasks

**1. Categorization** (`src/categorize.py`)
- Assigns `call_type`: `support` / `external` / `internal`
- Assigns `sub_theme`: `incident_response`, `customer_renewal`, `compliance_security`, etc.
- Hybrid: rule-based regex (91% of cases, free) + gpt-4o-mini fallback for ambiguous titles
- Confidence score on every result; flags low-confidence for review

**2. Sentiment Analysis** (`src/sentiment.py`)
- Aggregates pre-computed sentiment scores by call type, sub-theme, and week
- Negative/positive outliers with evidence
- Correlation with meeting characteristics (duration, participants, action count)
- 4 interactive charts

### Bonus Insights

**3. Churn Risk Scoring** (`src/churn_scorer.py`)
- Ranks customer accounts by churn risk (0–100 score)
- Combines: `churn_signal` key moments + sentiment trend + concerns + recent negativity
- Returns evidence (quoted key moments) for every score — the human reviews, the tool ranks

**4. Action Item Tracker** (`src/action_tracker.py`)
- Parses all 397 action items into: owner + verb + deadline + meeting source
- Owner workload ranking (who is overloaded?)
- Recurring keyword themes across meetings (systemic unresolved issues)

**5. Recurring Topic Analyzer** (`src/topic_analyzer.py`)
- 47 topics appear in 3+ meetings (on a 100-meeting corpus)
- Sentiment correlation: which topics drag mood down?
- Weekly timeline of topic occurrences
- Co-occurrence pairs (e.g., compliance + renewal appear together 11 times)

---

## Findings Summary

| Dimension | Finding |
|-----------|---------|
| Categorization | 44% external, 29% internal, 27% support — 91% handled by rules |
| Sentiment by type | External: 3.68 avg (most positive), Support: 2.94 avg (most negative) |
| Sentiment trend | Flat over the Feb–Apr period (slope +0.012/week) |
| Top sub-theme | Incident response (56 meetings) — the company has been fighting fires |
| Churn risk | 13 Critical, 3 Alert, 6 Watch, 18 Healthy |
| Top churn signals | Northstar Pharma, Summit Trust, Vanta Health Systems |
| Action items | 397 total, ~4/meeting; Maria Santos most loaded (31 items) |
| Top recurring topics | compliance (23 meetings), compliance reporting (19), renewal (17) |
| Most sentiment-negative topics | churn risk (2.12), SLA breach (2.13), incident communication (2.16) |

---

## Architecture

### Module structure

```
src/
├── loader.py          # Loads 100 meeting dirs → flat pandas DataFrame
├── categorize.py      # Hybrid rule + LLM categorization
├── sentiment.py       # Sentiment aggregation, trends, charts
├── churn_scorer.py    # Customer churn risk scoring with evidence
├── action_tracker.py  # Action item extraction + workload + themes
└── topic_analyzer.py  # Recurring topic detection + sentiment + timeline
```

### Design principles

- **Tool-shaped functions:** Each insight function takes typed parameters and returns
  a structured dict with provenance (meeting IDs). Natural foundation for MCP tools.
- **Use pre-computed data:** `summary.json` already has summaries, topics, sentiment,
  and tagged key moments. We aggregate these rather than regenerating — saves ~$30.
- **Transparent over opaque:** Heuristic churn scoring with component breakdown + quoted
  evidence beats a black-box ML model when there's no labeled training data.
- **Cost-aware:** Total LLM spend on this project is under $1. Rules handle 91% of
  categorization; LLM only for the remaining 9 ambiguous cases.

---

## Key Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Categorization | Hybrid (rules + LLM) | Rules are free and transparent; LLM handles semantic ambiguity |
| LLM for categorization | gpt-4o-mini | Cheap (~$0.001/call), accurate enough for short meeting titles |
| Sentiment | Trust pre-computed scores | Re-running = $30+ for likely similar signal; validate by sampling instead |
| Churn scoring | Heuristic + evidence | No labeled churn data; heuristic is explainable and auditable |
| Storage | pandas + CSV/JSON | Right tool for 100 docs; premature to add a DB |
| Charts | Plotly HTML | Interactive; embeds in notebook; PNG fallback via kaleido |
| Container | Docker | Reproducible across machines; no Python version surprises |

---

## Limitations

1. **No labeled ground truth** — Categorization validated by spot-check, not a held-out test set
2. **Heuristic churn scoring** — No actual churn outcomes; weights are based on judgment
3. **No cross-meeting threading** — Each meeting analyzed in isolation; no customer journey view
4. **Pre-computed dependency** — Downstream quality depends on upstream `summary.json` quality
5. **No batch LLM calls** — Sequential; fine for 100 docs, would batch for 10k+

---

## Production / Scaling Vision

This is a **static analytics pipeline**. The assignment calls for different insights
for different stakeholders — that's an **agentic system problem**, not a dashboard problem.

### What this becomes in production

Each function in `src/` is shaped to become an MCP tool:

```
Stakeholder Agents (Sales | Support | Eng | PM | Exec)
        │ MCP protocol
        ▼
MCP Tool Layer
  • search_meetings(query, filters)
  • get_sentiment_trend(call_type, time_range)
  • score_churn_risk(account)
  • find_action_items(owner)
  • find_recurring_topics(min_count)
        │
Governance + Observability + Eval layers
  • RBAC per tool, PII filtering, audit log
  • Trace per query, cost tracking, Langfuse
  • Regression tests, adversarial safety
        │
Data layer (this prototype)
  100 meetings → flat DataFrame → categorized + scored
```

**Estimated buildout: ~5 weeks from this foundation**
- Weeks 1–2: MCP tool wrappers
- Week 3: Governance (RBAC, PII, audit log)
- Week 4: Observability (traces, cost, latency)
- Week 5: Role-specific agents + eval suite

### Scaling at a glance

| Scale | Architecture |
|-------|-------------|
| 100 meetings (this) | pandas + CSV + scripts |
| 10k meetings | PostgreSQL, batch LLM calls, caching |
| 100k+ meetings | Vector DB for semantic search, streaming pipeline, full MCP+agent |

---

## Tech Stack

- **Python 3.11** in Docker
- **pandas, numpy** — Data manipulation
- **plotly** — Interactive charts (HTML + PNG)
- **openai** — gpt-4o-mini for LLM categorization fallback
- **python-dotenv** — Environment management
- **jupyter** — Notebook delivery
- **pytest** — Lightweight validation tests

---

## Project Structure

```
transcript-intelligence/
├── README.md
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── data/
│   └── dataset/              # 100 meeting folders (symlinked)
├── src/
│   ├── loader.py
│   ├── categorize.py
│   ├── sentiment.py
│   ├── churn_scorer.py
│   ├── action_tracker.py
│   └── topic_analyzer.py
├── notebooks/
│   └── analysis.ipynb        # Main deliverable — runs end-to-end
├── outputs/
│   ├── *.csv, *.json
│   └── charts/               # 11 interactive HTML charts
└── tests/
    └── test_categorize.py
```
