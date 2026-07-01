# Recovery Plan Layer — Architectural Roadmap

A design document, not an implementation guide. This sits above the Week
1–3 roadmap and the Validation phase — it assumes both are either done or
in progress, because Recovery Plans are built FROM validated, accurately-
scored recommendations. A Recovery Plan made of recommendations with wrong
impact numbers is just a worse-explained wrong answer at scale.

---

## 1. Where Recovery Plan generation sits in the architecture

It's a new layer, not a replacement of any existing one. The current
pipeline ends at:

```
Signal Detectors → Candidate Generator → Impact Estimator → Priority Engine → Recommendation Validator
                                                                      ↓
                                                          List[Recommendation] (ranked, validated)
```

Recovery Plan generation consumes that list as its input. It does not
re-derive signals, does not re-estimate impact, and does not duplicate
any logic from `impact_estimator.py`. It is purely combinatorial — it
asks "which subsets of this already-ranked list form a coherent,
non-conflicting plan, and which subset is best?"

```
List[Recommendation] (ranked, validated)
            ↓
  RecoveryPlanGenerator       — builds candidate plans (combinations)
            ↓
  RecoveryPlanSimulator       — runs SimulationEngine.simulate_scenario() per plan (already exists, unmodified)
            ↓
  RecoveryPlanScorer          — ranks plans by simulated outcome
            ↓
  RecoveryPlanExplainer       — narrative comparison across plans (extends RecommendationValidator's comparison logic)
            ↓
       List[RecoveryPlan] (ranked)
```

This sits in a new module:
`app/engines/recovery_plan_engine/` — a sibling directory to
`recommendation_engine/`, not nested inside it. They are peers: one
generates atomic actions, the other composes them into plans. Keeping
them as siblings (not parent/child) makes it structurally obvious that
the Recommendation Engine is not being deprecated — it's being composed
by a new consumer.

---

## 2. Should the Recommendation Engine change?

No, and this is the most important architectural decision in the whole
redesign. `RecommendationEngineV2.generate()` keeps its exact current
signature and exact current output: `List[Recommendation]`. Every file
in the Week 1–3 roadmap (signal_detectors, candidate_generator,
impact_estimator, priority_engine) and the Validation phase
(recommendation_validator) is built and tested completely independently
of whether a Recovery Plan layer exists.

The only change at this boundary is additive: `RecommendationEngineV2`
gains one new method that exposes its cached, already-computed
`UpstreamEngineOutputs` to the new layer, because Recovery Plan
simulation needs the same upstream object the individual simulations use
— it should not recompute it.

```python
def get_upstream(self) -> UpstreamEngineOutputs:
    return self._compute_upstream()
```

That's the entire footprint of this change on the existing engine. Every
recommendation card in the UI keeps working exactly as it does today —
"Simulate this fix" on a single recommendation does not go away. Recovery
Plans are an additional view, not a replacement view.

---

## 3. How Recovery Plans are generated from recommendations

This is a constrained combinatorial search, not a free-form generation
problem, which keeps it deterministic (a hard requirement per your
constraints).

### Step 1 — Conflict detection
Two recommendations conflict if they touch the same work item or the
same resource with incompatible actions (e.g. both reassign WI-059, or
one advances WI-054 to Sprint 5 while another splits it). This is
computable directly from existing fields — no new data needed:

```
conflicts(rec_a, rec_b) = True if:
    set(rec_a.affected_item_ids) ∩ set(rec_a.affected_item_ids) is non-empty
    AND rec_a.action_type and rec_b.action_type are mutually exclusive actions
        (e.g. REASSIGN_ITEM vs SPLIT_ITEM on the same item_id)
```

A small static compatibility table (which action-type pairs can coexist
on the same item) replaces what would otherwise be a fragile heuristic.
This table has at most 8×8 = 64 entries given the existing
`RecommendationAction` enum — small enough to hand-author and review,
not large enough to need a rules engine.

### Step 2 — Candidate plan construction
Rather than enumerating all 2^N subsets of the ranked list (combinatorial
explosion even for N=10), constrain generation to three plan archetypes,
which map directly to how a PM actually thinks about trade-offs:

- **Plan A — Highest impact, lowest risk.** Greedily take the
  highest-priority_score recommendations that don't conflict with each
  other, stopping once `confidence` would drop below HIGH/MEDIUM for any
  added item. This is the "safe, defensible" plan.
