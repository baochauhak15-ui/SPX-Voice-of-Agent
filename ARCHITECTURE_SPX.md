# SPX Voice of Operations Agent — Architecture Plan

> Written **before** implementation, per the hackathon brief. This document explains what was
> learned from the reference project, what is reused vs. redesigned, and how the MVP is built.

---

## 0. One-line product definition

An **operations intelligence agent** (not a chatbot, not a sentiment tool, not a dashboard-only
project) that turns fragmented Voice-of-Operations feedback from **Customers, Sellers and Riders**
into **cross-stakeholder root-cause hypotheses with evidence and a recommended action**.

```
Raw VOC ─► structured signals ─► cross-stakeholder pattern detection ─► root-cause analysis ─► recommended action
```

---

## 1. Inspection of the reference repository

Reference: `nguyenngocvantrinh-nasha/voc-root-cause-agent-clawathon-2026` (Zalopay chatbot CSAT agent).

| Reference file | Size | What it does | Observations |
|---|---|---|---|
| `voc_core.py` | 78 KB | Load/clean Excel, cache, classify rows, map tickets, priority, dashboard dataset | Monolithic; Zalopay-specific columns, week logic, TPE codes |
| `voc_rules_v2.py` | 32 KB | Standardised rule classifier: `strip_vi`, word-boundary match, risk flags, noise detection, dropdown fallback | **Best reusable idea**: normalise Vietnamese → match free text first → dropdown is only a fallback → emit multi-field result |
| `voc_llm_classifier.py` | 29 KB | LLM relabel for low-confidence rows; JSON parse; taxonomy validator; cache; batch; 429 backoff | **Reusable pattern**: `_needs_llm()` gate, `_validate_item()` against `VALID_*` sets, fallback to rule result |
| `voc_pipeline.py` | 128 KB | Survey↔click journey mapping, survey↔ticket mapping (±1 day), reports | Journey mapping concept reused as *tracking-id ↔ ops event* and *stakeholder ↔ ticket* linking |
| `voc_report_v3.py`, `voc_html_v2.py`, `voc_output_builders.py` | ~180 KB | Self-contained HTML reports (inline SVG, no CDN), Excel alert/action/follow-up lists | Report *structure* reused (Exec summary → KPI → period compare → top increasing → root cause → drilldown → samples → methodology) |
| `voc_llm_report.py` | 16 KB | LLM coverage report | Reused as "LLM layer coverage" block in the dashboard |
| `main.py` | 35 KB | GreenNode AgentBase HTTP runtime | Not needed — replaced by a tiny optional `app.py` static server |
| `run_local.py` | 9 KB | CLI modes daily / weekly / monthly / all | Reused as CLI shape, new `--mode demo` |
| `tests/gen_synthetic_data.py` | — | Synthetic Excel generator | Reused idea: seeded, deterministic synthetic data |

### 1.1 Reused (concept or pattern, rewritten for SPX)

1. **Pipeline shape** — Data Cleaner → Mapper → Classifier → Root Cause → Report.
2. **Vietnamese normalisation** — accent stripping (`strip_vi`), word-boundary matching; extended here
   with teen-code / abbreviation expansion and repeated-letter collapse ("lauuuu" → "lau").
3. **Hybrid classification contract** — rule layer runs on 100 % of rows; LLM only on a gated subset;
   LLM output validated against a controlled taxonomy; invalid → keep rule result.
4. **Rule result schema** — group, sub-issue, priority, owner, confidence, matched signal, reason,
   human-review flag.
5. **P1 / P2 / P3 semantics** — P1 immediate, P2 review, P3 monitor.
6. **Self-contained HTML reports** — no CDN, inline SVG charts, open offline.
7. **Daily / Weekly / Monthly + Action List** outputs.
8. **Synthetic data only**, secrets via env, outputs git-ignored.

### 1.2 Needs modification

