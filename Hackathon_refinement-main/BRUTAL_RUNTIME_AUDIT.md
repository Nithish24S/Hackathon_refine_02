# Brutal Runtime Audit Report

## Scope
This report is based on execution against the real uploaded workbook at:
- /workspaces/Hackathon_refine_01/Hackathon_refinement-main/PHASE_2/INPUT/TIO2_Sprint_Intelligence_v5_final.xlsx

The analysis was performed by running the actual parser, engine pipeline, and API routes rather than relying on documentation or assumptions.

---

## 1. Workbook Ingestion Evidence

### Parsed project state
- Sprints: 8
- Work items: 70
- Resources: 9
- Dependencies: 23
- Blockers: 5
- Current sprint context: Sprint 6 with 5 completed sprints and 3 remaining

### Resource and capacity snapshot
- Average allocation: 0.8917
- Average availability: 0.9089
- Underutilized resources: 2
- Active blockers: 1
- Critical path length: 5
- Critical path items: WI-001, WI-004, WI-030, WI-044

---

## 2. Deterministic Forecast Evidence

### Baseline forecast output
- Baseline on-time probability: 0.21
- Baseline expected delay: 8.08 days
- Baseline overall risk score: 40.42

### Interpretation
The baseline forecast is already signaling a materially risky delivery profile. The system is not showing a healthy trajectory for on-time delivery.

---

## 3. Recommendation Engine Evidence

### Recommendation generation
The recommendation engine produced a set of ranked actions. The runtime simulation showed that most recommendations were not materially useful.

### Recommendation simulation results
| Recommendation | Action Type | Simulated On-Time Probability | Delay Days | Risk Score | Outcome |
|---|---|---:|---:|---:|---|
| a180f3a2d5 | RESOLVE_BLOCKER | 0.415 | 0.86 | 35.21 | Strong positive effect |
| ae89811142 | REASSIGN_ITEM | 0.210 | 8.08 | 40.42 | No measurable benefit |
| 084c391055 | PARALLELIZE_ITEMS | 0.210 | 8.08 | 40.42 | No measurable benefit |
| 3d70f0653f | PARALLELIZE_ITEMS | 0.210 | 8.08 | 40.42 | No measurable benefit |
| 75640a7bd3 | REASSIGN_ITEM | 0.210 | 8.08 | 40.42 | No measurable benefit |
| 31bc084179 | ADVANCE_ITEM_TO_EARLIER_SPRINT | 0.210 | 8.08 | 40.42 | No measurable benefit |
| f724848172 | ADD_RESOURCE_SKILL | 0.033 | 18.48 | 69.40 | Harmful |
| 934fed56aa | SPLIT_ITEM | 0.233 | 7.51 | 39.47 | Minor benefit |
| 15a634960b | REBALANCE_SPRINT_LOAD | 0.210 | 8.08 | 40.42 | No measurable benefit |

### Key finding
Only one recommendation had a clearly meaningful impact: resolving the blocker. Most of the others did not improve the forecast at all, and one made the situation materially worse.

---

## 4. Recovery Plan Evidence

### Recovery plan generation
The recovery-plan engine generated three plans from the recommendation set.

### Runtime observation
The system logged a warning that the aggressive recovery plan scored lower than the safe plan, which indicates a flawed ranking or scoring logic rather than a robust planning mechanism.

### Interpretation
The recovery-plan output is not yet trustworthy as a prioritization mechanism because the highest-ranked plan is not clearly better than the alternatives in a logically consistent way.

---

## 5. API and Runtime Robustness Evidence

### Endpoint behavior
The FastAPI endpoints were exercised with the real workbook-backed runtime.

### Observed issues
- Forecast endpoint returned 422 without a session_id.
- Recommendations endpoint returned 422 without a session_id.
- Recovery-plans endpoint returned 422 without a session_id.
- When a dummy session_id was supplied, the route execution hit a datetime serialization error, showing the API response path is brittle.

### AI advisor status
- AI advisor initialization failed because BOSCH_API_KEY was not set.
- The system fell back to deterministic template explanations rather than a genuine AI-generated advisory layer.

---

## 6. Business and Technical Verdict

### Trustworthiness
Not yet trustworthy for PM decision support.

### Demo readiness
Partial. The pipeline runs and produces outputs, but the outputs are not consistently credible.

### Production readiness
No. The system still has material issues in recommendation quality, recovery-plan scoring, and API robustness.

### Bottom line
This is a working prototype with interesting mechanics, but it is not yet a reliable decision engine.

---

## 7. Final Judgment

- Status: Partial prototype
- Confidence: Low for real planning use
- Recommendation: Do not rely on it for stakeholder-facing delivery decisions until the recommendation quality and API robustness are fixed
