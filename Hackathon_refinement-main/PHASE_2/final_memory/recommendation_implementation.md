# Copilot Implementation Prompt — Pattern-Based Recommendation Engine

Paste everything below this line into Copilot as one instruction. It is written to be unambiguous: exact files, exact classes, exact contracts. Do not paraphrase or "improve" the structure — follow it exactly. Where a decision is not specified, stop and ask rather than guessing.

---

## 0. Context you must load before writing any code

Read these files fully before touching anything:

- `PHASE_2/backend/app/engines/recommendation_engine/models.py`
- `PHASE_2/backend/app/engines/recommendation_engine/signal_detectors.py`
- `PHASE_2/backend/app/engines/recommendation_engine/candidate_generator.py`
- `PHASE_2/backend/app/engines/recommendation_engine/impact_estimator.py`
- `PHASE_2/backend/app/engines/recommendation_engine/priority_engine.py`
- `PHASE_2/backend/app/engines/recommendation_engine/recommendation_validator.py`
- `PHASE_2/backend/app/engines/recommendation_engine/recommendation_engine_v2.py`
- `PHASE_2/backend/app/domain/models.py`
- `PHASE_2/backend/app/engines/spillover_engine.py`
- `PHASE_2/backend/app/engines/critical_path_engine.py`
- `PHASE_2/backend/app/engines/metrics_engine.py`
- `PHASE_2/backend/tests/test_candidate_generator.py`
- `PHASE_2/backend/tests/test_recommendation_engine_v2.py`

This is a refactor/extension of an **existing, working** signal → candidate → impact → priority pipeline. `signal_detectors.py` currently has 5 detector classes (`BlockerDetector`, `CapacityDetector`, `SprintDetector`, `CriticalPathDetector`, `ScheduleDetector`), each producing `OpportunitySignal` objects that `candidate_generator.py` turns into `RecommendationCandidate` objects with a `RecommendationAction`. You are **adding new detectors that follow the exact same pattern**, not replacing the pipeline.

---

## 1. The core principle (read this twice, it governs every decision below)

Every new detector must look **backward at history first**, then forward. A detector is not allowed to just look at the current sprint snapshot and flag a threshold breach — it must compute the pattern from completed historical data (sprints 1 through current-1) and use that pattern to (a) explain why something is about to go wrong again, and (b) size the recommended fix. If a detector cannot cite historical evidence for its signal, it is not one of these 9 detectors — do not build it here.

Every signal this prompt asks for must carry, in its `context` dict, the specific historical data point(s) that justify it (e.g. "this resource has hit 1.34x their estimate on 6 of the last 8 items" — not "this resource might be slow").

---

## 2. New enum values — add to `models.py`

### 2a. `SignalCategory` — add these members:
```python
ESTIMATION_RELIABILITY = "estimation_reliability"
SPOF = "single_point_of_failure"
RECURRING_BLOCKER = "recurring_blocker_category"
REWORK_LOOP = "rework_loop"
RAMP_UP = "ramp_up_discount"
RESEQUENCING = "resequencing_opportunity"
SWARM_TRADEOFF = "swarm_tradeoff"
```
(Keep existing members untouched. `SPILLOVER` category already exists — reuse it for the spillover root-cause detector, do not create a duplicate.)

### 2b. `RecommendationAction` — add these members:
```python
REBASELINE_ESTIMATE = "rebaseline_estimate"          # pattern 1
PAIR_REVIEWER = "pair_reviewer"                        # patterns 1, 4, 6, 7
ESCALATE_BLOCKER_EARLY = "escalate_blocker_early"       # patterns 2, 5
FREEZE_SCOPE_REQUEST = "freeze_scope_request"           # pattern 2
PULL_FORWARD_ITEM = "pull_forward_item"                 # pattern 3
SPLIT_AND_PAIR = "split_and_pair"                       # pattern 3 (distinct from existing SPLIT_ITEM — this one always has a named second resource)
ASSIGN_AS_SECOND_REVIEWER = "assign_as_second_reviewer" # pattern 3
CROSS_TRAIN_BACKUP = "cross_train_backup"               # pattern 4
INSERT_REVIEW_GATE = "insert_review_gate"               # pattern 6
APPLY_RAMP_UP_DISCOUNT = "apply_ramp_up_discount"        # pattern 7
RESEQUENCE_NON_CRITICAL_ITEM = "resequence_non_critical_item"  # pattern 8
SWARM_ITEM = "swarm_item"                               # pattern 9
```