- **Plan B — Maximum delay recovery.** Greedily take recommendations by
  `estimated_delay_reduction_days` descending, allowing MEDIUM confidence
  items, stopping at a configurable cap (e.g. 5 actions) or when marginal
  delay recovery per action drops below a threshold. This is the
  "aggressive" plan.
- **Plan C — Minimum disruption.** Take only recommendations that don't
  touch the critical path or any resource above 90% load even after the
  change — i.e. prefer reassignments, scope splits, and underutilized-
  resource absorption over blocker escalations or critical-path
  reshuffling. This is the "safest changes, smallest blast radius" plan.

Three plans, not an open-ended search space, is also the right call for
a judge demo: comparing three labeled, intuitively-named options ("Safe",
"Aggressive", "Minimal disruption") is something a judge can hold in
their head. A combinatorial optimizer producing an unlabeled "optimal"
plan is less explainable and harder to defend live.

### Step 3 — Plan construction algorithm (deterministic, greedy, explainable)

```
function build_plan(ranked_recommendations, archetype, max_actions=5):
    plan = []
    used_item_ids = set()
    used_resource_ids = set()

    for rec in ranked_recommendations (sorted per archetype's sort key):
        if len(plan) >= max_actions:
            break
        if archetype excludes rec by its own filter rule:
            continue
        if conflicts(rec, plan_so_far):
            continue
        plan.append(rec)
        used_item_ids |= set(rec.affected_item_ids)
        used_resource_ids |= set(rec.affected_resource_ids)

    return RecoveryPlanCandidate(actions=plan, archetype=archetype)
```

Greedy, not exhaustive search — this keeps the system deterministic and
fast enough to run synchronously inside an API request, which matters
for demo responsiveness. A judge clicking "Generate Recovery Plans"
should see a result in under a second, not watch a spinner while a
search space is explored.

---

## 4. How Recovery Plans are scored

Scoring happens AFTER simulation, not before — this is important. A
plan's score is not the sum of its individual recommendations' estimated
impacts (that would double-count overlapping effects and ignore
interaction effects, like two reassignments both targeting the same
underloaded receiver). The score comes from actually running the
combined simulation and reading the real resulting state.

```python
class RecoveryPlanScore(BaseModel):
    deadline_probability: float        # from simulated MonteCarloResult
    expected_delay_days: float         # from simulated ForecastResult
    overall_risk_score: float          # from simulated RiskResult
    actions_required: int              # len(plan.actions)
    execution_complexity: str          # "Low" / "Medium" / "High" — derived from actions_required + whether any action needs external stakeholder (blocker escalation)
    composite_score: float             # weighted combination, see below
```

Composite score formula (deterministic, no ML, matches the existing
`ScoringWeights` philosophy already used in `priority_engine.py`):

```
composite_score =
    0.45 * deadline_probability
  + 0.30 * (1 - normalized_expected_delay_days)
  + 0.15 * (1 - normalized_risk_score)
  - 0.10 * normalized_execution_complexity
```

The complexity penalty is what stops the system from always recommending
the most aggressive plan — a plan requiring 7 coordinated actions across
4 people should lose some points relative to a 3-action plan with similar
probability, because the 3-action plan is more likely to actually get
executed correctly by a real team. This single design choice is what
makes the "Recommended ⭐" plan feel like it came from a PM's judgment
rather than a pure optimizer.

---

## 5. How simulation evaluates an entire plan instead of one recommendation

This requires no new simulation code. `SimulationEngine.simulate_scenario()`
(confirmed present in your codebase at line 418 of
`simulation_engine.py`) already accepts `Sequence[Union[Recommendation,
str]]`, already clones the project state once, already applies every
recommendation in the sequence via `self.applicator.apply(clone,
recommendation)` in a loop, and already re-runs the full engine pipeline
once at the end via `_recalculate_clone`. This is precisely "evaluate an
entire proposed future project state" — it already exists, it's just
been used for ad-hoc multi-select in the UI rather than for named,
labeled plan objects.

The Recovery Plan layer's simulation step is therefore:

```python
class RecoveryPlanSimulator:
    def __init__(self, simulation_engine: SimulationEngine):
        self.simulation_engine = simulation_engine

    def simulate_plan(self, plan: RecoveryPlanCandidate) -> ScenarioResult:
        return self.simulation_engine.simulate_scenario(plan.actions)
```

That's the entire simulation integration. No new apply logic, no new
state-mutation logic — it is a one-line call to code that already exists
and already works (once the Week 2 fixes to `_apply_reassign_work` and
`_apply_add_capacity` land, which the Recovery Plan layer depends on
being correct, since a plan combining a broken reassignment with a
correct blocker resolution would produce a misleadingly good number).