| Area | Reference | SPX version |
|---|---|---|
| Stakeholders | Customer only | **Customer / Seller / Rider** — stakeholder is a first-class dimension everywhere |
| Taxonomy | Hard-coded Python sets (Zalopay payments/chatbot) | **YAML config** (`config/taxonomy.yaml`) with logistics groups; per-stakeholder keywords and meaning |
| Linking | survey ↔ chatbot click, survey ↔ ticket | VOC ↔ **operational events by `tracking_id`**; VOC ↔ tickets by `stakeholder_id` / `tracking_id` |
| Priority | Per-row (contact this user today) | **Per-insight** (volume, growth, stakeholder count, ops severity, repeat contacts, SLA breach) + per-row for the review queue |
| Root cause | Share of VOC by group/source | **Cross-stakeholder driver detection** + operational corroboration + confidence scoring |
| Knowledge | none | **Help Center gap detection** |
| LLM provider | GreenNode / Gemini | Provider-agnostic OpenAI-compatible endpoint (env), plus a deterministic `mock` provider for tests |

### 1.3 New modules (do not exist in the reference)

- `cross_stakeholder_analyzer.py` — the key differentiator.
- `root_cause_analyzer.py` — hypothesis + evidence + confidence, correlation-safe wording.
- `knowledge_checker.py` — Help Center coverage / gap / staleness.
- `insight_generator.py` — What / Who / Where / Why / Impact / Action / Owner / Priority / Evidence,
  every statement tagged **FACT**, **INFERENCE** or **RECOMMENDATION**.
- `action_generator.py` — action list.
- `dashboard.py` — polished single-file dashboard with drill-down.

---

## 2. Folder structure

```
spx-voice-of-operations-agent/
├── ARCHITECTURE_SPX.md          ← this file
├── README.md
├── run_local.py                 ← one command: python run_local.py --mode demo
├── app.py                       ← optional: serve outputs/ on localhost
├── requirements.txt
├── .env.example                 ← LLM settings (no secrets committed)
├── config/
│   ├── taxonomy.yaml            ← controlled VOC taxonomy (groups, sub-issues, keywords per stakeholder, owner, severity)
│   ├── drivers.yaml             ← operational drivers: which sub-issues per stakeholder + which ops metric corroborates
│   ├── priority.yaml            ← thresholds / weights for P1-P3
│   └── normalization.yaml       ← Vietnamese abbreviation / teen-code map
├── data/synthetic/              ← generated CSVs (committed so the demo works without generation)
│   ├── customer_voc.csv  seller_voc.csv  rider_voc.csv
│   ├── support_tickets.csv  operational_events.csv  help_center.csv
├── scripts/
│   └── generate_synthetic_data.py
├── spx_voo/                     ← the agent package
│   ├── config.py                ← YAML loading
│   ├── text_utils.py            ← Vietnamese normalisation, fuzzy match
│   ├── data_loader.py           ← read + schema validation
│   ├── data_cleaner.py          ← unify 3 VOC files → one frame, types, dedupe, negative flag
│   ├── linker.py                ← VOC ↔ ops events (tracking_id), VOC ↔ tickets
│   ├── voc_classifier.py        ← Layer 1 rules
│   ├── llm_classifier.py        ← Layer 2 LLM (gated, validated, cached)
│   ├── cross_stakeholder_analyzer.py
│   ├── root_cause_analyzer.py
│   ├── knowledge_checker.py
│   ├── insight_generator.py
│   ├── action_generator.py
│   ├── report_generator.py      ← daily / weekly / monthly HTML
│   ├── dashboard.py             ← main dashboard HTML
│   └── pipeline.py              ← orchestration
├── tests/                       ← pytest, one file per component
└── outputs/                     ← generated (git-ignored)
```

---

## 3. Synthetic SPX data schema

All data is **synthetic**, seeded (`--seed 42`) and deterministic. IDs are fake (`C000123`,
`S00456`, `R0789`, `SPXVN26…`). No PII, no real hubs' data.

Window: **2026-07-27 → 2026-09-20** (8 weeks). Baseline = first 7 weeks; incident week =
**2026-09-14 → 2026-09-20**.

Regions / hubs (fictional names):

