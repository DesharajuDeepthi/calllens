# Phase 7: Slide Deck Content Guide

## 🎯 PURPOSE

12 slides for the 30-minute presentation to product + engineering leadership.

**Format:** Lead with insights, not code. Tell a story.

**Time budget:** 2 hours to build (after analysis is done)

---

## 📋 SLIDE-BY-SLIDE STRUCTURE

### Slide 1: Title
- **Title:** Transcript Intelligence: From Meeting Data to Stakeholder Decisions
- **Subtitle:** Take-home assignment | [Your Name]
- **Visual:** Simple, clean

---

### Slide 2: The Opportunity
**Question:** Why does this product matter?

**Content:**
- 100 meeting transcripts → buried insights about customers, ops, product
- Different stakeholders ask different questions
- Today: insights are reactive, slow, manual
- Vision: insights are proactive, fast, surfaced automatically

**Visual:** A 2-column layout showing "Today" (manual review) vs "With Transcript Intelligence" (instant answers)

---

### Slide 3: The Dataset
**Content:**
- 100 meetings across multiple call types (support, external, internal)
- Each meeting has: transcript, summary, topics, sentiment, key moments tagged
- **Critical insight:** Pre-computed signals exist → don't regenerate, build on top
- Date range: [fill in from data]
- Total: [X] hours of meetings, [Y] action items, [Z] unique speakers

**Visual:** Sample meeting card showing all available fields

---

### Slide 4: My Approach
**Content:**
- **Hybrid categorization:** Rules (free, ~70%) + LLM (Haiku, ~30%) for ambiguous cases
- **Trust pre-computed data:** Sentiment scores, topics, key moments → use them
- **Tool-shaped functions:** Each insight is a reusable, composable function
- **Cost-aware:** Total LLM spend <$1 for this analysis

**Visual:** Pipeline diagram: `Raw Meetings → Loader → Categorize → Insights → Visualizations`

---

### Slide 5: Required Task 1 — Categorization
**Content:**

| Call Type | Count | % |
|-----------|-------|---|
| Support | [X] | [Y%] |
| External | [X] | [Y%] |
| Internal | [X] | [Y%] |

**Sub-themes found:** 8 distinct themes including incident_response, customer_renewal, compliance_security, ...

**Why hybrid:** Rules transparent and free for obvious cases; LLM for nuance; confidence scores flag ~12% for review.

**Visual:** Donut chart of call types + bar chart of sub-themes

---

### Slide 6: Required Task 2 — Sentiment Trends
**Content:**

3-4 key findings:
1. **[Call type] is most negative** — avg sentiment X.X vs Y.Y for other types
2. **[Sub-theme] drives the most negativity** — likely indicator of [business pain]
3. **Sentiment is [trending direction]** over the period
4. **[Characteristic] correlates with sentiment** (e.g., longer meetings = lower sentiment)

**What this means:**
- Support leaders: prioritize [X]
- Sales: watch [Y] accounts
- Eng: invest in [Z]

**Visual:** Sentiment heatmap (call type × sub-theme) — this is the killer visual

---

### Slide 7: Bonus Insight A — Churn Risk Scoring
**Content:**

**The question:** Which customers are at risk of leaving?

**Approach:** Weighted score of 4 signals → ranked accounts with evidence

| Risk Level | Count | Action |
|-----------|-------|--------|
| Critical (70+) | [X] | Exec outreach this week |
| Alert (50-69) | [X] | CS check-in within 7 days |
| Watch (30-49) | [X] | Monitor |
| Healthy (<30) | [X] | No action |

**Top 3 at-risk:** [Account 1], [Account 2], [Account 3]

**Why this matters:** $[estimated ARR at risk] across flagged accounts.

**Visual:** Horizontal bar chart of top 10 at-risk accounts, color-coded by risk level

---

### Slide 8: Bonus Insight A — Evidence Example
**Content:**

Deep-dive on the #1 at-risk account: **[Account name]**

- **Risk score:** [X]/100 ([Risk level])
- **Components:** Churn signals: [X], Sentiment: [Y], Concerns: [Z], Recent: [W]
- **Evidence (specific quotes from real meetings):**
  > "[quote 1]" — [Speaker], [Meeting title]
  > "[quote 2]" — [Speaker], [Meeting title]
- **Recommendation:** [Recommendation]

**Why this slide matters:** Shows the tool produces explainable, actionable output — not black-box scores.

---

### Slide 9: Bonus Insight B — Action Item Tracker
**Content:**

**The question:** Who's doing what across all our meetings? What's recurring?

**Findings:**
- **[X] total action items** across [Y] meetings
- **Top loaded owner:** [Name] with [N] items across [M] meetings → possible bottleneck
- **Top action verbs:** [verb 1], [verb 2], [verb 3] → reveals working mode
- **Recurring themes:** Keywords like "[X]", "[Y]", "[Z]" appear in 3+ meetings → systemic issues

**For engineering leads:** Visibility into IC workload and unresolved themes.

**Visual:** Owner workload bar chart + recurring keyword bar chart, side-by-side

---

### Slide 10: Bonus Insight C — Recurring Topics
**Content:**

**The question:** What topics keep coming up? Which drag sentiment down?

**Findings:**
- **[N] recurring topics** (appearing in 3+ meetings)
- **Most discussed:** "[Topic 1]", "[Topic 2]", "[Topic 3]"
- **Drives negativity:** "[Topic X]" averages sentiment [Y] across [Z] meetings → systemic pain
- **Co-occurring pairs:** "[Topic A]" + "[Topic B]" appear together in [N] meetings → likely linked issues

