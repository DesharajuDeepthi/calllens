# Phase 6: Final README Template

## 🎯 PURPOSE

The README is what reviewers read **first**. It must:
- Explain what the project does (1 paragraph)
- Show how to run it (so they can reproduce)
- Document key decisions (so they understand your thinking)
- Acknowledge limitations (so they trust your judgment)
- Outline scaling/production vision (for the AI engineer role)

**Time budget:** 1 hour

---

## 📋 TEMPLATE — Copy this to `README.md` and fill in

```markdown
# Transcript Intelligence

Extracts insights from 100 B2B SaaS meeting transcripts. Categorizes meetings by 
call type, surfaces sentiment trends, identifies churn risks, tracks action items, 
and detects recurring topics across the corpus.

Built as a take-home assignment for the Applied AI Developer role at [Company].

---

## 🚀 Quick Start

### Setup

```bash
# Clone or unzip the project
cd transcript-intelligence

# Install dependencies (Python 3.10+)
pip install -r requirements.txt

# Set API key (Anthropic Claude)
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### Run the full pipeline

```bash
# Option 1: Jupyter notebook (recommended for review)
jupyter notebook notebooks/analysis.ipynb
# Then: Cell → Run All

# Option 2: Run individual modules from command line
python -m src.loader        # Load and flatten meetings
python -m src.categorize    # Categorize all meetings  
python -m src.sentiment     # Generate sentiment report
python -m src.churn_scorer  # Score churn risk
python -m src.action_tracker
python -m src.topic_analyzer
```

### What gets generated

- `outputs/meetings_flat.csv` — Full flattened dataset
- `outputs/categorized.csv` — With assigned call_type / sub_theme
- `outputs/sentiment_report.json` — Full sentiment analysis
- `outputs/churn_rankings.json` — Ranked at-risk accounts
- `outputs/action_items.csv` — All extracted action items
- `outputs/charts/*.html` — Interactive Plotly charts
- `outputs/charts/*.png` — Static images (if kaleido installed)

---

## 📊 What This Does

### Required Tasks (Per Assignment)

1. **Categorization Pipeline** (`src/categorize.py`)
   - Assigns `call_type`: support / external / internal
   - Assigns `sub_theme`: incident_response, customer_renewal, compliance_security, etc.
   - **Hybrid approach:** rule-based regex (free, ~70% of cases) + Claude Haiku fallback for ambiguous titles
   - Confidence scoring on every result for human review

2. **Sentiment Analysis** (`src/sentiment.py`)
   - Aggregates pre-computed sentiment scores by call type, sub-theme, time
   - Identifies negative/positive outliers with evidence
   - Generates interpretable findings (not just charts)

### Bonus Insights

3. **Churn Risk Scoring** (`src/churn_scorer.py`)
   - Ranks customer accounts by churn risk
   - Combines: churn_signal moments + sentiment trends + concerns + recent negativity
   - Returns evidence (quoted moments) for each score

4. **Action Item Tracker** (`src/action_tracker.py`)
   - Parses 4 action items per meeting (avg) into owner + verb + deadline
   - Identifies owner workload imbalance
   - Surfaces recurring action themes (= unresolved systemic issues)

5. **Recurring Topic Analyzer** (`src/topic_analyzer.py`)
   - Finds topics appearing in 3+ meetings
   - Correlates topics with sentiment (which topics drag mood down?)
   - Detects co-occurring topics
   - Plots topic timelines

---

## 🏗️ Architecture

### Module structure

```
src/
├── loader.py          # Loads 100 meeting folders → flat DataFrame
├── categorize.py      # Hybrid rule + LLM categorization
├── sentiment.py       # Sentiment aggregation + trends
├── churn_scorer.py    # Customer churn risk scoring
├── action_tracker.py  # Action item extraction + patterns
├── topic_analyzer.py  # Recurring topic detection
└── utils.py           # Helpers (LLM client, caching)
```

### Design principles

- **Tool-shaped functions:** Each insight is a callable with typed inputs and 
  a structured dict output. This is the natural foundation for an MCP tool 
  layer in a future agentic system.
- **Leverage pre-computed data:** `summary.json` already has summaries, topics, 
  sentiment, and tagged key moments. We use these as inputs rather than 
  regenerating them. Saves ~$30 in API costs.
- **Transparent over opaque:** Heuristic scoring with evidence > black-box ML 
  without labeled training data.
- **Cost-aware:** Total LLM spend on this project is <$1. Rules handle ~70% 
  of categorization; LLM only for ambiguous cases (Haiku model).

---

## 🔑 Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM provider | Anthropic Claude | Cost-effective; Haiku for categorization, Sonnet for nuance if needed |
| Categorization | Hybrid (rules + LLM) | Rules handle obvious patterns for free; LLM for ambiguous cases; explainable |
| Sentiment | Trust pre-computed scores | Re-running with different model = $30+ for likely similar results |
| Churn scoring | Heuristic with weights | No labeled churn data → can't train ML; transparent heuristic with evidence |
| Storage | pandas + CSV/JSON | Right tool for 100 docs; database is premature optimization |
| Charts | Plotly HTML | Interactive; can embed in notebook; static PNG fallback |
| Tests | Lightweight assertions | Show evals thinking without overbuilding for prototype |