| Region | Hubs |
|---|---|
| HCM | `HCM-ThuDuc-SOC`, `HCM-TanBinh-Hub`, `HCM-Q7-Hub` |
| HN | `HN-LongBien-SOC`, `HN-CauGiay-Hub` |
| DN | `DN-HaiChau-Hub` |
| CT | `CT-NinhKieu-Hub` |

| File | Columns | Notes |
|---|---|---|
| `customer_voc.csv` | feedback_id, stakeholder_type, stakeholder_id, timestamp, rating, comment, issue_type, region, hub, tracking_id | Rating 1–5, comment in Vietnamese (with / without accents, typos, teen code). `issue_type` = survey dropdown (may be blank or contradict text) |
| `seller_voc.csv` | feedback_id, stakeholder_type, seller_id, timestamp, rating, comment, issue_type, region, hub, tracking_id | Seller wording ("đơn của shop…") |
| `rider_voc.csv` | feedback_id, stakeholder_type, rider_id, timestamp, rating, comment, issue_type, region, hub | No tracking_id — rider feedback is about hub/route/app |
| `support_tickets.csv` | ticket_id, stakeholder_type, stakeholder_id, created_time, first_response_time, resolution_time, issue_type, description, status, owner_team, hub, tracking_id | Used for repeat-contact and SLA signals |
| `operational_events.csv` | event_id, timestamp, tracking_id, event_type, hub, region, delivery_attempt, processing_time, status | `event_type ∈ {inbound_scan, sort_complete, outbound, delivery_attempt, pickup}`; `processing_time` in hours (hub dwell for `sort_complete`; pickup lead time for `pickup`) |
| `help_center.csv` | article_id, title, issue_type, content, owner_team, last_updated | ~12 articles; one intentionally incomplete (failed delivery after 2 attempts), one stale |

Negative VOC rule (deterministic): `rating ≤ 2`, or `rating == 3` **and** the comment carries a
complaint signal.

### 3.1 Embedded demo stories

| # | Story | Where it lives | Expected agent output |
|---|---|---|---|
| **A (main)** | `HCM-ThuDuc-SOC` processing delay from 2026-09-14 | Customer late-delivery ↑, Seller order-status/late ↑, Rider hub-waiting ↑, ops `sort_complete.processing_time` ↑ at that hub only | **Cross-stakeholder operational issue detected — Potential root cause: Hub processing delay — Customer + Seller + Rider — P1 — Operations investigation** |
| B | Seller failed delivery after 2 attempts; Help Center article does not explain next step | Seller VOC + help_center | **Knowledge Gap → Update Help Center** |
| C | COD / settlement complaints (sellers), background noise with no operational signal | Seller VOC | At most an *emerging trend* with Low confidence — never escalated to P1 without operational evidence (proves the agent does not over-alert) |
| D | Rider app login issue, small spike in HN | Rider VOC | Single-stakeholder, P2 review, owner Product (proves the agent does not force every issue into the hub story) |
| Noise | Short / meaningless comments, positive comments, multi-issue comments, typos, no accents | All VOC | Classifier robustness; LLM candidates |

---

## 4. Taxonomy (config, not code)

`config/taxonomy.yaml` defines:

```yaml
groups:
  Delivery:
    sub_issues:
      Late delivery:
        owner: Operations
        severity: 3            # 1..5 operational severity
        keywords:              # accent-free, matched after normalisation
          any:      [giao tre, giao cham, cham giao, lau qua, qua han, tre hen, cho lau]
          customer: [chua nhan duoc hang]
          seller:   [don cua shop giao cham, khach hoi don]
          rider:    []
        stakeholder_meaning:
          customer: "My parcel arrived late"
          seller:   "My shop's orders are delivered late → buyer complaints / cancellations"
          rider:    "Late departures caused by upstream delay"
```

Groups: **Delivery** (Late delivery, Failed delivery, Delivery attempt, Return, Tracking / status),
**Pickup** (Pickup delay, Pickup failure, Handover issue), **Hub / Operations** (Hub processing delay,
Lost / damaged parcel, Wrong routing), **Payment / Money** (COD, Settlement, Fee, Compensation),
**Support** (Slow response, No response, Incorrect information, Repeated contact),
**Account / System** (App issue, Account issue, Feature issue), **Other** (Unclear, Non-actionable).

