# Lead Scoring and Routing: Design Rationale

**For:** Head of Marketing  
**Purpose:** A concise guide to how leads are prioritized and routed.

## Scoring categories

Each lead receives a score out of 100. The weights reflect the current priority on fit and decision-maker access, while readiness helps identify timely buying activity.

| Category | Weight | Signals considered |
|---|---:|---|
| **Company fit** | 40 points | Target industry (up to 20); company size (up to 10); infrastructure signals such as OpenShift, SIEM, on-premises, or cloud (up to 10). |
| **Requestor seniority** | 40 points | CTO, CIO, and CAIO score highest; configured VP, Head, and Director roles follow; Architect and Operations roles receive the next tier. |
| **Readiness** | 20 points | Budget evidence (up to 8); future purchase quarter (up to 6); repeat requests from the same company (up to 4); captured external engagement (up to 2). |

Subcategory and category caps keep the total score within 100.

## Deal category and routing

The system applies these rules in order; the first match sets the deal label:

1. Readiness score of 18 or higher → **Now or Never Deal**.
2. Otherwise, CTO/CIO/CAIO title → **Promising Lead**.
3. Otherwise, Financial Services or Healthcare industry score of at least 17.5 → **Hot Deal**.
4. Otherwise, matched infrastructure or target-industry signal → **Interesting Deal**.
5. No match → **Interesting Deal** by default.

The label helps reps orient quickly; the numeric score and supporting signals remain available to judge the evidence.

## Data handling

- **Company size:** Use tracked size when present; otherwise use self-reported size.
- **Repeat requests:** Aggregate the company's lead records into a request count and use it as one readiness signal.
- **Missing or unrecognized values:** Award zero for the affected signal and continue scoring the rest of the record.
- **Conflicting title matches:** Use the highest matching title tier.
- **Signal matching:** Industry and title use configured values/phrases. Budget, timeline, infrastructure, and engagement keywords are detected from captured fields.

## Workflow at lead arrival

```text
Source CSV
   ↓
Read records and refresh stable lead/company metadata
   ↓
Extract fields and score all configured signals
   ↓
Assign deal category using ordered routing rules
   ↓
Sort by score and notify up to 10 leads per run
   ↓
Record rep action and reminder history
```

GitHub Actions runs after qualifying repository changes or a manual dispatch. Each run ranks the available records and carries metadata forward for repeatable processing and audit history. The current workflow has no fixed processing interval or automatic schedule, and its notification limit is ten leads per run. Marketing should review volume and category outcomes as lead flow grows.

## Current scope

Readiness includes the configured budget, quarter, request-frequency, and external-engagement signals. Social or event activity affects the score only when represented in captured engagement data. More sources or signal types can be added as they become available.

## Future enhancements and flexibility

1. **Connect other data sources:** Stage 1 can be adapted to read from another datasource or API while preserving the downstream extraction, scoring, and routing stages.
2. **Adjust business priorities:** The team can update weights, signal values, and routing thresholds in `scoring_config.json` as market priorities change.
3. **Choose metadata storage:** Lead and audit metadata can be moved from repository files to another datasource or storage service as operational needs evolve.
