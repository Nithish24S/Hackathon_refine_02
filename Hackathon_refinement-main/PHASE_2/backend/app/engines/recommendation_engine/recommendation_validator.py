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
    Runs after PriorityEngine. Produces a RecommendationValidation per recommendation
    by grounding the explanation in the available signal context and comparison data.
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
        self._items = {wi.item_id: wi for wi in getattr(project_state, "work_items", [])}
        self._resources = self._build_resource_lookup(project_state)

    def validate_all(self, ranked: List[Recommendation]) -> Dict[str, RecommendationValidation]:
        result: Dict[str, RecommendationValidation] = {}
        for rec in ranked:
            alternatives = self._find_alternatives(rec, ranked)
            result[rec.recommendation_id] = self._validate_one(rec, alternatives)
        return result

    def _find_alternatives(self, rec: Recommendation, ranked: List[Recommendation]) -> List[Recommendation]:
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

        delay_before = round(getattr(self.upstream.forecast, "expected_delay_days", 0.0), 1)
        delay_after = round(max(0.0, delay_before - rec.estimated_delay_reduction_days), 1)
        delay_summary = f"{delay_before}d → {delay_after}d"

        prob_before = round(getattr(self.upstream.monte_carlo, "on_time_probability", 0.0) * 100, 0)
        prob_gain_pct = round(rec.estimated_risk_reduction * 100, 0)
        prob_after = min(100, int(prob_before) + int(prob_gain_pct))
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
        if load_ratio is not None:
            overload_pct = round((load_ratio - 1.0) * 100)
            source_name = self._resource_name((rec.affected_resource_ids or [None])[0])
            if overload_pct > 0:
                bullets.append(f"{source_name} is overloaded by {overload_pct}%")
            else:
                bullets.append(f"{source_name} has a load imbalance ({round(load_ratio * 100)}% of capacity)")

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
        blocker = next((b for b in getattr(self.project_state, "blockers", []) if getattr(b, "blocker_id", None) == blocker_id), None)
        if blocker:
            severity = blocker.severity.value if hasattr(blocker.severity, "value") else str(blocker.severity)
            bullets.append(f"{severity} severity blocker, blocking {len(getattr(blocker, 'impacted_item_ids', []) or [])} item(s)")
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
            downstream_count = sum(1 for dep in getattr(self.project_state, "dependencies", []) if getattr(dep, "predecessor_item_id", None) == item_id)
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
        if not alternatives:
            return [], []

        why_better = []
        rejected = []
        for alt in alternatives:
            if alt.priority_score < rec.priority_score:
                reason = self._compare_one(rec, alt)
                if reason:
                    why_better.append(reason)
                rejected.append(f"{alt.title} (priority {round(alt.priority_score * 100)} vs {round(rec.priority_score * 100)})")

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
                trade_offs.append(
                    TradeOff(
                        description=f"Receiving resource already has {round(receiver_other_load)}h of other committed work this sprint",
                        severity="minor" if receiver_other_load < 20 else "moderate",
                    )
                )
        if rec.action_type == RecommendationAction.RESOLVE_BLOCKER:
            trade_offs.append(
                TradeOff(
                    description="Requires external stakeholder action (escalation), not fully within team control",
                    severity="moderate",
                )
            )
        if not trade_offs:
            trade_offs.append(TradeOff(description="No significant trade-offs identified", severity="minor"))
        return trade_offs

    def _build_one_line_pitch(self, rec: Recommendation, delay_before: float, delay_after: float) -> str:
        return f"{rec.title} — recovers {round(delay_before - delay_after, 1)} days, {rec.confidence.value.lower()} confidence."

    def _build_resource_lookup(self, project_state: ProjectState) -> Dict[str, object]:
        resources = getattr(project_state, "resources", None)
        if resources is not None:
            return {getattr(r, "resource_id", None): r for r in resources if getattr(r, "resource_id", None)}
        team = getattr(project_state, "team", None)
        if team is not None:
            return {getattr(r, "resource_id", None): r for r in team if getattr(r, "resource_id", None)}
        return {}

    def _resource_name(self, resource_id: str) -> str:
        r = self._resources.get(resource_id)
        return getattr(r, "name", None) or (resource_id or "Unknown")

    def _free_hours(self, resource_id: str) -> float | None:
        dev = next(
            (
                dm
                for dm in getattr(getattr(self.upstream, "metrics", None), "resource_metrics", None).developer_metrics
                if getattr(dm, "resource_id", None) == resource_id
            ),
            None,
        )
        if dev is None:
            return None
        resource = self._resources.get(resource_id)
        if not resource:
            return None
        capacity = (getattr(resource, "daily_capacity_hrs", 0.0) or 0.0) * (getattr(self.project_state.project_info, "sprint_duration_days", 10) or 10)
        return max(0.0, capacity - getattr(dev, "remaining_effort_hours", 0.0))

    def _has_dependency_conflict(self, item_ids: List[str]) -> str | None:
        for item_id in item_ids:
            for dep in getattr(self.project_state, "dependencies", []) or []:
                if getattr(dep, "successor_item_id", None) == item_id:
                    pred = self._items.get(getattr(dep, "predecessor_item_id", None))
                    if pred and getattr(pred, "status", None) not in ("Completed", "Done"):
                        return getattr(dep, "predecessor_item_id", None)
        return None

    def _other_committed_hours(self, resource_id: str, exclude_item_ids: List[str]) -> float:
        return sum(
            float(getattr(wi, "remaining_effort_hrs", 0.0) or 0.0)
            for wi in getattr(self.project_state, "work_items", [])
            if getattr(wi, "assigned_resource", None) == resource_id and getattr(wi, "item_id", None) not in exclude_item_ids
        )