---

## 📈 Findings Summary

*(Fill in after running)*

- **Categorization:** X% support / Y% external / Z% internal. Most common sub-theme: ____.
- **Sentiment:** ____ calls are most negative (avg ____); ____ calls are most positive (____).
- **Sentiment trend:** ____ over the analyzed period.
- **Top churn risk:** ____ accounts flagged Critical or Alert.
- **Action items:** ____ total, with ____ owners. Most overloaded: ____.
- **Recurring topics:** Top 3 = ____, ____, ____.

---

## ⚠️ Limitations

1. **No labeled ground truth** — Categorization validated by manual spot-check, not held-out test data
2. **Heuristic churn scoring** — No actual churn outcomes to train on; weights are based on judgment
3. **Single-document analysis** — No cross-meeting threading (same customer over time)
4. **Pre-computed dependency** — Quality of downstream analysis depends on `summary.json` quality from upstream pipeline
5. **No batch optimization** — Sequential LLM calls; OK for 100 docs, would batch for 10k+

---

## 🚢 Production / Scaling Notes

This prototype is a **static analytics pipeline**. The assignment description 
specifies different stakeholders need different information — that's an 
**agentic system problem**, not a dashboard problem.

### What this becomes in production

Each function in `src/` is shaped to become an MCP tool. Production architecture:

1. **MCP tool layer** — Wrap each analysis function as a versioned, tested MCP tool
2. **Stakeholder-specific agents** — Sales agent (uses churn + sentiment tools), 
   Support agent (uses pattern + action item tools), Eng agent (uses topic + 
   incident tools), etc.
3. **Governance layer** — RBAC on tools (sales agent can't query internal eng 
   meetings), PII filtering, audit logging, data lineage tracking
4. **Observability** — Trace every agent step (Langfuse-style), track cost per 
   query, P95 latency, alerting on regressions
5. **Eval framework** — Regression tests per stakeholder's query set, adversarial 
   safety tests, citation correctness checks

### What I did NOT build

- ❌ Agent orchestration (LangGraph, Claude Agent SDK)
- ❌ MCP server implementation
- ❌ RBAC / governance infrastructure
- ❌ Observability stack (Langfuse, etc.)
- ❌ Full eval framework

**Why:** For 100 meetings, this is overkill. The right scope for a take-home 
is solid analytics with code shaped to support the transition.

### Scaling at-a-glance

| Dataset Size | Architecture |
|--------------|--------------|
| **100 meetings** (this prototype) | pandas + CSV + scripts |
| **10k meetings** | Add caching, batch LLM calls, store in PostgreSQL |
| **100k+ meetings** | Vector DB for semantic search, streaming pipeline, full MCP+agent architecture |

---

## 🧪 Tests

```bash
# Lightweight validation
python -m pytest tests/
```

Tests cover:
- Loader: All 100 meetings load, schema is correct
- Categorizer: Rules vs LLM split, confidence distribution
- Churn scorer: Account name extraction, score range bounds

---

## 📦 Tech Stack

- **Python 3.10+**
- **pandas, numpy** — Data manipulation
- **plotly** — Interactive charts
- **anthropic** — Claude API (Haiku for cost-effective categorization)
- **python-dotenv** — Environment management
- **jupyter** — Notebook delivery

---

## 📁 Project Structure

```
transcript-intelligence/
├── README.md                       # This file
├── requirements.txt
├── .env.example
├── data/
│   └── dataset/                    # 100 meeting folders (input)
├── src/                            # Core modules
│   ├── loader.py
│   ├── categorize.py
│   ├── sentiment.py
│   ├── churn_scorer.py
│   ├── action_tracker.py
│   ├── topic_analyzer.py
│   └── utils.py
├── notebooks/
│   └── analysis.ipynb              # Main deliverable
├── outputs/                        # Generated artifacts
│   ├── *.csv, *.json
│   └── charts/
└── tests/
```

---

## 👤 Author

[Your Name] | [Your Email]

Built in ~12 hours over 2 days for the Applied AI Developer interview.
```

---

## ✅ ACCEPTANCE CRITERIA

1. ✅ Someone can `pip install -r requirements.txt && jupyter notebook` and reproduce all outputs
2. ✅ Every major decision has a documented rationale
3. ✅ Limitations are explicitly stated (shows intellectual honesty)
4. ✅ Production vision is articulated but **not over-claimed** (you didn't build it)
5. ✅ Findings summary is filled in with real numbers from the analysis

---

## 💡 README PHILOSOPHY

The README does double duty:
- **Functional:** Lets reviewers run the code and understand outputs
- **Strategic:** Positions your thinking for the AI engineer role

The "Production / Scaling Notes" section is **critical** — it's where you 
connect the analytics prototype to the agentic system vision without 
overclaiming what you built.
