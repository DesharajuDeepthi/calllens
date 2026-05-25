# Transcript Intelligence — Project Specification for Claude Code

## 🎯 PROJECT OVERVIEW

You are building a **Transcript Intelligence** analytics system for a take-home interview assignment for an **Applied AI Developer** role at a B2B enterprise SaaS company.

**The goal:** Process ~100 meeting transcripts and extract meaningful insights for different stakeholders (support leaders, sales managers, product managers, engineering leads).

**Timeline:** 1-2 days. Do not over-engineer.

**Deliverables:**
1. Working Python pipeline (analytics)
2. Jupyter notebook for exploration + final outputs
3. 10-12 slide presentation (handled separately — code generates supporting charts)
4. Clean README with architecture notes

---

## 📁 INPUT DATA STRUCTURE

The data lives in `data/dataset/` with 100 subdirectories. Each subdirectory is one meeting with 6 JSON files:

```
data/dataset/{meeting_id}/
├── meeting-info.json    # Title, duration, participants, organizer, dates
├── transcript.json      # Full transcript with per-sentence sentiment + speaker
├── summary.json         # PRE-COMPUTED: summary, action items, topics, sentiment, key moments
├── speakers.json        # Speaker timeline (who spoke when)
├── speaker-meta.json    # Speaker ID → Name mapping
└── events.json          # Join/leave events
```

### 🔑 CRITICAL: The data has PRE-COMPUTED fields. USE THEM.

**`summary.json` already contains:**
- `summary` (text)
- `actionItems` (list of "Name: action" strings)
- `topics` (list of topic strings, ~6 per meeting)
- `overallSentiment` (e.g. "mixed-negative", "positive")
- `sentimentScore` (float, e.g. 2.4)
- `keyMoments` (list with `type` field including: `churn_signal`, `technical_issue`, `concern`, `positive_pivot`, etc.)

**Do not re-generate these with LLM calls.** Build ON TOP of them. This saves ~$30 in API costs and shows pragmatism.

### Sample meeting titles observed:
- "Detect Outage - Remediation Plan Review" (internal)
- "Support Case #9279 - Summit Trust Billing Inquiry" (support)
- "Weekly Engineering Standup" (internal)
- "Aegis / Redwood Clinical - ISO 27001 Preparation" (external)
- "Aegis / Cobalt Software - Q2 Planning" (external)

---

## 🏗️ ARCHITECTURE PRINCIPLES

### Build it as composable, tool-shaped functions (NOT a monolithic script)

Each insight is a separate function with:
- Clear typed parameters
- Structured dict output
- Provenance (meeting IDs in results)
- Good docstring

**Why:** This is *good Python design*. It also positions the code as a natural foundation for a future agentic system (where each function would become an MCP tool). But we are NOT building agents/MCP in this take-home — we're building clean analytics.

### Do NOT build (out of scope):
- ❌ LangGraph / agent frameworks
- ❌ MCP servers
- ❌ Vector databases / RAG
- ❌ Docker / Kubernetes
- ❌ Web dashboards (Streamlit — only if Phase 3 budget allows)
- ❌ Full eval frameworks (mention only)
- ❌ RBAC / production governance (mention only)
- ❌ Real-time streaming

### DO build:
- ✅ Clean modular Python (each module has one responsibility)
- ✅ Pandas DataFrame as primary data structure
- ✅ Plotly for charts (interactive HTML output)
- ✅ Pre-computed data as much as possible (only call LLM when truly needed)
- ✅ One Jupyter notebook that runs end-to-end and tells the story

---

## 📂 PROJECT STRUCTURE

Create this exact structure:

