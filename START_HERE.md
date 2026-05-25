# 🚀 START HERE — Project Build Order for Claude Code

You are Claude Code building the **Transcript Intelligence** take-home project for an 
Applied AI Developer interview. This file is your master plan.

---

## 📚 Documents to Read (in order)

These specification files exist in this directory. Read them as you build:

1. **`CLAUDE.md`** — Master spec. Read FIRST. Understand the whole project.
2. **`PHASE_1_LOADER.md`** — Build `src/loader.py` (30 min)
3. **`PHASE_2_CATEGORIZE.md`** — Build `src/categorize.py` (2 hrs)
4. **`PHASE_3_SENTIMENT.md`** — Build `src/sentiment.py` (1.5 hrs)
5. **`PHASE_4_CHURN.md`** — Build `src/churn_scorer.py` (2 hrs)
6. **`PHASE_4_ACTIONS.md`** — Build `src/action_tracker.py` (1.5 hrs)
7. **`PHASE_4_TOPICS.md`** — Build `src/topic_analyzer.py` (1.5 hrs)
8. **`PHASE_5_NOTEBOOK.md`** — Build `notebooks/analysis.ipynb` (1.5 hrs)
9. **`PHASE_6_README.md`** — Build `README.md` (1 hr)
10. **`PHASE_7_SLIDES.md`** — Build slide deck content (2 hrs)

---

## ⏰ Recommended Execution Order

### Day 1 — Code (8 hrs)
- [ ] **Hour 1:** Read CLAUDE.md fully. Set up project structure, install deps.
- [ ] **Hour 1-2:** Implement `loader.py` (Phase 1). Run, verify 100 meetings load.
- [ ] **Hour 2-4:** Implement `categorize.py` (Phase 2). Run, verify distribution.
- [ ] **Hour 5-6:** Implement `sentiment.py` (Phase 3). Run, generate charts.
- [ ] **Hour 6-8:** Implement `churn_scorer.py` (Phase 4A). Run, validate top rankings.

### Day 2 — Bonuses + Deliverables (7 hrs)
- [ ] **Hour 1-2:** Implement `action_tracker.py` (Phase 4B).
- [ ] **Hour 2-3:** Implement `topic_analyzer.py` (Phase 4C).
- [ ] **Hour 3-5:** Build `notebooks/analysis.ipynb` (Phase 5). Run end-to-end.
- [ ] **Hour 5-6:** Write `README.md` (Phase 6).
- [ ] **Hour 6-7:** Build slide deck (Phase 7) — content first, formatting last.

### Day 2 evening (1-2 hrs)
- [ ] Record 5-7 min video walkthrough
- [ ] Final review: Run notebook from scratch, verify reproducibility

---

## 🎯 Quality Bar

For each module:
- ✅ Runs without errors on all 100 meetings
- ✅ Functions have type hints, docstrings, structured returns
- ✅ Outputs saved to `outputs/` directory
- ✅ Charts saved as HTML (PNG optional)
- ✅ Acceptance criteria in the Phase doc are met

For the project as a whole:
- ✅ Notebook runs Cell → Run All without errors
- ✅ README explains setup, decisions, scaling notes
- ✅ Slide deck tells a story (insights → meaning → vision)
- ✅ Code is modular, typed, documented
- ✅ Total LLM API spend <$5
- ✅ No agent/MCP/RBAC code (we did NOT build that — see CLAUDE.md)

---

## ⚠️ Critical "Don't Do" List

Read CLAUDE.md for the full list. Highlights:

- ❌ Don't build LangGraph / agent frameworks
- ❌ Don't build MCP servers
- ❌ Don't regenerate summaries with LLM (they exist in `summary.json`)
- ❌ Don't write a monolithic script
- ❌ Don't implement all bonus insights — pick the 3 specified
- ❌ Don't polish before end-to-end works
- ❌ Don't add a vector DB or RAG (premature for 100 docs)

---

## 🛠️ Environment Setup

### Prerequisites
- Python 3.10+
- Anthropic API key (set in `.env`)

