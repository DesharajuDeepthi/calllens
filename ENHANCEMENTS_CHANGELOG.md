# Enhancements Changelog

A line-by-line record of the changes made on branch `claude/code-review-assessment-3BLvJ`
(PR #1), written so the original author can follow **what changed, where, and why** —
from the high-level requirements down to individual code lines.

- **Scope:** purely additive analytics + an evaluation harness + a test suite.
- **Did NOT touch:** `notebooks/analysis.ipynb`, `mcp_server/` logic, the dataset.
- **Everything runs offline** (no API key): all new analysis is computed from local JSON.
- **Tests:** 104 passing, **92% coverage on `src/`** (`pytest tests/ --cov=src`).
- **No test needs an API key.** The only AI-API call (the LLM categorization fallback) is unit-tested with a **mocked** client; the real API is exercised only in the manual notebook run, which skips gracefully when no key is set.

---

## 1. Why these changes (requirements → implementation)

The starting repo was strong but left the single richest signal in the dataset unused
and validated its decisions by eye rather than by number. These changes close both gaps.

| # | Requirement (the "why") | What was built | Where |
|---|---|---|---|
| R1 | The per-sentence `sentimentType` + `speaker` in `transcript.json` was discarded at load — only one pre-computed scalar per meeting was used. | Retain per-turn data; attribute each turn to **rep vs. customer**; compute rep/customer gap, intra-meeting arc, per-speaker sentiment. | `loader.py`, `transcript_sentiment.py` |
| R2 | Churn was a snapshot per account; a downward *sequence* is a stronger signal. | Reconstruct each account's meeting sequence and classify its trajectory; feed it into churn. | `account_journey.py`, `churn_scorer.py` |
| R3 | Categorization was "spot-checked"; the "trust the pre-computed sentiment" decision was asserted, not measured. | Confusion matrix + precision/recall vs a hand-labelled set; sentiment validation vs transcript-derived score; churn weight sensitivity. | `evaluation.py`, `tests/fixtures/categorization_labels.csv` |
| R4 | `topics` were matched as exact strings ("compliance" ≠ "compliance reporting"). | Opt-in canonicalization that merges near-duplicate topics. | `topic_analyzer.py` |
| R5 | Hygiene found in the earlier review: `mcp` missing from requirements; `score_account` computed twice; risk score could exceed the documented 0–100; leftover scratch notebook; stale/contradictory README. | Fixed all of the above. | `requirements.txt`, `churn_scorer.py`, `README.md`, repo |

### Headline findings produced by the new code
- Reps read **+0.41 pts** more positive than customers on the same calls (aggregate masks customer frustration).
- Categorization scores **97% accuracy / macro-F1 0.97** on 34 hand-labelled meetings (rules-only mode).
- Pre-computed vs transcript-derived sentiment correlate at **r=0.94** (MAE 0.33, 99% within 1 pt) → trusting `summary.json` is justified, *measured*.
- **3 accounts** show a sustained sentiment decline: Summit Trust, Brightpath Commerce, Frostbyte AI.
- The top-10 churn ranking is **90% stable** under component reweighting → conclusions are driven by signal, not by exact weights.

---

## 2. New files

### `src/transcript_sentiment.py` (new, flagship — R1)

Mines the per-sentence transcript data the loader now retains.

| Function | What it does | Why |
|---|---|---|
| `SENTIMENT_VALUE` import / `PIVOT_THRESHOLD = 0.5` | `negative→1, neutral→3, positive→5`; a ≥0.5 late drop is a "negative pivot". | Aligns per-sentence labels to the same 1–5 scale as the pre-computed score so the two are comparable. |
| `_values(turns, role=None)` | Pull sentiment values, optionally filtered to one role. | Single helper so every metric below shares identical filtering logic. |
| `derived_meeting_sentiment(turns)` | Mean per-sentence sentiment for a meeting. | The transcript-derived counterpart to the pre-computed score — used by the eval to validate it. |
| `role_sentiment(turns)` | Splits sentiment into rep vs. customer, plus the gap and the customer's negative-turn share. | **The flagship metric.** On a support call the calm vendor dilutes the average; the customer's number is what matters. |
| `meeting_sentiment_arc(turns, role=None)` | First/middle/last-third means, an overall slope, and a `has_negative_pivot` flag. | Detects calls that *end* worse than they start. Returns safe nulls for `< 3` turns. |
| `late_call_sentiment(turns, role=None)` | Mean over the final third. | The end of a call is the freshest signal; consumed by churn. |
| `speaker_sentiment(turns, min_turns=3)` | Per-speaker mean; surfaces the most negative speaker. | "Who is frustrated?" — useful for support coaching and escalation. |
| `add_transcript_features(df)` | Adds columns: `derived_sentiment`, `customer_sentiment`, `rep_sentiment`, `sentiment_arc_slope`, `has_negative_pivot`, `late_customer_sentiment`, `most_negative_speaker`. | One call enriches the whole DataFrame so downstream modules (churn, eval) can use the signal. Raises `KeyError` if `transcript_turns` is missing — fail loud, not silent. |
| `chart_rep_vs_customer`, `chart_negative_pivots`, `generate_transcript_report` | Plotly charts + a JSON report with an interpreted `insight`. | Mirrors the existing module style (charts + a `*_report.json` + a printed insight). |

**Design note (the 0.5 pivot threshold):** across the corpus, meetings actually trend
*up* to a positive close (mean slope +0.65; only 8/100 end below their start, none by
>0.3), so `has_negative_pivot` is 0 at the principled 0.5 threshold. That is a genuine
finding — frustration is front/mid-loaded and reps steer to a positive ending — so the
threshold was **not** lowered just to manufacture a non-zero count.

### `src/account_journey.py` (new — R2)

| Function | What it does | Why |
|---|---|---|
| `DECLINE_SLOPE = -0.3`, `IMPROVE_SLOPE = 0.3` | Slope thresholds (points/meeting). | Explicit, tunable constants instead of magic numbers buried in logic. |
| `_trajectory(scores)` | Classifies a sentiment sequence as `declining` / `improving` / `volatile` / `stable` / `single_point` using slope + volatility (std). | "Volatile" (high std, ~flat slope) is a different risk than a clean decline; both matter. |
| `build_account_journey(df, account)` | Orders one account's meetings by time; computes trajectory, cadence (avg days between calls), first/last sentiment, full timeline. | Turns a bag of meetings into a *sequence* — the core of R2. |
| `build_all_journeys(df, min_meetings=2)` | Builds journeys for every multi-meeting account, declining ones first; writes `account_journeys.json`. | Single-meeting accounts have no trajectory, so they're excluded. |
| `trajectory_lookup(journeys)` | `account → trajectory` dict. | Clean hand-off to the churn scorer without it needing to know how journeys are built. |
| `chart_account_trajectories`, `generate_journey_report` | Line chart of at-risk trajectories + JSON report. | Consistent with the existing module pattern. |

### `src/evaluation.py` (new — R3)

| Function | What it does | Why |
|---|---|---|
| `confusion_matrix(y_true, y_pred, labels)` | Confusion matrix as a DataFrame. | Pure-numpy, no scikit-learn dependency added. |
| `classification_report(y_true, y_pred, labels)` | Per-class precision/recall/F1/support, accuracy, macro-F1. | The standard way to *measure* a classifier instead of eyeballing it. |
| `evaluate_categorization(df, labels_path)` | Scores predicted `call_type` against the hand-labelled sample. | The labels file is an **independent** sample — it measures the classifier, it is not its training data. |
| `sentiment_validation(df, tolerance=1.0)` | Correlation / MAE / within-tolerance / direction-agreement between pre-computed and transcript-derived sentiment. | Converts "we trust `summary.json`" into a number (r=0.94) — the most credibility-per-line change in the PR. |
| `_spearman(a, b)` | Spearman via Pearson-on-ranks. | Avoids adding scipy for one function. |
| `churn_weight_sensitivity(rankings, top_k, perturbations)` | Re-weights the churn components and measures how much the ranking moves (top-K overlap + Spearman). | The churn weights are judgment calls; this shows the **ranking is robust** to them (90% stable). |

### `tests/fixtures/categorization_labels.csv` (new — R3)

34 meetings hand-labelled (`meeting_id, true_call_type, title`) by reading titles/summaries,
including deliberately ambiguous cases the rules can't catch (e.g. `URGENT: Blackridge
Investments - Complete Loss of Threat Visibility`, which has no `Support Case`/`Aegis /`
pattern). This is what `evaluate_categorization` scores against — and the one ambiguous
miss in rules-only mode is exactly why accuracy is 97%, not a suspicious 100%.

### `tests/conftest.py` + 7 test files (new — R3/R5)

- `conftest.py`: a **session-scoped `real_df`** fixture (the full 100-meeting corpus run
  through the offline pipeline once), a `make_turns()` builder, and a `synthetic_df`
  fixture with a hand-crafted declining account (`Acme Corp`) and a healthy one (`Globex`)
  for deterministic unit tests.
- `test_loader.py`, `test_transcript_sentiment.py`, `test_account_journey.py`,
  `test_evaluation.py`, `test_churn_scorer.py`, `test_topic_analyzer.py`, `test_reports.py`
  (the last runs the existing `sentiment.py` / `action_tracker.py` report generators on real
  data, which also covers their chart functions).

---

## 3. Modified files — exact diffs and rationale

### `src/loader.py` (R1)

Retain per-turn transcript data with rep/customer roles, and keep heavy columns out of the CSV.

**Added constants** — map sentiment labels to the 1–5 scale and mark columns too big for CSV:
```diff
+# Per-sentence sentimentType -> numeric, aligned to the 1-5 pre-computed scale.
+SENTIMENT_VALUE = {"negative": 1.0, "neutral": 3.0, "positive": 5.0}
+
+# Columns too heavy to serialize into the flat CSV (kept in-memory only).
+_HEAVY_COLS = ["transcript_text", "transcript_turns"]
```

**Added `_speaker_role_resolver(info)`** — the rep/customer attribution. The vendor is the
organizer's email domain; vendor staff follow `first.last@domain`, so a speaker name
normalises to a local-part we can look up. Unmatched speakers are `customer` in a
multi-domain (customer-facing) call and `internal` otherwise. *Verified: 100% of 311
speakers across the corpus get a role (298 matched directly, 11 multi-domain→customer,
2 single-domain→internal).*
```diff
+def _speaker_role_resolver(info: dict):
+    ...
+    by_localpart = {e.split("@")[0].lower(): e.split("@")[1].lower() for e in emails}
+    by_lastname  = {e.split("@")[0].lower().split(".")[-1]: ... }   # fallback on surname
+    def resolve(name: str) -> str:
+        ...
+        domain = by_localpart.get(key) or by_lastname.get(last)
+        if domain:
+            return "rep" if domain == vendor_domain else "customer"
+        return "customer" if multi_domain else "internal"
+    return resolve
```

**Added `_parse_transcript_turns(...)`** — flattens each sentence into a typed turn
`{speaker_id, speaker, role, sentiment_type, sentiment_value, time}`; skips non-dict rows.
```diff
+def _parse_transcript_turns(transcript_data: list, resolve_role) -> list[dict[str, Any]]:
+    ...
+        turns.append({ "speaker_id": ..., "speaker": name, "role": resolve_role(name),
+                       "sentiment_value": SENTIMENT_VALUE.get(stype, 3.0), "time": ... })
```

**Wired into `_parse_meeting`** and added a `transcript_turns` field to the record:
```diff
+    resolve_role = _speaker_role_resolver(info)
+    turns = _parse_transcript_turns(transcript_data, resolve_role)
     ...
         "transcript_text": full_text,
+        "transcript_turns": turns,
```

**CSV save** now drops the heavy columns so `meetings_flat.csv` doesn't bloat with full
transcripts or nested turn lists (previously the full `transcript_text` was written verbatim):
```diff
-        df_csv = df.copy()
+        df_csv = df.drop(columns=_HEAVY_COLS, errors="ignore").copy()
```

### `src/churn_scorer.py` (R2 + R5)

**New component `_transcript_score(meetings)`** — adds risk from customer-specific late-call
negativity and negative pivots, but only if the transcript features are present (so the
scorer still works on a plain DataFrame). Bounded to 20.
```diff
+def _transcript_score(meetings: pd.DataFrame) -> float:
+    if "late_customer_sentiment" not in meetings.columns:
+        return 0.0          # backward-compatible: no transcript features -> no effect
+    ...
+    return min(points, 20)
```

**New component `_trajectory_score(trajectory)`** — a declining arc adds 10, volatile 5:
```diff
+def _trajectory_score(trajectory: dict | None) -> float:
+    if not trajectory: return 0.0
+    return {"declining": 10.0, "volatile": 5.0}.get(trajectory.get("label"), 0.0)
```

**`score_account` gains an optional `trajectory` arg, folds in both new components, and
clamps the total to 100** (the documented range — previously the max possible was 125):
```diff
-def score_account(df: pd.DataFrame, account: str) -> dict[str, Any]:
+def score_account(df: pd.DataFrame, account: str,
+                  trajectory: dict | None = None) -> dict[str, Any]:
     ...
-    total = churn_pts + sent_pts + concern_pts + recent_pts
+    transcript_pts = _transcript_score(account_meetings)
+    trajectory_pts = _trajectory_score(trajectory)
+    total = min(churn_pts + sent_pts + concern_pts + recent_pts
+                + transcript_pts + trajectory_pts, 100)
```
…and the two new components are surfaced in the `components` breakdown so charts and the
sensitivity analysis see them:
```diff
             "recent_negativity": recent_pts,
+            "transcript_negativity": transcript_pts,
+            "trajectory": trajectory_pts,
```

**Bug fix in `score_all_accounts`** — the original called `score_account` **twice per
account** (once in the body, once in the `if ...["meeting_count"] >= min_meetings` filter),
doubling the work. Now it scores once, then filters. It also accepts `journeys` to feed
trajectories:
```diff
+    trajectories = {}
+    if journeys:
+        from src.account_journey import trajectory_lookup
+        trajectories = trajectory_lookup(journeys)
+
     results = [
-        score_account(customer_facing, account)
+        score_account(customer_facing, account, trajectory=trajectories.get(account))
         for account in accounts
-        if score_account(customer_facing, account)["meeting_count"] >= min_meetings
     ]
+    results = [r for r in results if r["meeting_count"] >= min_meetings]
```

### `src/topic_analyzer.py` (R4)

**Added `_normalize_topic` + `build_topic_canonical_map`** — group near-duplicate topics by
token-subset / high Jaccard overlap; the most frequent topic in a group wins as canonical
(deterministic). `_normalize_topic` lowercases, strips punctuation, and does naive
singularisation.
```diff
+def build_topic_canonical_map(topic_counts: dict[str, int], jaccard: float = 0.6) -> dict[str, str]:
+    ...
+    for rep_topic, rep_ts in reps:
+        overlap = len(ts & rep_ts) / len(ts | rep_ts)
+        if ts <= rep_ts or rep_ts <= ts or overlap >= jaccard:
+            match = rep_topic; break
```

**`topic_frequency` gains an opt-in `canonicalize` flag** and switches its internal store
from `list` to `set` so a meeting is never double-counted for a topic, and merged groups
union their meeting sets correctly. **Default is `False`, so existing outputs/numbers are
unchanged** unless a caller opts in:
```diff
-def topic_frequency(df: pd.DataFrame, min_count: int = 3) -> dict[str, Any]:
-    topic_meetings: dict[str, list[str]] = defaultdict(list)
+def topic_frequency(df: pd.DataFrame, min_count: int = 3, canonicalize: bool = False) -> dict[str, Any]:
+    topic_meetings: dict[str, set[str]] = defaultdict(set)
     ...
-            topic_meetings[topic].append(row["meeting_id"])
+            topic_meetings[topic].add(row["meeting_id"])
+    if canonicalize:
+        cmap = build_topic_canonical_map({t: len(m) for t, m in topic_meetings.items()})
+        merged = defaultdict(set)
+        for topic, mids in topic_meetings.items():
+            merged[cmap[topic]] |= mids
+        topic_meetings = merged
+    topic_meetings = {t: sorted(mids) for t, mids in topic_meetings.items()}
```

### `requirements.txt` (R5)

```diff
 pytest>=7.4
+pytest-cov>=4.1
 kaleido>=0.2.1
 nbformat>=5.9
+mcp>=1.0.0
```
`mcp` was imported by `mcp_server/server.py` but only installed inside the Dockerfile, so
the README's non-Docker "run the MCP server" path would fail on a clean install.
`pytest-cov` backs the coverage requirement.

### `.gitignore` (R5)

```diff
+# Coverage
+.coverage
+htmlcov/
+.pytest_cache/
```

### `README.md` (R5)

- Documented the two new insight modules (transcript sentiment, account journeys), the
  evaluation harness + its numbers, and the new output files.
- Updated both `src/` trees to list the new modules.
- Fixed stale notes ("symlinked" → "committed"; dropped the hard-coded "11 charts" count).
- **Reconciled the MCP scope contradiction:** the README previously framed the agentic
  layer as future work while `mcp_server/` already existed. It now states a working MCP
  prototype ships, and explicitly flags that the RBAC `role` is a caller-supplied
  parameter — i.e. it demonstrates the access-control *shape*, it is not enforced identity.

### `notebooks/Untitled.ipynb` (R5)

Deleted — leftover empty scratch notebook.

---

## 4. Decisions & trade-offs (anticipating "why did you…")

- **Offline by design.** Two suggestions originally implied API calls (LLM re-scoring,
  embeddings). Both were implemented as deterministic offline equivalents — transcript-derived
  sentiment for validation, lexical token-clustering for topic dedup — because reproducible,
  test-able, zero-cost analysis is more valuable here than a network dependency. Real
  embeddings remain the obvious production upgrade for topic clustering.
- **Backward compatibility.** New churn components no-op when transcript features are absent;
  `canonicalize` defaults off. Existing behaviour and reported numbers are preserved unless a
  caller opts in.
- **No new heavy deps.** Confusion matrix and Spearman are hand-rolled with numpy rather than
  pulling in scikit-learn/scipy.
- **Score clamp.** Clamping churn to 100 changes some absolute scores but keeps the documented
  0–100 range and the 70/50/30 risk thresholds meaningful.

## 5. Not changed (and why)

- **`notebooks/analysis.ipynb`** — the take-home's primary deliverable. The new modules are
  not yet surfaced in its narrative; that's the natural follow-up and was left out to keep
  this PR a clean, reviewable analytics+tests change.
- **`mcp_server/` logic** — untouched; only the README framing around it was corrected.

## 6. How to reproduce

```bash
pip install -r requirements.txt
pytest tests/ -q --cov=src --cov-report=term     # 104 passed, 92% coverage (no API key needed)

# End-to-end, offline (no API key):
python -m src.evaluation            # 97% categorization acc; sentiment r=0.94
python -m src.transcript_sentiment  # rep-vs-customer gap, pivots
python -m src.account_journey       # declining-account trajectories
```
