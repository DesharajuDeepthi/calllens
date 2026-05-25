# Phase 5: Jupyter Notebook (`notebooks/analysis.ipynb`)

## 🎯 PURPOSE

The notebook is **the technical reference deliverable** the panel will review. It must:
- Run end-to-end without errors (Cell → Run All)
- Tell the story in order (loader → categorize → sentiment → bonus insights → vision)
- Have markdown cells explaining decisions
- Embed charts inline
- Be readable by a non-author (the reviewer)

**Time budget:** 1.5 hours (mostly assembling outputs from prior phases)

---

## 📋 NOTEBOOK STRUCTURE

Organize as 8 sections with markdown headers. Each section calls into `src/` modules — the notebook itself is thin.

---

### Section 0: Title + Setup

```markdown
# Transcript Intelligence — Analysis Notebook

**Author:** [Your Name]
**Dataset:** 100 meeting transcripts (B2B SaaS company "Aegis")
**Date:** [Today]

## What this notebook covers
1. Data exploration (Phase 1)
2. Required Task 1: Topic categorization
3. Required Task 2: Sentiment analysis
4. Bonus Insight A: Churn risk scoring
5. Bonus Insight B: Action item tracker
6. Bonus Insight C: Recurring topic detector
7. Production architecture vision
8. Limitations & next steps
```

```python
# Cell: imports
import sys
sys.path.insert(0, "..")

import pandas as pd
import json
from pathlib import Path

from src.loader import load_meetings, quick_stats
from src.categorize import categorize_meetings, review_low_confidence
from src.sentiment import generate_sentiment_report
from src.churn_scorer import score_all_accounts, add_account_column, chart_top_risk_accounts, chart_risk_components
from src.action_tracker import generate_action_items_report
from src.topic_analyzer import generate_topic_report

# Display config
pd.set_option("display.max_colwidth", 100)
pd.set_option("display.max_rows", 20)
```

---

### Section 1: Data Exploration

```markdown
## 1. Dataset Overview

We load 100 meeting transcripts from `data/dataset/`. Each meeting has 6 JSON files:
- `meeting-info.json` — Title, duration, participants
- `transcript.json` — Per-sentence transcript with timestamps
- `summary.json` — **Pre-computed** summary, action items, topics, sentiment, key moments
- `speakers.json`, `speaker-meta.json`, `events.json` — Speaker timeline

### Key decision: Leverage pre-computed fields

The dataset already includes summarized topics, sentiment scores, and tagged 
key moments (`churn_signal`, `technical_issue`, `concern`, `positive_pivot`). 
I'll build **on top of these**, not regenerate them. This saves ~$30 in API 
costs and shows pragmatism — don't re-do work that's already done.
```

```python
df = load_meetings()
stats = quick_stats(df)
df.head()
```

```python
# Show a sample meeting with everything we have on it
sample = df.iloc[0]
print(f"Title: {sample['title']}")
print(f"Duration: {sample['duration_min']:.1f} min")
print(f"Topics: {sample['topics']}")
print(f"Sentiment: {sample['overall_sentiment']} ({sample['sentiment_score']})")
print(f"Action items: {len(sample['action_items'])}")
print(f"Key moments: {sample['key_moment_types']}")
```

---

### Section 2: Required Task 1 — Categorization

```markdown
## 2. Categorization (Required Task 1)

**Goal:** Assign each meeting a call_type (`support` / `external` / `internal`) and 
a sub-theme (e.g., `incident_response`, `customer_renewal`, `compliance_security`).

### Approach: Hybrid (rules + LLM)

| Method | Use case | Cost |
|--------|----------|------|
| Rule-based | Obvious patterns ("Support Case #", "Standup", "Aegis / X -") | Free |
| LLM (Claude Haiku) | Ambiguous titles requiring semantic understanding | ~$0.003/call |

### Why hybrid?
- Rules handle ~70% for free with full transparency
- LLM handles the rest with semantic nuance
- Confidence scoring flags cases needing human review
- Easier to debug than pure LLM (when wrong, regex is inspectable)
```

