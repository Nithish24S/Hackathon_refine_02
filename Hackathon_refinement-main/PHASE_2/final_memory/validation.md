# Phase 5 — Recommendation Validation

A new, standalone phase that runs AFTER priority_engine.py ranks
recommendations and BEFORE they're serialized to the API. This is not a
rewrite of anything in the previous roadmap — it's a new file that reads
data already sitting in `Recommendation`, `OpportunitySignal`, and
`ImpactEstimate` objects (their `evidence`, `context`, and
`calculation_notes` fields already exist) and turns it into the
structured explanation your example shows.

Do this phase last, after the Week 1–3 roadmap is fully working. It
depends on accurate signals and impact estimates — validating a bad
number just produces a confident-sounding wrong answer, which is worse
than no explanation at all.

---

## Why this is a separate file, not edits to existing ones

`signal_detectors.py`, `candidate_generator.py`, `impact_estimator.py`,
and `priority_engine.py` each answer one question: what's wrong, what
could we do, how much would it help, how should we rank it. None of them
compare option A against option B, or state a trade-off, because none of
them has visibility into the full ranked list at the same time —
`priority_engine.py` produces the ranked list but doesn't loop back to
annotate it.

A new file, `recommendation_validator.py`, sits in
`app/engines/recommendation_engine/` alongside the others and runs once
the full ranked list exists. It takes the list, the upstream engine
outputs, and produces a `RecommendationValidation` object attached to
each recommendation.

---

## New file: `app/engines/recommendation_engine/recommendation_validator.py`

### Step 1 — New data model

Add this to `app/engines/recommendation_engine/models.py`, after the
existing `Recommendation` class (after line 121, before `to_api_dict`'s
closing or right after the class ends):

```python
@dataclass(frozen=True)
class TradeOff:
    description: str
    severity: str  # "minor", "moderate", "significant"


@dataclass(frozen=True)
class RecommendationValidation:
    recommendation_id: str
    why_selected: List[str]
    why_better_than_alternatives: List[str]
    rejected_alternatives: List[str]
    delay_reduction_summary: str
    probability_improvement_summary: str
    confidence_label: ConfidenceLevel
    confidence_reasoning: str
    trade_offs: List[TradeOff]
    one_line_pitch: str
```

This is the object your example maps onto directly:
`why_selected` → the 4 bullet points ("Meena is overloaded by 38%",
"Ravi has 42 hours free", etc), `delay_reduction_summary` → "8.4 → 3.1
days", `probability_improvement_summary` → "68% → 91%",
`confidence_label` → "High", `trade_offs` → anything given up by
choosing this (e.g. "Ravi's other task WI-062 slips by 1 day").

### Step 2 — The validator class