```
transcript-intelligence/
├── README.md                          # User-facing project doc
├── CLAUDE.md                          # This file (project spec)
├── requirements.txt                   # Python deps
├── .env.example                       # API key template
├── data/
│   └── dataset/                       # (Input data, already provided)
├── src/
│   ├── __init__.py
│   ├── loader.py                      # Load + flatten 100 meetings
│   ├── categorize.py                  # Hybrid categorization (rules + LLM)
│   ├── sentiment.py                   # Sentiment aggregation
│   ├── churn_scorer.py                # BONUS: Churn risk ranking
│   ├── action_tracker.py              # BONUS: Action item analysis
│   ├── topic_analyzer.py              # BONUS: Recurring topic detection
│   ├── charts.py                      # All Plotly chart generation
│   └── utils.py                       # LLM client, caching, helpers
├── notebooks/
│   └── analysis.ipynb                 # Main analysis notebook (the deliverable)
├── outputs/
│   ├── meetings_flat.csv              # Flattened dataset
│   ├── categorized.csv                # With categories assigned
│   ├── insights_report.json           # All findings in JSON
│   ├── charts/                        # All charts (HTML + PNG)
│   └── slides_data.json               # Data points used in slides
└── tests/
    └── test_categorize.py             # Lightweight validation tests
```

---

## 🎬 EXECUTION PLAN

Execute in this order. Each phase builds on the previous. **Do not skip ahead.**

### **Phase 1: Setup & Data Exploration** (45 min)
**Goal:** Understand the data, set up the project.

1. Create directory structure above
2. Write `requirements.txt`:
   ```
   pandas>=2.0
   numpy>=1.24
   plotly>=5.18
   anthropic>=0.40
   python-dotenv>=1.0
   jupyter>=1.0
   tqdm>=4.66
   ```
3. Create `.env.example` with `ANTHROPIC_API_KEY=your_key_here`
4. Write `src/loader.py` (see PHASE_1_LOADER.md for exact spec)
5. Run loader, confirm: 100 meetings loaded, no errors
6. Print basic stats: total meetings, total duration, date range, unique speakers, distribution of pre-computed sentiments

### **Phase 2: Required Task 1 — Categorization** (2 hours)
**Goal:** Categorize all 100 meetings into call types (support/external/internal).

1. Write `src/categorize.py` (see PHASE_2_CATEGORIZE.md for exact spec)
2. Implement HYBRID approach:
   - Rule-based first (fast, free, transparent for obvious cases)
   - LLM-based fallback for ambiguous cases (using Claude Haiku for cost)
   - Confidence scoring on every result
3. Run on all 100 meetings
4. Validate: distribution looks reasonable (rough expectation: 30-40% support, 30-40% external, 20-30% internal)
5. Manually review 10 random samples — does the categorization make sense?
6. Save `outputs/categorized.csv`

### **Phase 3: Required Task 2 — Sentiment Analysis** (1.5 hours)
**Goal:** Aggregate sentiment, find trends, interpret meaningfully.

1. Write `src/sentiment.py` (see PHASE_3_SENTIMENT.md for exact spec)
2. Aggregate at multiple levels:
   - Per meeting (use pre-computed `sentimentScore`)
   - Per call type
   - Per topic
   - Over time (weekly/monthly trends)
3. Generate plotly charts (saved to `outputs/charts/`):
   - Sentiment distribution by call type (box plot)
   - Sentiment over time (line chart)
   - Sentiment heatmap by topic × call type
4. Identify 3-4 *interpretable* trends. Write these as text findings (not just data).

### **Phase 4: Bonus Insights** (3-4 hours)
**Goal:** Stand-out insights beyond required tasks. Pick 3.

1. **Churn Risk Scorer** (`src/churn_scorer.py`) — see PHASE_4_CHURN.md
2. **Action Item Tracker** (`src/action_tracker.py`) — see PHASE_4_ACTIONS.md
3. **Recurring Topic Detector** (`src/topic_analyzer.py`) — see PHASE_4_TOPICS.md

### **Phase 5: Notebook Assembly** (1.5 hours)
**Goal:** The main deliverable that tells the story.

1. Create `notebooks/analysis.ipynb` (see PHASE_5_NOTEBOOK.md for outline)
2. Structure: each section uses the modules built in Phases 1-4
3. Markdown cells explain decisions and findings
4. Charts embedded inline
5. Final section: "Production Architecture Vision" — explain what this becomes at scale