```python
df = categorize_meetings(df)
df[["meeting_id", "title", "call_type", "sub_theme", "category_confidence", "category_method"]].head(10)
```

```python
# Distribution check
print("Call type distribution:")
print(df["call_type"].value_counts())
print("\nSub-theme distribution:")
print(df["sub_theme"].value_counts())
```

```python
# Review low-confidence cases (our "eval-lite")
low_conf = review_low_confidence(df, threshold=0.7)
```

```markdown
### Quality check

I'll manually inspect 10 randomly-sampled meetings to validate categorization:
```

```python
sample = df.sample(10, random_state=42)[["title", "call_type", "sub_theme", "category_confidence"]]
sample
```

```markdown
**Observation:** [Write 2-3 sentences after running, noting how many look right]
```

---

### Section 3: Required Task 2 — Sentiment

```markdown
## 3. Sentiment Analysis (Required Task 2)

**Goal:** Aggregate sentiment across call types, sub-themes, and time. Surface 
*interpretations*, not just numbers.

### Key decision: Trust the pre-computed sentiment

`summary.json` includes both `overallSentiment` (categorical) and `sentimentScore` 
(numeric 1-5). I trust these as inputs. Re-running sentiment with a different 
model would cost API budget for likely similar results.

In production, I'd validate by sampling 20 meetings, manually scoring them, 
and computing correlation. If it drops below ~0.8, re-score.
```

```python
sentiment_report = generate_sentiment_report(df)
```

```python
from IPython.display import HTML
HTML(filename="../outputs/charts/sentiment_by_call_type.html")
```

```python
HTML(filename="../outputs/charts/sentiment_over_time.html")
```

```python
HTML(filename="../outputs/charts/sentiment_heatmap.html")
```

```markdown
### Findings

[Use the insights from sentiment_report:]
- **By call type:** [insight]
- **By sub-theme:** [insight]
- **Over time:** [insight]
- **Vs. characteristics:** [insight]

### What this means for stakeholders
- **Support leaders:** [interpretation]
- **Sales managers:** [interpretation]
- **Engineering leads:** [interpretation]
```

```python
# Show negative outliers — these are leading indicators
print("Top 5 most negative meetings:\n")
for m in sentiment_report["negative_outliers"][:5]:
    print(f"  [{m['sentiment_score']:.1f}] {m['title']}")
    print(f"        Type: {m['call_type']} / {m['sub_theme']}")
    print(f"        Flags: churn={m['has_churn_signal']}, concern={m['has_concern']}")
    print()
```

---

### Section 4: Bonus A — Churn Risk Scoring

```markdown
## 4. Bonus Insight A: Churn Risk Scoring

**The most business-critical bonus insight.** Sales and CS leaders want to know:
which customers are at risk?

### Approach: Transparent heuristic scoring

I combine four signals:
1. **Churn signal key moments** (explicit dissatisfaction): 25 pts each, capped at 50
2. **Sentiment trend** (avg low + declining): up to 40 pts
3. **Concerns raised**: 5 pts each, capped at 20  
4. **Recent negativity**: 5-15 pts based on most recent meeting

**Risk levels:**
- 70+ → Critical (immediate exec outreach)
- 50-69 → Alert (check-in within a week)
- 30-49 → Watch (monitor closely)
- <30 → Healthy

### Why heuristic, not ML?
Without labeled churn data (who actually left), training a classifier isn't 
possible. The heuristic is transparent — every score has component breakdown 
and quoted evidence. **With churn labels, this becomes the feature set for a 
trained model.**
```

```python
df = add_account_column(df)
rankings = score_all_accounts(df)

print(f"Scored {len(rankings)} accounts.\n")
print("Top 5 highest-risk accounts:")
for r in rankings[:5]:
    print(f"  [{r['risk_score']:.0f}] {r['account']} — {r['risk_level']}")
    print(f"     {r['meeting_count']} meetings | Avg sentiment: {r['avg_sentiment']}")
    print(f"     Recommendation: {r['recommendation']}")
    print()
```