The only new piece is `build_revised_sprint_plan` from the Validation
roadmap — that already produces a structured before/after ownership
table from a clone, and Recovery Plans reuse it directly, once per plan,
to produce the "new sprint plan" view per option.

---

## 6. New data models required

All new models live in `app/engines/recovery_plan_engine/models.py`,
following the same dataclass pattern as
`recommendation_engine/models.py`.

```python
@dataclass(frozen=True)
class RecoveryPlanCandidate:
    plan_id: str
    archetype: str  # "SAFE", "AGGRESSIVE", "MINIMAL_DISRUPTION"
    actions: List[Recommendation]  # reuses existing Recommendation type — no duplication


@dataclass(frozen=True)
class RecoveryPlanScore:
    deadline_probability: float
    expected_delay_days: float
    overall_risk_score: float
    actions_required: int
    execution_complexity: str
    composite_score: float


@dataclass(frozen=True)
class RecoveryPlanExplanation:
    plan_id: str
    why_recommended: List[str]
    comparison_to_alternatives: List[str]   # reuses the comparison pattern from RecommendationValidator
    trade_offs: List[TradeOff]              # reuses TradeOff from the Validation phase — no duplication
    narrative_summary: str                  # the "Recovery Plan A is recommended because..." paragraph


@dataclass(frozen=True)
class RecoveryPlan:
    plan_id: str
    archetype: str
    label: str  # "Recommended", "Alternative", "Minimal disruption"
    actions: List[Recommendation]
    score: RecoveryPlanScore
    explanation: RecoveryPlanExplanation
    revised_sprint_plan: List[Dict[str, Any]]  # reuses build_revised_sprint_plan output structure
    scenario_result: ScenarioResult  # the raw simulation output, for drill-down
```

Note how much this reuses: `Recommendation`, `TradeOff`,
`ScenarioResult`, and the `build_revised_sprint_plan` output shape are
all imported, never redefined. This is deliberate — it keeps the new
layer thin and makes it obvious in code review that nothing from the
existing pipeline was duplicated or forked.

---

## 7. What APIs need to change

No existing endpoint changes behavior or response shape. Three new
endpoints are added, all in a new router file
`app/api/routes/recovery_plans.py`:

```
GET  /api/recovery-plans?session_id=...
     → generates all 3 plan archetypes, simulates each, scores each,
       returns them ranked with the top one labeled "Recommended"

GET  /api/recovery-plans/{plan_id}?session_id=...
     → full detail for one plan: actions, score, explanation,
       revised_sprint_plan, scenario_result

POST /api/recovery-plans/apply
     body: { plan_id, session_id }
     → applies the plan's actions to the actual session state
       (not a clone) — this is the "Apply Plan" button from your
       proposed UI flow. Internally this is just calling
       ActionApplicator.apply_many() against the real session's
       ProjectState instead of a clone, reusing existing apply logic.
```

The existing `/api/recommendations`, `/api/recommendations/simulate`, and
`/api/recommendations/scenario` endpoints are untouched. A judge or a
future developer can still call them directly and get individual
recommendation behavior exactly as before — this matters because some
demo moments (showing the granular "why" on one specific blocker) work
better as a single-recommendation drill-down than as a whole-plan view,
and you want both available.

---

## 8. How the frontend evolves