```python
from __future__ import annotations

from typing import Dict, List

from app.domain.models import ProjectState
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    OpportunitySignal,
    Recommendation,
    RecommendationAction,
    RecommendationValidation,
    TradeOff,
    UpstreamEngineOutputs,
)


class RecommendationValidator:
    """
    Runs after PriorityEngine. Takes the full ranked list and produces a
    RecommendationValidation per recommendation, comparing each one
    against the others in the same category so 'why is this better than
    the alternatives' has real alternatives to point at.
    """

    def __init__(
        self,
        project_state: ProjectState,
        upstream: UpstreamEngineOutputs,
        signals_by_id: Dict[str, OpportunitySignal],
    ) -> None:
        self.project_state = project_state
        self.upstream = upstream
        self.signals_by_id = signals_by_id
        self._items = {wi.item_id: wi for wi in project_state.work_items}
        self._resources = {r.resource_id: r for r in project_state.resources if hasattr(project_state, "resources")} if hasattr(project_state, "resources") else {r.resource_id: r for r in project_state.team}

    def validate_all(self, ranked: List[Recommendation]) -> Dict[str, RecommendationValidation]:
        result: Dict[str, RecommendationValidation] = {}
        for rec in ranked:
            alternatives = self._find_alternatives(rec, ranked)
            result[rec.recommendation_id] = self._validate_one(rec, alternatives)
        return result

    def _find_alternatives(self, rec: Recommendation, ranked: List[Recommendation]) -> List[Recommendation]:
        """Alternatives are other recommendations that touch the SAME
        affected items, resources, or blockers — i.e. genuinely competing
        options for solving the same problem, not just any other card."""
        rec_targets = set(rec.affected_item_ids) | set(rec.affected_resource_ids) | set(rec.affected_blocker_ids)
        if not rec_targets:
            return []
        alternatives = []
        for other in ranked:
            if other.recommendation_id == rec.recommendation_id:
                continue
            other_targets = set(other.affected_item_ids) | set(other.affected_resource_ids) | set(other.affected_blocker_ids)
            if rec_targets & other_targets:
                alternatives.append(other)
        return alternatives

    def _validate_one(self, rec: Recommendation, alternatives: List[Recommendation]) -> RecommendationValidation:
        why_selected = self._build_why_selected(rec)
        why_better, rejected = self._build_comparison(rec, alternatives)
        confidence_reasoning = self._build_confidence_reasoning(rec)
        trade_offs = self._build_trade_offs(rec)

        delay_before = round(self.upstream.forecast.expected_delay_days, 1)
        delay_after = round(max(0.0, delay_before - rec.estimated_delay_reduction_days), 1)
        delay_summary = f"{delay_before}d → {delay_after}d"

        prob_before = round(self.upstream.monte_carlo.on_time_probability * 100, 0) if hasattr(self.upstream.monte_carlo, "on_time_probability") else 0
        prob_gain_pct = round(rec.estimated_risk_reduction * 100, 0)
        prob_after = min(100, prob_before + prob_gain_pct)
        prob_summary = f"{int(prob_before)}% → {int(prob_after)}%"

        pitch = self._build_one_line_pitch(rec, delay_before, delay_after)

        return RecommendationValidation(
            recommendation_id=rec.recommendation_id,
            why_selected=why_selected,
            why_better_than_alternatives=why_better,
            rejected_alternatives=rejected,
            delay_reduction_summary=delay_summary,
            probability_improvement_summary=prob_summary,
            confidence_label=rec.confidence,
            confidence_reasoning=confidence_reasoning,
            trade_offs=trade_offs,
            one_line_pitch=pitch,
        )

    def _build_why_selected(self, rec: Recommendation) -> List[str]:
        """
        Pull the human-readable 'why' bullets straight from the signal
        context and the candidate's own simulation_params — this data
        already exists from Tier 1, we are just surfacing it as bullets
        instead of a paragraph.
        """
        bullets: List[str] = []
        signal = self.signals_by_id.get(rec.root_cause_signal_id)
        ctx = signal.context if signal else {}

        if rec.action_type == RecommendationAction.REASSIGN_ITEM:
            bullets.extend(self._why_reassign(rec, ctx))
        elif rec.action_type == RecommendationAction.RESOLVE_BLOCKER:
            bullets.extend(self._why_resolve_blocker(rec, ctx))
        elif rec.action_type == RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT:
            bullets.extend(self._why_advance_item(rec, ctx))
        elif rec.action_type == RecommendationAction.PARALLELIZE_ITEMS:
            bullets.extend(self._why_parallelize(rec, ctx))
        else:
            bullets.append(rec.description)

        return bullets or [rec.description]

    def _why_reassign(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        load_ratio = ctx.get("load_ratio")
        if load_ratio:
            overload_pct = round((load_ratio - 1.0) * 100)
            source_name = self._resource_name((rec.affected_resource_ids or [None])[0])
            if overload_pct > 0:
                bullets.append(f"{source_name} is overloaded by {overload_pct}%")
            else:
                bullets.append(f"{source_name} has a load imbalance ({round(load_ratio*100)}% of capacity)")

        receiver_id = rec.metadata.get("simulation_params", {}).get("receiving_resource_id") if rec.metadata else None
        if receiver_id:
            receiver = self._resources.get(receiver_id)
            receiver_name = receiver.name if receiver else receiver_id
            free_hours = self._free_hours(receiver_id)
            if free_hours is not None:
                bullets.append(f"{receiver_name} has {round(free_hours)} hours free")
            item_id = (rec.affected_item_ids or [None])[0]
            item = self._items.get(item_id) if item_id else None
            if item and receiver:
                required_skill = getattr(item, "required_skill", None)
                if required_skill and (receiver.primary_skill == required_skill or receiver.secondary_skill == required_skill):
                    bullets.append(f"Story requires {required_skill} skill, which {receiver_name} has")

        dep_conflict = self._has_dependency_conflict(rec.affected_item_ids)
        bullets.append("No dependency conflict" if not dep_conflict else f"Note: dependency conflict on {dep_conflict}")

        return bullets

    def _why_resolve_blocker(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        blocker_id = (rec.affected_blocker_ids or [None])[0]
        blocker = next((b for b in self.project_state.blockers if b.blocker_id == blocker_id), None)
        if blocker:
            severity = blocker.severity.value if hasattr(blocker.severity, "value") else str(blocker.severity)
            bullets.append(f"{severity} severity blocker, blocking {len(blocker.impacted_item_ids or [])} item(s)")
        overdue = ctx.get("days_overdue", 0)
        if overdue and overdue > 0:
            bullets.append(f"{overdue} day(s) past target resolution date")
        on_cp = ctx.get("on_critical_path", False)
        if on_cp:
            bullets.append("Blocking items are on the critical path")
        return bullets

    def _why_advance_item(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        item_id = (rec.affected_item_ids or [None])[0]
        item = self._items.get(item_id) if item_id else None
        if item:
            downstream_count = sum(
                1 for dep in self.project_state.dependencies
                if dep.predecessor_item_id == item_id
            )
            if downstream_count > 0:
                bullets.append(f"Prerequisite for {downstream_count} downstream item(s)")
        spillover_days = ctx.get("delay_breakdown", {}).get("spillover_days") if isinstance(ctx.get("delay_breakdown"), dict) else None
        if spillover_days:
            bullets.append(f"Contributes to {round(spillover_days, 1)} days of predicted spillover")
        return bullets

    def _why_parallelize(self, rec: Recommendation, ctx: dict) -> List[str]:
        bullets = []
        cp_length = ctx.get("cp_remaining_hours")
        if cp_length:
            bullets.append(f"{round(cp_length)} hours remain on the critical path")
        return bullets

    def _build_comparison(self, rec: Recommendation, alternatives: List[Recommendation]) -> tuple[List[str], List[str]]:
        """
        Compare this recommendation's priority_score and impact against
        each alternative targeting the same problem. Produce both a
        'why better' list and a list of what was rejected and why.
        """
        if not alternatives:
            return [], []

        why_better = []
        rejected = []

        for alt in alternatives:
            if alt.priority_score < rec.priority_score:
                reason = self._compare_one(rec, alt)
                if reason:
                    why_better.append(reason)
                rejected.append(f"{alt.title} (priority {round(alt.priority_score*100)} vs {round(rec.priority_score*100)})")

        return why_better, rejected

    def _compare_one(self, rec: Recommendation, alt: Recommendation) -> str:
        if rec.estimated_delay_reduction_days > alt.estimated_delay_reduction_days + 0.5:
            return f"Recovers {round(rec.estimated_delay_reduction_days - alt.estimated_delay_reduction_days, 1)} more days of delay than \"{alt.title}\""
        if rec.confidence == ConfidenceLevel.HIGH and alt.confidence != ConfidenceLevel.HIGH:
            return f"Higher confidence than \"{alt.title}\" ({rec.confidence.value} vs {alt.confidence.value})"
        if rec.estimated_risk_reduction > alt.estimated_risk_reduction + 0.05:
            return f"Larger risk reduction than \"{alt.title}\""
        return f"Ranked higher than \"{alt.title}\" on combined priority score"

    def _build_confidence_reasoning(self, rec: Recommendation) -> str:
        if rec.confidence == ConfidenceLevel.HIGH:
            return "Based on directly measured data (actual hours, actual load ratios, actual blocker status) with no estimation uncertainty."
        if rec.confidence == ConfidenceLevel.MEDIUM:
            return "Based on a mix of measured data and reasonable assumptions about how the team will respond to this change."
        return "Based on a coarse estimate — treat the impact numbers as directional, not precise."

    def _build_trade_offs(self, rec: Recommendation) -> List[TradeOff]:
        trade_offs = []
        receiver_id = rec.metadata.get("simulation_params", {}).get("receiving_resource_id") if rec.metadata else None
        if receiver_id and rec.action_type == RecommendationAction.REASSIGN_ITEM:
            receiver_other_load = self._other_committed_hours(receiver_id, exclude_item_ids=rec.affected_item_ids)
            if receiver_other_load and receiver_other_load > 0:
                trade_offs.append(TradeOff(
                    description=f"Receiving resource already has {round(receiver_other_load)}h of other committed work this sprint",
                    severity="minor" if receiver_other_load < 20 else "moderate",
                ))
        if rec.action_type == RecommendationAction.RESOLVE_BLOCKER:
            trade_offs.append(TradeOff(
                description="Requires external stakeholder action (escalation), not fully within team control",
                severity="moderate",
            ))
        if not trade_offs:
            trade_offs.append(TradeOff(description="No significant trade-offs identified", severity="minor"))
        return trade_offs

    def _build_one_line_pitch(self, rec: Recommendation, delay_before: float, delay_after: float) -> str:
        return f"{rec.title} — recovers {round(delay_before - delay_after, 1)} days, {rec.confidence.value.lower()} confidence."

    def _resource_name(self, resource_id: str) -> str:
        r = self._resources.get(resource_id)
        return r.name if r else (resource_id or "Unknown")

    def _free_hours(self, resource_id: str) -> float | None:
        dev = next((dm for dm in self.upstream.metrics.resource_metrics.developer_metrics if dm.resource_id == resource_id), None)
        if dev is None:
            return None
        resource = self._resources.get(resource_id)
        if not resource:
            return None
        capacity = (resource.daily_capacity_hrs or 0.0) * (self.project_state.project_info.sprint_duration_days or 10)
        return max(0.0, capacity - dev.remaining_effort_hours)

    def _has_dependency_conflict(self, item_ids: List[str]) -> str | None:
        for item_id in item_ids:
            for dep in self.project_state.dependencies:
                if dep.successor_item_id == item_id:
                    pred = self._items.get(dep.predecessor_item_id)
                    if pred and pred.status not in ("Completed", "Done"):
                        return dep.predecessor_item_id
        return None

    def _other_committed_hours(self, resource_id: str, exclude_item_ids: List[str]) -> float:
        return sum(
            wi.remaining_effort_hrs
            for wi in self.project_state.work_items
            if wi.assigned_resource == resource_id and wi.item_id not in exclude_item_ids
        )
```