```python
chart_top_risk_accounts(rankings)
```

```python
chart_risk_components(rankings)
```

```python
# Show evidence for the #1 at-risk account
top_account = rankings[0]
print(f"Why is {top_account['account']} ranked highest?\n")
print("Evidence:")
for ev in top_account["evidence"][:3]:
    print(f"\n  [{ev['type']}] Meeting: {ev['title']}")
    print(f"  Speaker: {ev['speaker']}")
    print(f'  Quote: "{ev["quote"]}"')
```

---

### Section 5: Bonus B — Action Item Tracker

```markdown
## 5. Bonus Insight B: Action Item Tracker

Engineering leads, project managers, and chiefs of staff need cross-meeting 
visibility into:
- Who is overloaded with action items?
- What kinds of actions dominate (deliverables, communication, investigation)?
- Are certain themes recurring across meetings (= unresolved systemic issues)?
```

```python
action_report = generate_action_items_report(df)
```

```python
HTML(filename="../outputs/charts/owner_workload.html")
```

```python
HTML(filename="../outputs/charts/recurring_themes.html")
```

```markdown
### Findings

- **Workload imbalance:** [insight from report]
- **Action mode:** [insight — what verbs dominate]
- **Recurring themes:** [insight — what keeps coming up]
- **Action density:** [which meeting types produce action vs. discussion]

### Stakeholder value
- **Engineering leads:** Identify overloaded ICs before they burn out
- **PM/CoS:** Spot recurring themes that need a project, not more action items
- **Sales/CS leads:** Action items mentioning a customer = follow-up backlog
```

---

### Section 6: Bonus C — Recurring Topics

```markdown
## 6. Bonus Insight C: Recurring Topic Detector

Surface topics appearing across many meetings — these are leading indicators of 
either healthy patterns (e.g., recurring planning) or systemic problems (e.g., 
recurring outages).
```

```python
topic_report = generate_topic_report(df)
```

```python
HTML(filename="../outputs/charts/topic_frequency.html")
```

```python
HTML(filename="../outputs/charts/topic_sentiment.html")
```

```python
HTML(filename="../outputs/charts/topic_timeline.html")
```

```markdown
### Findings

- **Most recurring topics:** [from report]
- **Topics driving negativity:** [from report]
- **Co-occurring topics:** [from report]
- **Lifecycle observations:** [is anything trending up/down?]

### Stakeholder value
- **Product managers:** See what topics customers care about most
- **Engineering leads:** Spot recurring technical pain points
- **CEOs/Leadership:** Track strategic themes over time
```

---

### Section 7: From Static Analytics to Agentic Intelligence (Production Vision)

```markdown
## 7. Production Architecture: From Static Analytics → Agentic System

### What this prototype is
A static analytics pipeline that pre-computes insights for known questions.

### What it needs to become
The PDF says:
> *"each [stakeholder] would want something different from this tool."*

That's the giveaway: different users → different questions → different reasoning. 
**No single dashboard answers all of them.** This is an agentic system problem.

### Production architecture (what I'd build next, not in this prototype)

```
┌───────────────────────────────────────────────────────────────────────┐
│                     Stakeholder Agents                                │
│  Sales Agent | Support Agent | Eng Agent | PM Agent | Exec Agent      │
└──────────────────────────────┬────────────────────────────────────────┘
                               │ MCP protocol
                               ▼