Do not rename or remove any existing `RecommendationAction` member — `REASSIGN_ITEM`, `SPLIT_ITEM`, `ADVANCE_ITEM_TO_EARLIER_SPRINT`, `PARALLELIZE_ITEMS`, `REBALANCE_SPRINT_LOAD`, `REMOVE_DEPENDENCY_BOTTLENECK`, `ADD_RESOURCE_SKILL`, `RESOLVE_BLOCKER` all stay and are still used by the existing detectors.

### 2c. New dataclass — add to `models.py`:
```python
@dataclass(frozen=True)
class HistoricalPattern:
    pattern_type: str            # one of the 9 detector names below
    resource_id: str | None
    blocker_category: str | None
    sample_size: int             # number of historical data points the pattern is based on
    metric_name: str             # e.g. "actual_to_estimate_ratio"
    metric_value: float
    historical_occurrences: list[str]  # item_ids / sprint_ids / blocker_ids that make up the evidence
    confidence: str              # "HIGH" if sample_size >= 3, "MEDIUM" if 2, "LOW" if 1
```
Every new `OpportunitySignal.context` dict must include a `"historical_pattern": HistoricalPattern(...).__dict__` (or equivalent serializable form) entry. This is what makes the signal explainable to a PM — do not skip it.

---

## 3. New detector classes — add to `signal_detectors.py`