> This is a first-pass implementation grounded in your actual model
> fields (`OpportunitySignal.context`, `Recommendation.metadata`,
> `developer_metrics`, `dependencies`). Some of the `ctx.get(...)` keys
> referenced here (`load_ratio`, `days_overdue`, `on_critical_path`,
> `delay_breakdown`) only exist if you've already done the Week 1
> signal_detectors.py fixes from the previous roadmap — this is exactly
> why this phase comes last.

---

## Wiring it into the pipeline

### `recommendation_engine_v2.py` — one new step

In `generate()` (the method that already runs
signals → candidates → impact_estimates → ranked), add the validation
call right before `return list(self._cached_recommendations)`:

```python
signals_by_id = {s.signal_id: s for s in signals}
validator = RecommendationValidator(self.project_state, upstream, signals_by_id)
self._cached_validations = validator.validate_all(actionable[:top_n])

self._cached_recommendations = actionable[:top_n]
return list(self._cached_recommendations)
```

Add `self._cached_validations: Dict[str, RecommendationValidation] = {}`
to `__init__`, and add a new public method:

```python
def get_validation(self, recommendation_id: str) -> Optional[RecommendationValidation]:
    return self._cached_validations.get(recommendation_id)
```

Import `RecommendationValidator` and `RecommendationValidation` at the
top of the file alongside the existing imports from
`recommendation_engine.models`.