┌───────────────────────────────────────────────────────────────────────┐
│                       MCP Tool Layer                                  │
│  (Each of my analysis functions becomes an MCP tool)                  │
│                                                                       │
│  • search_meetings(query, filters)                                    │
│  • get_sentiment_trend(call_type, time_range)                         │
│  • score_churn_risk(account, time_range)                              │
│  • find_action_items(owner, status)                                   │
│  • find_recurring_topics(min_count)                                   │
│  • get_meeting_summary(meeting_id)                                    │
└──────────────────────────────┬────────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Governance Layer │  │ Observability    │  │ Eval Framework   │
│ • RBAC per tool  │  │ • Trace per query│  │ • Regression     │
│ • PII filtering  │  │ • Cost tracking  │  │   tests          │
│ • Audit logging  │  │ • Latency P95    │  │ • Adversarial    │
│ • Data lineage   │  │ • Langfuse-style │  │   safety tests   │
└──────────────────┘  └──────────────────┘  └──────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────────────┐
│                      Data Layer (this prototype)                      │
│  100 meetings → flat DataFrame → categorized + scored + indexed       │
└───────────────────────────────────────────────────────────────────────┘
```

### Why each layer matters

- **Agents:** Sales asks "show me churn risk"; Support asks "what's recurring?" 
  Same data, different reasoning. Agents pick the right tools.
- **MCP:** Tools are reusable, versioned, tested. Salesforce or Slack could 
  consume the same MCP servers.
- **Governance:** Transcripts contain PII, deals, internal disputes. Sales agent 
  can't query internal eng meetings. Every action logged with data lineage.
- **Observability:** P95 latency, cost per query, trace per agent step. Catch 
  regressions before users notice.
- **Evals:** Adversarial tests (prompt injection), correctness (does agent cite 
  real meetings?), safety (no PII leaks).

### Honest scope note

I did **not** build the agent or MCP layers in this take-home. That's the 
right call for 100 meetings — agentic infrastructure is overkill at this scale.

What I **did** do that supports the transition:
- Each insight is a standalone function with clean inputs/outputs
- Outputs include provenance (meeting IDs) for citations
- Confidence scoring on categorization (foundation for evals)
- Pre-computed data leveraged (cost-aware design)

**To productionize:** Wrap each function as an MCP tool (~1 week), add the 
governance/obs layers (~2 weeks), build role-specific agents (~2 weeks). 
Maybe ~5-week buildout from this foundation.
```

---

### Section 8: Limitations & Next Steps

```markdown
## 8. Limitations & Next Steps

### What this prototype doesn't do
1. **No labeled ground truth** — Categorization quality validated by manual spot-check, not a held-out test set
2. **Heuristic churn scoring** — No actual churn data to train on
3. **Single-document analysis** — No cross-meeting threading (same customer over time)
4. **No real-time** — Batch pipeline only
5. **Pre-computed dependencies** — If `summary.json` quality drops, everything downstream degrades

### What I'd build next (in priority order)
1. **Labeled eval set** — Hand-label 30 meetings for categorization to track accuracy over time
2. **Customer thread linking** — Cluster meetings by customer name + email participants  
3. **Action item completion tracking** — Link follow-up meetings to determine which items closed
4. **MCP tool wrappers** — Convert each function to an MCP tool (foundation for agentic system)
5. **Sentiment validation eval** — Sample-validate the pre-computed sentiment scores

### What I'd push back on
- "Build the full agentic system" → I'd argue: prove value with analytics first, then automate the queries via agents
- "Use a vector DB" → Premature for 100 docs; metadata + pandas filtering is sufficient
- "Fine-tune a custom model" → Pre-computed signals + heuristics are good enough; ML when we have labels
```

---

## ✅ ACCEPTANCE CRITERIA

1. ✅ Notebook runs Cell → Run All without errors
2. ✅ All charts render inline
3. ✅ Each section has a markdown intro explaining the decision and a markdown summary explaining findings
4. ✅ Section 7 (production vision) is the differentiator for the AI engineer role
5. ✅ Section 8 (limitations) shows intellectual honesty
6. ✅ Total runtime: <5 minutes (most work pre-computed in saved JSON files)

---

## 💡 NOTEBOOK BEST PRACTICES

- **Don't paste code into the notebook.** Import from `src/`. The notebook orchestrates and narrates; the modules do the work.
- **Each section ends with a "What this means" markdown cell.** Insights, not just charts.
- **Use `HTML()` to embed plotly outputs** — better than re-rendering each time.
- **Print sparingly.** Don't dump 100-row DataFrames; show `.head(10)` or relevant slices.
- **Save outputs to `outputs/`.** The notebook should be reproducible after `Run All`.