### First steps when you start

```bash
# 1. Set up project structure
mkdir -p src notebooks outputs/charts tests data

# 2. Create requirements.txt
cat > requirements.txt << 'EOF'
pandas>=2.0
numpy>=1.24
plotly>=5.18
anthropic>=0.40
python-dotenv>=1.0
jupyter>=1.0
tqdm>=4.66
pytest>=7.4
kaleido>=0.2.1
EOF

# 3. Create .env.example
cat > .env.example << 'EOF'
ANTHROPIC_API_KEY=your_key_here
EOF

# 4. Install deps
pip install -r requirements.txt

# 5. Create empty src/__init__.py
touch src/__init__.py

# 6. Symlink or copy the dataset folder
# Assuming the unzipped dataset is at ./interview-assignment/dataset/
ln -s "$(pwd)/interview-assignment/dataset" data/dataset
```

---

## 📊 Expected Final Deliverables

When done, you should have:

```
transcript-intelligence/
├── README.md                       ✅ Phase 6
├── requirements.txt                ✅ Setup
├── .env.example                    ✅ Setup
├── data/dataset/                   📂 100 meeting folders
├── src/
│   ├── __init__.py
│   ├── loader.py                   ✅ Phase 1
│   ├── categorize.py               ✅ Phase 2
│   ├── sentiment.py                ✅ Phase 3
│   ├── churn_scorer.py             ✅ Phase 4A
│   ├── action_tracker.py           ✅ Phase 4B
│   ├── topic_analyzer.py           ✅ Phase 4C
│   └── utils.py                    (helpers if needed)
├── notebooks/
│   └── analysis.ipynb              ✅ Phase 5
├── outputs/
│   ├── meetings_flat.csv
│   ├── categorized.csv
│   ├── sentiment_report.json
│   ├── churn_rankings.json
│   ├── action_items.csv
│   ├── action_items_report.json
│   ├── topic_report.json
│   └── charts/                     📊 8-10 HTML charts
└── slides/
    └── presentation.pdf            ✅ Phase 7 (built in Google Slides/Keynote/etc.)
```

---

## 🎤 For Q&A Prep

Each Phase doc has a "Q&A PREP" section at the end. Read all of them before the interview.

Critical talking points:
- **Why hybrid categorization** (cost + transparency)
- **Why trust pre-computed sentiment** (don't re-do upstream work)
- **Why heuristic churn scoring** (no labels for ML)
- **Why no agents/MCP** (right scope for 100 docs; designed for future transition)
- **Production vision** (5-week buildout; the foundation is here)

---

## 🚦 Sanity Checks

Before declaring done, verify:

1. `python -m src.loader` runs cleanly → 100 meetings loaded
2. `python -m src.categorize` runs cleanly → all categorized, distribution reasonable
3. `python -m src.sentiment` runs cleanly → charts in `outputs/charts/`
4. `python -m src.churn_scorer` runs cleanly → ranked accounts
5. `python -m src.action_tracker` runs cleanly → action items extracted
6. `python -m src.topic_analyzer` runs cleanly → recurring topics found
7. Notebook runs Cell → Run All without errors
8. `cat outputs/*.json` shows real data, not empty files
9. README is filled in with real numbers from the analysis
10. You've drafted the slides with content (formatting can come last)

---

## 💡 If You Get Stuck

- **Module fails:** Check the relevant Phase doc — it has full code templates
- **API errors:** Check `.env` has valid `ANTHROPIC_API_KEY`
- **Distribution looks wrong:** Re-read Phase docs' acceptance criteria
- **Running out of time:** Skip Phase 4B or 4C (drop one bonus) — never skip Phase 5 (notebook)

---

## ⏭️ Start Now

1. Read `CLAUDE.md` end-to-end
2. Then read `PHASE_1_LOADER.md`
3. Build `src/loader.py`
4. Verify it works
5. Move to Phase 2

Don't read all phases before starting. Read → build → verify → next phase.

Good luck. You have everything you need.