### `models_phase3.py` — API shape

Add a new Pydantic model after `RecommendationSummary` (after line 429):

```python
class TradeOffResponse(BaseModel):
    description: str
    severity: str


class RecommendationValidationResponse(BaseModel):
    why_selected: List[str] = Field(default_factory=list)
    why_better_than_alternatives: List[str] = Field(default_factory=list)
    rejected_alternatives: List[str] = Field(default_factory=list)
    delay_reduction_summary: str = Field(default="")
    probability_improvement_summary: str = Field(default="")
    confidence_label: str = Field(default="MEDIUM")
    confidence_reasoning: str = Field(default="")
    trade_offs: List[TradeOffResponse] = Field(default_factory=list)
    one_line_pitch: str = Field(default="")
```

Then add ONE new field to `RecommendationSummary`:
```python
validation: Optional[RecommendationValidationResponse] = Field(None, description="Why this recommendation was selected and how it compares to alternatives")
```

### `routes/recommendations.py` — populate it

In `_recommendation_to_summary` (where you already added `urgency`,
`action_summary` etc from the previous roadmap), add one more parameter
`validation: Optional[RecommendationValidation] = None`, and populate the
new field:

```python
validation_response = None
if validation:
    validation_response = RecommendationValidationResponse(
        why_selected=validation.why_selected,
        why_better_than_alternatives=validation.why_better_than_alternatives,
        rejected_alternatives=validation.rejected_alternatives,
        delay_reduction_summary=validation.delay_reduction_summary,
        probability_improvement_summary=validation.probability_improvement_summary,
        confidence_label=validation.confidence_label.value if hasattr(validation.confidence_label, "value") else str(validation.confidence_label),
        confidence_reasoning=validation.confidence_reasoning,
        trade_offs=[TradeOffResponse(description=t.description, severity=t.severity) for t in validation.trade_offs],
        one_line_pitch=validation.one_line_pitch,
    )
```