Each class below must be constructed with only the data already available to the pipeline (`ProjectState`, `cp_result`, `dag`, `impact_scores`, `metrics`, `SpilloverAnalysis`, `RiskResult` — check `recommendation_engine_v2.py` for what's already wired up and passed to detectors; reuse those objects, do not add new engine dependencies without checking first). Each class must implement a `detect(self) -> List[OpportunitySignal]` method, exactly matching the existing detector interface.

### 3.1 `EstimationReliabilityDetector` (pattern 1)
- For every resource, compute `actual_hrs / estimated_hrs` across all their **completed** work items (`WorkItemStatus.DONE` or equivalent — check `domain/models.py` for the exact status enum).
- Only compute a ratio if the resource has **2 or more** completed items (sample size floor — do not flag on 1 data point).
- Flag `HIGH` severity when the ratio is >= 1.3, `MEDIUM` when 1.2–1.3.
- Also flag chronic **under**-billers: ratio <= 0.7 across 2+ items, severity `LOW`, action recommendation differs (see candidate generator section).
- Context must include: resource_id, ratio, sample_size, list of item_ids used, and the resource's **remaining** (not-yet-started/in-progress) item_ids that would be affected by re-baselining.
- Do not emit a signal for a resource with no remaining items — there's nothing actionable.

### 3.2 `SpilloverRootCauseDetector` (pattern 2)
- For every historical spillover (an item that missed its original sprint and carried into a later one — check `spillover_engine.py`/`SpilloverAnalysis` for the existing carry-over data model, reuse it, do not recompute from scratch), classify the cause into one of: `dependency_blocked`, `resource_unavailable`, `estimate_wrong`, `scope_growth`, `toolchain_friction`. Use whatever cause/reason field already exists on the blocker/item data; if no explicit cause field exists in the domain model, derive it heuristically (blocker linked → `dependency_blocked`; resource had another active item in same window → `resource_unavailable`; `actual_hrs` far exceeds `estimated_hrs` with no blocker → `estimate_wrong`; item's `estimated_hrs` changed after sprint start → `scope_growth`) and clearly comment the heuristic in code.
- Group historical spillovers by `(cause, resource_id or blocker_category)` "signature".
- For the **current/upcoming** sprint, check whether any in-progress or upcoming item matches a signature that spilled before (same resource overloaded again, same blocker category still open, same dependency chain). If yes, emit a `SPILLOVER` category signal **before** the item is late, not after — this detector must be able to fire pre-emptively, unlike a simple "this item is already late" check.
- Context must include the matched historical signature, the sprint(s) it occurred in previously, and the cause classification.
- The recommended action must map to the cause: `dependency_blocked` → `ESCALATE_BLOCKER_EARLY`; `resource_unavailable` → `REBALANCE_SPRINT_LOAD` (existing action); `estimate_wrong` → `REBASELINE_ESTIMATE`; `scope_growth` → `FREEZE_SCOPE_REQUEST`; `toolchain_friction` → `INSERT_REVIEW_GATE`. This mapping decision belongs in the candidate generator (section 4), not hardcoded in the detector — the detector only classifies and signals.

### 3.3 `SPOFDetector` (pattern 4)
- Build a skill → resource-count map from `ProjectState` (use whatever skill/role field exists on resources in `domain/models.py`).
- Find skills covered by exactly 1 resource.
- Check whether any upcoming/in-progress critical-path item (`cp_result.items_on_critical_path`) requires that skill.
- If yes, and if a **second** resource has slack capacity (reuse the same slack computation `CapacityDetector` already does — check `capacity_detector` code above and call the same helper method or extract it to a shared util rather than reimplementing it), emit a `SPOF` signal with `CRITICAL` severity (this is a tail-risk detector — do not downgrade its severity even if the probability looks low; the framing is "one absence away from a repeat", not expected value).
- Context must include: skill name, the sole current resource, the candidate backup resource and their available slack hours, and — if it exists in project history — the past incident where this SPOF caused a velocity drop (cite the specific sprint).

### 3.4 `RecurringBlockerDetector` (pattern 5)
- Group all historical blockers (resolved and active) by `category` (and separately by `category + owner/stakeholder` if that field exists).
- For each group with **2 or more** occurrences, compute average and max historical time-to-resolution.
- For any **currently active** blocker in a category that has recurred before, compute days-until-overdue using the historical average/max resolution time (not the blocker's own `target_resolution_date` alone) and flag it as `CRITICAL` if projected resolution (raised_date + historical avg resolution time) would land after the blocker's current target or after project deadline.
- Context must include occurrence count, category, owner/stakeholder if available, average and max historical resolution days, and the specific prior blocker_ids that recurred (e.g. "3rd Daimler sign-off delay this quarter" style evidence — construct this from real field data, do not invent stakeholder names).
- This must fire even if the currently active blocker itself isn't overdue yet — the point is early escalation based on the category's historical track record.

### 3.5 `ReworkLoopDetector` (pattern 6)
- Detect items that were marked done/complete and then reopened or had additional hours logged after completion (check `domain/models.py` for a status-history or reopened flag; if none exists, infer from `actual_hrs` continuing to increase after a `completed_date` is set, and comment this clearly as a heuristic).
- Group by category/work-type (whatever categorical field exists — component, work type, etc.).
- If a category has **2 or more** rework incidents historically, and there are upcoming items in the same category without a review/QA step already modeled, emit a `REWORK_LOOP` signal.
- Context must include the category, the historical item_ids that had rework, and hours wasted (rework hours = hours logged after the original completion date).

### 3.6 `RampUpDetector` (pattern 7)
- Identify resources whose first work item start date is within N sprints of the current sprint (use the project's actual sprint length; treat "new joiner" as anyone in their first 2 sprints — if the codebase already has an onboarding/tenure field, use that instead of inferring from first item date).
- For each such resource, emit a `RAMP_UP` signal on their assigned upcoming/in-progress items recommending a temporary efficiency discount be applied to forecast hours for those items, plus a pairing recommendation on any of their items that are on the critical path.
- Context must include resource_id, sprint number they joined, and which of their items are affected.
- **Important**: this detector's output is primarily a **forecast input correction**, not just a recommendation card. Flag in your implementation notes (see section 6) that `forecast_engine.py` may need a hook to accept a per-resource discount factor — check whether that hook exists; if not, note it as a follow-up rather than silently forcing it into scope now.

### 3.7 `ResequencingDetector` (pattern 8)
- Find non-critical-path items currently scheduled to run serially with (i.e., assigned to the same resource, in the same or adjacent sprint as) a critical-path item, where there is **no actual dependency edge** in the DAG (`dag`) between them — i.e., the serialization is an assignment artifact, not a true dependency.
- Emit a `RESEQUENCING` signal recommending the non-critical item be moved off that resource's plate (reassigned or moved to a later sprint) to free calendar time for the critical-path work, with severity scaled by how many hours would be freed on the critical-path resource.
- Context must include: the critical-path item, the non-critical item wrongly serialized with it, hours freed, and confirmation (explicit) that no DAG edge exists between them — this must be checked programmatically against `dag`, not assumed.

### 3.8 `SwarmTradeoffDetector` (pattern 9)
- Only considered when the single largest critical-path bottleneck item cannot be split (check whatever "splittable" signal `CriticalPathDetector`/existing split logic already uses — reuse it, do not reinvent).
- If a second/third resource has any slack, compute: (a) days saved on the critical path if they swarm onto the bottleneck item, and (b) the specific delay this causes to whatever item that resource would otherwise have worked on.
- This detector's signal must carry **both numbers explicitly** in context (`days_saved_on_critical_path`, `delay_caused_to_other_item`, `other_item_id`, `other_resource_id`) — this is a last-resort, honest-tradeoff detector; do not emit it if you cannot compute the delay side, since a one-sided "this saves N days" number without the cost is exactly the failure mode this pattern exists to avoid.

---

## 4. `candidate_generator.py` changes

- Wire all 8 new detector classes into `CandidateGenerator` alongside the existing 5, following the exact same call pattern already used (look at how `BlockerDetector` etc. are instantiated and called — the constructor almost certainly takes the same shared engine outputs bundle; check `UpstreamEngineOutputs` in `models.py` and extend it if new detectors need something not already in there).
- For each new `OpportunitySignal`, produce one or more `RecommendationCandidate` objects using the new `RecommendationAction` members from section 2b, following the mapping given per-pattern above.
- Every new candidate's `target_ids` must be built the same way existing candidates do (check `stable_id(action_type.value, target_ids)` usage) so IDs stay stable and deduplicated across runs.
- Do not remove or alter behavior of the 8 existing action-generation blocks already in this file.

## 5. `impact_estimator.py` and `priority_engine.py` changes

- Every new `RecommendationAction` needs an impact-estimation path in `impact_estimator.py`. Follow the existing pattern for how `RESOLVE_BLOCKER` / `REBALANCE_SPRINT_LOAD` etc. estimate hours/days recovered — do not leave any new action type falling through to a default/zero estimate silently. If you cannot compute a real estimate for one of the 11 new actions, raise a clear `NotImplementedError` with a TODO comment rather than returning a fabricated number.
- `priority_engine.py` scoring must treat `SPOFDetector` signals as tail-risk (i.e., do not let expected-value scoring alone suppress a SPOF recommendation just because probability is low — check if there's already a severity-override or floor mechanism in the scorer; if not, add one gated on `SignalCategory.SPOF`).

## 6. Explainability / narrative requirement

Every new `Recommendation` produced from these detectors must, when rendered through `narrative_service.py` / `plan_explainer.py` (check both), be able to state the historical justification in one sentence, e.g. "Recommending X because the same pattern caused Sprint 4's spillover." Confirm the `HistoricalPattern` data added in section 2c flows all the way through to whatever renders recommendation text — do not let it get dropped at a serialization boundary. If the renderer needs a new template/branch to consume `historical_pattern`, add it; do not silently ignore this requirement.

## 7. Tests — required, not optional

For each of the 8 new detectors, add a test class in `tests/test_candidate_generator.py` (or a new `tests/test_signal_detectors_pattern_based.py` if that's cleaner — mirror however the existing 5 detectors are tested) covering:
1. A "pattern present" fixture that must produce the signal.
2. A "pattern absent / sample size too small" fixture that must **not** produce the signal (e.g. resource with only 1 completed item must not trigger `EstimationReliabilityDetector`).
3. A check that `context["historical_pattern"]` is populated and non-empty.

Also add at least one end-to-end test in `tests/test_recommendation_engine_v2.py` that runs the full pipeline on a fixture with a known repeating pattern (e.g. a resource that overran estimate on 3 prior items, with 1 remaining item) and asserts a `REBASELINE_ESTIMATE` recommendation comes out the other end with correct target and non-empty evidence.

Run the full existing test suite (`pytest PHASE_2/backend/tests`) after your changes and confirm nothing that currently passes breaks. Do not modify existing passing tests to make them pass — if an existing test breaks, that's a signal you changed shared behavior you shouldn't have.

## 8. Explicit non-goals — do not do these

- Do not touch the frontend (`Frontend/src/...`) in this pass. Recommendation cards will render generically through whatever component already renders `Recommendation` objects; if a new action type needs bespoke UI, that's a separate follow-up, not part of this task.
- Do not modify `forecast_engine.py`'s core algorithm beyond adding the optional ramp-up discount hook noted in 3.6, and only if it's a small, additive change. If it looks larger than that, stop and flag it instead of doing it.
- Do not change any of the 5 existing detector classes' detection logic — only add new classes and wire them in.
- Do not invent domain fields that don't exist in `domain/models.py`. If a pattern needs a field that isn't there (e.g. explicit spillover cause, reopened-item flag), implement the heuristic fallback as specified above and clearly comment it as a heuristic, so it's easy to replace later with real data if the schema is extended.

## 9. Deliverable summary

When done, provide:
1. A short changelog of every file touched and what changed.
2. Confirmation that `pytest PHASE_2/backend/tests` passes in full.
3. A list of any TODOs/NotImplementedErrors you had to leave (per section 5) with a one-line reason each.