This is purely additive to `Dashboard.jsx` — a new top-level tab
alongside the existing Overview / Risk / Critical Path / Forecast /
Actions tabs, called **Recovery Plans**. The existing Actions tab (with
its individual recommendation cards, Select checkboxes, and "Simulate
selection" button) is not removed — it remains as the place where a
judge or PM can inspect and manually combine individual actions, which is
still valuable as a power-user / drill-down view.

The new Recovery Plans tab follows this flow:

```
[Recovery Plans tab opens]
        ↓
Three plan cards shown side by side: Safe / Aggressive / Minimal disruption
One is visually marked "Recommended ⭐" (the highest composite_score)
Each card shows: deadline probability, expected finish date, delay
reduction, number of actions, execution complexity badge
        ↓
[Click a plan card]
        ↓
Expanded view: list of actions in the plan (each one a mini version of
the existing recommendation card), the narrative explanation paragraph,
trade-offs, and the revised sprint plan table (reused component from the
Validation roadmap's 9e section)
        ↓
[Compare Plans button] → side-by-side table: probability / delay /
risk / complexity columns, one row per plan
        ↓
[Apply Plan button] → confirmation modal → POST /api/recovery-plans/apply
```

The "Compare Plans" table is the single highest-value new UI element for
judges, because it's the most direct visual answer to "what is the best
recovery pathway" — three rows, four columns, one glance. Build this
before the individual plan detail view if time is short; it's higher
demo value per hour of frontend work.

---

## 9. Which parts of the current roadmap become obsolete

None. This is worth stating explicitly because it's the core promise of
this redesign: every file in the Week 1–3 roadmap and the Validation
phase roadmap remains necessary and unchanged in scope.

- `signal_detectors.py`, `candidate_generator.py`, `impact_estimator.py`,
  `priority_engine.py` — still produce the atomic recommendations that
  Recovery Plans are built from. Without accurate per-recommendation
  numbers, Recovery Plan scores are garbage in, garbage out.
- `recommendation_validator.py` — still answers "why was THIS
  recommendation selected" for the individual cards inside an expanded
  plan view. The Recovery Plan layer's own explainer reuses its
  comparison-building helper methods rather than reimplementing them.
- `simulation_engine.py` fixes (the reassign-direction bug, the
  add-capacity named-resource bug) — these are even MORE critical for
  Recovery Plans than for single-recommendation simulation, because a
  plan combining 3-4 actions will compound any simulation bug 3-4x.

If anything, this redesign raises the stakes on getting the Week 1-3
foundation correct, rather than replacing the need for it.

---

## 10. New phases to add to the roadmap

**Phase 6 — Recovery Plan Engine (new, after Validation phase)**

Day-by-day, assuming Week 1–3 and Validation are complete:

- Day 1: `recovery_plan_engine/models.py` — the 4 new dataclasses above
- Day 1–2: `recovery_plan_engine/plan_generator.py` — conflict detection
  table + the 3 archetype builders + greedy construction algorithm
- Day 2: `recovery_plan_engine/plan_simulator.py` — thin wrapper around
  existing `SimulationEngine.simulate_scenario()`, plus the scoring
  formula from section 4
- Day 3: `recovery_plan_engine/plan_explainer.py` — extends
  `RecommendationValidator`'s comparison logic to compare plans instead
  of individual recommendations; produces the narrative paragraph
- Day 3–4: `routes/recovery_plans.py` — the 3 new endpoints, plus
  Pydantic response models in a new `models_recovery_plans.py` following
  the same pattern as `models_phase3.py`
- Day 4–5: `Dashboard.jsx` — new Recovery Plans tab, the 3-card layout,
  the Compare Plans table, the expanded plan detail view (reusing the
  revised-sprint-plan table component already built in the Validation
  roadmap)
- Day 5: end-to-end test — generate plans against the demo workbook,
  confirm the 3 archetypes produce genuinely different action sets (not
  the same plan three times, which would undercut the entire value
  proposition), confirm Compare Plans table renders correctly, prepare
  demo narrative

**Updated demo narrative** (replaces the single-recommendation narrative
from the earlier roadmap):

> "Sprint 6 starts today. We're at 7% probability of hitting the
> deadline. Instead of showing you a list of disconnected fixes, the tool
> built three complete recovery plans." [show 3 cards] "Plan A — the
> recommended one — resolves the blocker, rebalances Meena's overload,
> and protects the dependency chain. Three actions, 91% probability,
> finishing June 28." [click Compare Plans] "Here's why it beats the
> alternatives: Plan B recovers similar probability but needs a temporary
> resource Bosch would have to source externally. Plan C is safer but
> only gets us to 84%." [click Apply Plan] "This is the new sprint plan
> the team executes tomorrow morning."

This is structurally the same demo as before, but answers a higher-order
question — not "what should I fix" but "what should I DO" — which is the
exact gap the product vision prompt identifies.

---

## Summary table

| Layer | Status | Why |
|---|---|---|
| Parser, Metrics, Forecast, Monte Carlo, Risk | Unchanged | Foundation, never touched |
| Signal Detectors, Candidate Generator, Impact Estimator, Priority Engine | Unchanged in scope, must be correct (Week 1-3 roadmap) | Recovery Plans are built from their output |
| Recommendation Validator | Unchanged in scope, reused | Provides comparison-logic helpers the plan explainer extends |
| Simulation Engine | Unchanged interface, bug fixes still required | `simulate_scenario()` already does what plan simulation needs |
| **Recovery Plan Engine** | **New** | Combinatorial layer: generate, simulate, score, explain plans |
| API routes | Additive only | 3 new endpoints, 0 existing endpoints changed |
| Frontend | Additive only | New tab, existing Actions tab untouched |