Add `validation=validation_response,` to the `RecommendationSummary(...)`
constructor call.

At the call site (`get_recommendations` route, around line 242), after
getting `recommendations = engine.generate(...)`, fetch each
recommendation's validation via `engine.get_validation(rec.recommendation_id)`
and pass it through.

---

## Frontend — `Dashboard.jsx`

Add this as a new expandable block inside the existing `recs.map(rec =>
(` loop, after the resource load bars and dependency chain sections from
the previous roadmap (Phase 9b/9c), still inside the
`<div className="flex-1">` wrapper:

```jsx
{rec.validation && (
  <details className="mt-4 rounded-2xl border border-slate-700 bg-slate-900/60 p-3">
    <summary className="cursor-pointer text-sm font-semibold text-emerald-300">Why this recommendation?</summary>
    <div className="mt-3 space-y-3 text-sm">
      <div>
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Why selected</div>
        <ul className="space-y-1 text-slate-300">
          {rec.validation.why_selected.map((point, i) => (
            <li key={i} className="flex gap-2"><span className="text-emerald-400">•</span>{point}</li>
          ))}
        </ul>
      </div>

      {rec.validation.why_better_than_alternatives.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Why better than alternatives</div>
          <ul className="space-y-1 text-slate-300">
            {rec.validation.why_better_than_alternatives.map((point, i) => (
              <li key={i} className="flex gap-2"><span className="text-sky-400">•</span>{point}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl bg-slate-950 p-2">
          <div className="text-xs text-slate-500">Expected delay</div>
          <div className="text-white font-semibold">{rec.validation.delay_reduction_summary}</div>
        </div>
        <div className="rounded-xl bg-slate-950 p-2">
          <div className="text-xs text-slate-500">Deadline probability</div>
          <div className="text-white font-semibold">{rec.validation.probability_improvement_summary}</div>
        </div>
      </div>

      <div>
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Confidence: {rec.validation.confidence_label}</div>
        <div className="text-slate-400 text-xs">{rec.validation.confidence_reasoning}</div>
      </div>

      {rec.validation.trade_offs.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Trade-offs</div>
          <ul className="space-y-1">
            {rec.validation.trade_offs.map((t, i) => (
              <li key={i} className="flex gap-2 text-xs">
                <span className={t.severity === 'significant' ? 'text-rose-400' : t.severity === 'moderate' ? 'text-amber-400' : 'text-slate-500'}>●</span>
                <span className="text-slate-300">{t.description}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  </details>
)}
```

This block, expanded, produces exactly the layout in your example: a
bulleted "why" list, expected delay and probability as two stat boxes,
confidence with reasoning, and trade-offs underneath.

---

## Copilot prompts, in order

**Prompt 1** — models:
> "In app/engines/recommendation_engine/models.py, add two new frozen
> dataclasses after the existing Recommendation class: TradeOff
> (description: str, severity: str) and RecommendationValidation
> (recommendation_id: str, why_selected: List[str],
> why_better_than_alternatives: List[str], rejected_alternatives:
> List[str], delay_reduction_summary: str,
> probability_improvement_summary: str, confidence_label:
> ConfidenceLevel, confidence_reasoning: str, trade_offs: List[TradeOff],
> one_line_pitch: str). Do not modify any existing class in this file."