The LLM validator builds its allowed-label set **from this file**, so adding a sub-issue in YAML is
immediately accepted by both layers.

---

## 5. Hybrid classification

### Layer 1 — rules (`voc_classifier.py`), 100 % of rows

1. Normalise: lowercase → strip accents → expand abbreviations (`ko/k/hok → khong`, `dc → duoc`,
   `ship → giao`, …) → collapse repeated letters → strip punctuation.
2. Match every sub-issue's `any` + stakeholder-specific keywords (word-boundary; fuzzy for long tokens).
3. **Multi-issue**: all matched sub-issues are kept; primary = highest (hits × severity);
   the rest go to `secondary_issues`.
4. Dropdown `issue_type` is a *fallback* when text is empty/unclear (reference lesson #4) and a
   *conflict signal* when it disagrees with the text.
5. Output: `stakeholder, issue_group, sub_issue, secondary_issues, priority, owner, confidence,
   matched_signal, reason, human_review_flag, llm_candidate, llm_reason`.

Confidence: **High** = text keywords, single group · **Medium** = text keywords but multi-group,
or dropdown-only · **Low** = nothing matched / conflicting.

### Layer 2 — LLM (`llm_classifier.py`), only when needed

Gate (`llm_candidate = True`): negative VOC **and** any of — Low confidence, unclear-but-long
comment (≥ 15 chars), dropdown ↔ text conflict, ≥ 2 groups matched.

- Provider: `LLM_PROVIDER=openai` (any OpenAI-compatible `/chat/completions` endpoint via
  `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`), `mock` (deterministic, tests), `none` (default).
- Batched, JSON-only prompt that includes the taxonomy and stakeholder context.
- Validator: `issue_group`/`sub_issue` must exist in taxonomy; `confidence ∈ {High, Medium, Low}`.
  Invalid / error / timeout → **keep rule result**, record `llm_status`.
- Cache keyed by hash(prompt version + text) so re-runs are free.

---

## 6. Cross-stakeholder root-cause engine (the differentiator)

`config/drivers.yaml` describes **operational drivers** — the things that can simultaneously hurt
several stakeholders:

```yaml
hub_processing_delay:
  label: Hub processing delay
  owner: Operations
  voc_signals:                   # which sub-issues count as this driver's symptoms, per stakeholder
    customer: [Late delivery, Tracking / status]
    seller:   [Late delivery, Tracking / status, Repeated contact]
    rider:    [Hub processing delay]
  ops_metric: {event_type: sort_complete, field: processing_time, agg: mean}
```

Algorithm (`cross_stakeholder_analyzer.py` + `root_cause_analyzer.py`):

1. **Group** negative, classified VOC by driver (via its sub-issues per stakeholder).
2. **Compare stakeholders**: current window vs baseline (same length, prior period; baseline daily
   average for daily mode). Growth %, absolute Δ, per stakeholder.
3. **Localise**: concentration by region and hub (top hub share, lift vs baseline share).
4. **Cross-check operations**: ops metric for the same hub(s), current vs baseline; and at
   *tracking level*, the share of linked customer/seller complaints whose parcel passed the hub
   with `processing_time` above the baseline p90.
5. **Temporal alignment**: date the ops metric first exceeded threshold vs date VOC first spiked.
6. **Score evidence** (each criterion is a named, inspectable check):

| Check | Pass condition |
|---|---|
| Multi-stakeholder | ≥ 2 stakeholders with significant growth (≥ +20 % and ≥ min volume) |
| Location overlap | Same top hub for ≥ 2 stakeholders |
| Ops corroboration | Ops metric at that hub ≥ +20 % vs baseline |
| Parcel-level link | ≥ 40 % of linked complaints passed a delayed-hub event |
| Temporal alignment | Ops deterioration starts on/before the VOC spike |

Confidence: **High** ≥ 4 checks, **Medium** 2–3, **Low** ≤ 1.

7. **Wording guard**: High → "strong signal / likely driver"; Medium → "potential root cause";
   Low → "possible, needs validation". The word *cause* is never used without "potential/likely".
   The UI always shows the caveat "correlation, not proven causality".

---

## 7. Insight, priority, knowledge gap, action

**Insight object** (one per driver hypothesis and per significant single-stakeholder trend):

```
what, who, where, why, impact, recommended_action, owner, priority, confidence,
evidence[] (metric, baseline, current, delta, source, record_ids[]),
statements[] ({type: FACT | INFERENCE | RECOMMENDATION, text}),
drilldown: {examples, issue_distribution, region/hub, tickets, ops_events, help_articles, reasoning}
```

**Priority** (config weights, `priority.yaml`): points for volume, growth, number of stakeholders,
operational severity (taxonomy), repeat contacts (tickets per stakeholder_id), SLA breach
(first response > SLA). Score → P1 / P2 / P3. Priority reasons are listed, not hidden.
Impact text only cites measured quantities (repeat contacts, SLA breach %) — never invented money.

**Knowledge checker**: for each important issue × stakeholder, find Help Center articles
(`issue_type` match + keyword overlap), then check (a) article exists, (b) article covers the
"must-explain" concepts configured for that sub-issue, (c) `last_updated` ≤ 180 days. Also counts
what share of complaints raise the uncovered question → *"34 % of seller failed-delivery complaints
ask what happens after 2 attempts; article HC-004 does not explain the next step."*

**Action list** columns: `insight, root_cause, stakeholder, priority, owner, recommended_action,
evidence, status` (status defaults to `Open`).

---

## 8. Outputs

| Output | File |
|---|---|
| Main dashboard | `outputs/SPX_Voice_of_Operations_Dashboard.html` |
| Daily | `outputs/SPX_Daily_Operations_Intelligence_YYYYMMDD.html` |
| Weekly | `outputs/SPX_Weekly_VOC_Root_Cause_Report_YYYYWW.html` |
| Monthly | `outputs/SPX_Monthly_Operations_Intelligence_YYYYMM.html` |
| Action list | `outputs/SPX_Action_List.csv` + `.xlsx` |
| Classified records (traceability) | `outputs/voc_classified.csv` |
| Machine-readable insights | `outputs/insights.json` |

All HTML is self-contained (inline CSS/JS/SVG, no CDN) with light/dark themes.

---

## 9. End-to-end demo flow (what the judges see)

```
python run_local.py --mode demo
```

1. Generate (or reuse) synthetic data → validate schemas → clean → link.
2. Classify 100 % with rules; show `N` LLM candidates (LLM runs if `LLM_PROVIDER` is set).
3. Detect drivers → hypotheses → evidence → confidence → priority.
4. Write dashboard + 3 reports + action list, print a console summary:

```
⚠ Cross-stakeholder operational issue detected
  Potential root cause : Hub processing delay (HCM-ThuDuc-SOC)   confidence: High   P1
  Affected             : Customer +x% · Seller +y% · Rider +z%
  Ops signal           : sort_complete processing time +w% at HCM-ThuDuc-SOC
  Action               : Operations investigation (owner: Operations; CS/SS comms update)
```

5. Open the dashboard: KPI cards → *What changed?* trend with the incident week → *Who is
   affected?* → top emerging issues → cross-stakeholder root-cause bars → AI insight card →
   click → drill-down (VOC examples, tickets, ops events, Help Center, reasoning checks).

---

## 10. Build order (incremental, test after each)

1. Synthetic data generator + loader/cleaner/linker → `tests/test_data.py`
2. Taxonomy + normaliser + rule classifier + LLM layer (mock) → `tests/test_classifier.py`
3. Cross-stakeholder + root cause + knowledge + insight + action → `tests/test_root_cause.py`
4. Reports + dashboard + CLI → `tests/test_end_to_end.py`

## 11. Out of scope (deliberately)

Authentication, real SPX integrations, real PII, microservices, streaming/real-time infra,
multi-agent orchestration. This is a convincing hackathon MVP, not a production system.