### **Phase 6: README & Polish** (1 hour)
**Goal:** Documentation that earns trust.

1. Write `README.md` (see PHASE_6_README.md for template)
2. Include: setup instructions, architecture diagram, decisions, scaling notes
3. Run notebook end-to-end one more time, confirm reproducibility

---

## 🎯 KEY DECISIONS (Why Each Choice)

These will come up in Q&A. Be ready to justify.

| Decision | Choice | Why |
|----------|--------|-----|
| Language | Python | Standard for AI/data; required by JD |
| LLM | Claude (Haiku for cheap, Sonnet for nuance) | Cost-effective hybrid; aligns with role |
| Categorization | Hybrid (rules + LLM) | Rules handle obvious cases free; LLM for ambiguous |
| Storage | Pandas in-memory + CSV | Right tool for 100 docs; not premature DB optimization |
| Charts | Plotly | Interactive HTML; can be embedded in slides |
| Tests | Lightweight pytest | Show eval thinking without overbuilding |
| Pre-computed fields | Use them | $30 savings; shows pragmatism |

---

## 💰 COST BUDGET

Total LLM API spend should be **under $5**. Track it.

- Categorization: 100 meetings × ~$0.003 (Haiku) = $0.30
- Validation/sampling: 10-20 calls × ~$0.01 (Sonnet) = $0.20
- Buffer for iteration: ~$2

If you're going over $5, stop and reconsider. Something is wrong.

---

## ⚠️ FAILURE MODES TO AVOID

1. **Trying to build an agent.** Don't. This is analytics.
2. **Regenerating summaries with LLM.** They're already there. Use them.
3. **Monolithic script.** Build modular from day 1.
4. **Skipping the notebook.** The notebook IS the deliverable.
5. **Over-formatting charts.** Plotly defaults are fine.
6. **Implementing all bonus ideas.** Pick 3, do them well.
7. **Polishing too early.** Get end-to-end working first, then polish.

---

## 🔄 EXECUTION ORDER

Read these files in order:

1. **CLAUDE.md** (this file) — overall spec
2. **PHASE_1_LOADER.md** — data loading module spec
3. **PHASE_2_CATEGORIZE.md** — categorization module spec
4. **PHASE_3_SENTIMENT.md** — sentiment analysis module spec
5. **PHASE_4_CHURN.md** — churn scorer spec
6. **PHASE_4_ACTIONS.md** — action item tracker spec
7. **PHASE_4_TOPICS.md** — topic analyzer spec
8. **PHASE_5_NOTEBOOK.md** — notebook structure
9. **PHASE_6_README.md** — final README template

---

## ✅ DEFINITION OF DONE

- [ ] All 100 meetings load without errors
- [ ] Categorization runs end-to-end, results saved
- [ ] Sentiment trends identified and charted
- [ ] 3 bonus insights implemented
- [ ] Jupyter notebook runs end-to-end (Run All → no errors)
- [ ] README explains setup, decisions, scaling notes
- [ ] All charts saved to `outputs/charts/`
- [ ] Total API spend under $5
- [ ] Code is modular, typed, documented
- [ ] No agent/MCP/RBAC code (just clean analytics)

---

## 🎤 INTERVIEW POSITIONING

In the presentation and Q&A, frame the work as:

**What you built:** Production-quality analytics pipeline. Modular, tested, documented.

**What's next (you didn't build, but designed for):** The functions are tool-shaped. In a production agentic system, each would become an MCP tool. Different stakeholders (sales, support, eng) would have role-specific agents composing these tools. Governance via RBAC, observability via Langfuse, evals via regression tests.

**Why this scope is right:** For 100 transcripts, an agentic system is overkill. The analytics foundation is what matters. Productionizing to agents is Phase 2.

**Be honest:** Don't claim you built agent tools. You built analytics functions that *could become* agent tools with more work.