**Prompt 2** — the validator file (give Copilot the full code block from
"Step 2" above as a file to create, don't ask it to write this from
scratch — paste the code and ask it to adapt only the import paths and
field names if they don't match exactly):
> "Create a new file
> app/engines/recommendation_engine/recommendation_validator.py with this
> exact content [paste the RecommendationValidator class]. First check
> app/domain/models.py to confirm whether ProjectState has a `resources`
> attribute or only `team` — adjust the `_resources` dict construction in
> __init__ accordingly, using whichever one actually exists. Also confirm
> the exact attribute name for on-time probability on the monte_carlo
> upstream object (check app/engines/monte_carlo_engine.py for the
> MonteCarloResult class) and fix `on_time_probability` references if the
> real field name differs."

**Prompt 3** — wire into orchestrator:
> "In recommendation_engine_v2.py, import RecommendationValidator and
> RecommendationValidation from recommendation_engine.models and
> recommendation_engine.recommendation_validator. Add
> self._cached_validations: Dict[str, RecommendationValidation] = {} to
> __init__. In generate(), after `actionable = self._deduplicate(actionable)`
> and before the return statement, build signals_by_id from the signals
> list already in scope, construct a RecommendationValidator, call
> validate_all on actionable[:top_n], and store the result in
> self._cached_validations. Add a new public method get_validation(self,
> recommendation_id: str) -> Optional[RecommendationValidation] that
> looks it up from the cache."

**Prompt 4** — API models:
> "In models_phase3.py, add TradeOffResponse and
> RecommendationValidationResponse Pydantic models exactly as specified,
> placed after RecommendationSummary. Add one new Optional field
> `validation: Optional[RecommendationValidationResponse] = None` to
> RecommendationSummary itself."

**Prompt 5** — wire into routes (supervise closely, this touches the same
function you already modified in the previous roadmap):
> "In routes/recommendations.py, add a new optional parameter `validation:
> Optional[RecommendationValidation] = None` to
> _recommendation_to_summary. Build a RecommendationValidationResponse
> from it if present, exactly as specified, and pass it as the
> `validation=` field in the RecommendationSummary constructor call. Find
> the call site inside get_recommendations where
> _recommendation_to_summary is invoked for each recommendation, and
> after generating recommendations via engine.generate(...), call
> engine.get_validation(rec.recommendation_id) for each one and pass it
> through to the existing call."

**Prompt 6** — frontend:
> "In Dashboard.jsx, inside the recs.map block, after the existing
> resource load bars and dependency chain sections, add a new collapsible
> 'Why this recommendation?' details block exactly as specified, reading
> from rec.validation. Only render if rec.validation exists."

---

## Test checklist for this phase specifically

1. [ ] `RecommendationValidator` instantiates without error against the
   demo workbook (catch attribute errors on `self.project_state.resources`
   vs `self.project_state.team` first — this is the most likely break)
2. [ ] For the BLK-004 / Meena-overload pair of recommendations, confirm
   `why_selected` produces real numbers (e.g. "Meena is overloaded by
   X%"), not empty lists
3. [ ] Confirm `_find_alternatives` actually finds something for at least
   one recommendation — if every recommendation has zero alternatives,
   the comparison logic never fires and `why_better_than_alternatives`
   will always be empty, which defeats the whole point
4. [ ] Confirm `delay_reduction_summary` and `probability_improvement_summary`
   produce sane before→after pairs (not negative numbers, not >100%)
5. [ ] In the UI, expand the "Why this recommendation?" panel on the
   BLK-004 card and the Meena→Ravi reassignment card — these are your two
   strongest demo moments, make sure both read cleanly before anything
   else
6. [ ] Confirm trade-offs aren't always the generic fallback ("No
   significant trade-offs identified") — if every card shows that, the
   `_build_trade_offs` logic isn't actually finding anything and needs a
   second pass

---

## Why this sequencing protects your demo

This phase reads data, it doesn't compute new forecasts or simulations.
That means if something goes wrong in `recommendation_validator.py` close
to the deadline, you can disable just this phase (return `None` for
`validation` everywhere) and the rest of the tool — the part that
actually moves delay numbers and reassigns work — keeps working
untouched. Build this last, and keep it isolated, specifically so a bug
here can never take down the core recommendation engine the night before
finals.