**For PMs:** What customers and teams care about most, with evidence.

**Visual:** Scatter plot — topic frequency vs avg sentiment (size = meeting count)

---

### Slide 11: From Analytics to Agentic Intelligence (THE DIFFERENTIATOR)
**Content:**

**The hint in the assignment:**
> *"each [stakeholder] would want something different from this tool."*

**Why this matters:**
- Sales asks: "Which customers show churn risk?"
- Support asks: "What issues are recurring?"
- Engineering asks: "What outages happened last quarter?"
- Same data, **different reasoning per query**

**This is an agentic system problem, not a dashboard problem.**

**Production architecture (what comes next):**

```
Stakeholders → Role-specific Agents → MCP Tools → Data
                       ↓
            ┌──────────┴──────────┐
            │ Governance | Evals  │
            │ Observability       │
            └─────────────────────┘
```

- **MCP tools:** My functions become reusable, versioned tools
- **Agents:** Pick the right tools per query, cite evidence
- **Governance:** RBAC, audit logs, PII filtering
- **Observability:** Trace every step, cost per query, latency P95
- **Evals:** Regression tests, safety tests, citation accuracy

**What I built supports this:** Functions are tool-shaped with provenance.
**What I deliberately didn't build:** The agent + MCP layer. Overkill for 100 meetings, the right call for a 2-day prototype.

---

### Slide 12: Limitations + What I'd Build Next
**Content:**

### Honest limitations
1. **No labeled ground truth** for categorization accuracy or churn outcomes
2. **Heuristic churn scoring** — without churn labels, can't train ML
3. **Single-document analysis** — no cross-meeting threading
4. **Pre-computed dependencies** — quality depends on upstream summarization

### What I'd build next (priority order)
1. **Eval set:** Hand-label 30 meetings; track categorization accuracy
2. **Customer threading:** Link meetings by customer name + participants
3. **MCP tool wrappers:** Convert each function to versioned MCP tools (1 week)
4. **Sales agent prototype:** Demonstrate "show me churn risk" end-to-end (1 week)
5. **Governance layer:** RBAC + audit logging (2 weeks)
6. **Full eval framework:** Regression + safety + citation tests (2 weeks)

**Total path to production agentic system:** ~5 weeks from this foundation.

---

## 🎤 PRESENTATION DELIVERY TIPS

### Opening (Slide 1-2): Hook
> "B2B SaaS companies record thousands of meetings. The data is rich, but the 
> insights are stuck in transcripts. I'll show you how I extracted them — and 
> what this product needs to become at scale."

### Middle (Slides 3-10): Build the story
- Each slide answers a question
- Use the **finding → meaning → who cares → recommendation** structure
- Show evidence (quotes, examples) wherever possible
- **Slides 5-6 are required tasks** (be solid)
- **Slides 7-10 are bonuses** (be impressive)
- **Slide 8 (churn evidence)** is your "wow" moment — make it concrete

### Climax (Slide 11): Production vision
> "Up to now I've shown you analytics. But the assignment specifies different 
> stakeholders need different things — and that's not a dashboard problem. 
> Let me show you what this becomes."

This is where you connect to the AI engineer role.

### Close (Slide 12): Honesty
> "Here's what I didn't build, what I'd build next, and how long it'd take. 
> The analytics foundation is solid; the agentic system is a 5-week buildout 
> from here."

### Tone throughout
- **Confident, not arrogant** — "I chose X because Y" not "X is obviously best"
- **Honest about limitations** — Don't oversell. The panel will respect it.
- **Insight-first** — Numbers serve the story, not the other way around
- **Concrete examples** — Always show real meetings, real quotes, real names

---

## ⏰ TIMING (30 min total)

| Slide | Topic | Time |
|-------|-------|------|
| 1-2 | Intro + opportunity | 2 min |
| 3-4 | Data + approach | 3 min |
| 5 | Categorization | 3 min |
| 6 | Sentiment | 4 min |
| 7-8 | Churn risk + evidence | 6 min |
| 9 | Action items | 3 min |
| 10 | Topics | 3 min |
| 11 | Production vision | 4 min |
| 12 | Limitations + next | 2 min |

**Buffer:** ~30 sec, in case of questions during slides.

---

## 🎯 Q&A PREP (15 min after presentation)

Anticipate these questions:

**"Walk me through your categorization code."**
→ Pull up `src/categorize.py`. Show rules + LLM fallback + confidence scoring.

**"How would you scale this to 1M meetings?"**
→ Vector DB for semantic search, batch LLM calls, MCP tools, streaming pipeline. Cite specifics.

**"Why didn't you use [LangGraph / OpenAI / clustering / X]?"**
→ Honest answer: "Wrong tool for this scope" or "I'd use it at scale Y". Don't be defensive.

**"What if the pre-computed sentiment is wrong?"**
→ Sample-validation: hand-score 20 meetings, compare correlation. If < 0.8, re-score with my own model.

**"How do you know your churn scorer works?"**
→ Backtest with historical churn data; A/B test (CS uses list vs. their own); track outreach effectiveness.

**"What's the biggest gap in your work?"**
→ No labeled eval set. Everything else is a known trade-off.

**"What would you do differently with more time?"**
→ (1) Build a proper eval framework with held-out test set, (2) Convert functions to MCP tools to demo the production vision, (3) Customer-thread linking for richer churn signals.
