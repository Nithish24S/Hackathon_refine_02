"""Recommendation API Routes (Phase 3.4)

Endpoints:
- GET /api/recommendations
- POST /api/recommendations/simulate
- POST /api/recommendations/scenario
"""
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional, Dict, List
from app.storage import store
from app.api.models import ApiResponse, ErrorCodes
from app.engines.dependency_engine import DependencyDAG
from app.engines.metrics_engine import ProjectMetrics
from app.api.models_phase3 import (
    RecommendationResponse,
    RecommendationSimulationRequest,
    RecommendationScenarioRequest,
    RecommendationSimulationResponse,
    RecommendationSimulationResult,
    RecommendationSummary,
    RecommendationType,
    RecommendationValidationResponse,
    TradeOffResponse,
)
from app.domain.models import ProjectState
from app.engines.advisor_input_builder import AdvisorInputBuilder
from app.engines.recommendation_engine.candidate_generator import CandidateGenerator
from app.engines.recommendation_engine.impact_estimator import ImpactEstimator
from app.engines.recommendation_engine.models import RecommendationAction, RecommendationValidation, ScoringWeights
from app.engines.recommendation_engine.recommendation_engine_v2 import RecommendationEngineV2
from app.engines.recommendation_engine.signal_detectors import (
    BlockerDetector,
    CapacityDetector,
    CriticalPathDetector,
    ScheduleDetector,
    SprintDetector,
)

router = APIRouter(prefix="/api", tags=["Phase3.4"])


def _recommendation_type_from_action(action_type: RecommendationAction) -> RecommendationType:
    return {
        RecommendationAction.RESOLVE_BLOCKER: RecommendationType.RESOLVE_BLOCKER,
        RecommendationAction.REASSIGN_ITEM: RecommendationType.REASSIGN_WORK,
        RecommendationAction.SPLIT_ITEM: RecommendationType.SPLIT_TASK,
        RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT: RecommendationType.MOVE_BLOCKER_ITEMS,
        RecommendationAction.PARALLELIZE_ITEMS: RecommendationType.PARALLELIZE_TASKS,
        RecommendationAction.REBALANCE_SPRINT_LOAD: RecommendationType.REASSIGN_WORK,
        RecommendationAction.REMOVE_DEPENDENCY_BOTTLENECK: RecommendationType.CRITICAL_PATH_OPTIMIZATION,
        RecommendationAction.ADD_RESOURCE_SKILL: RecommendationType.ADD_RESOURCE,
    }.get(action_type, RecommendationType.CRITICAL_PATH_OPTIMIZATION)


def _compute_impact_level(estimated_delay_reduction: float) -> str:
    """
    CRITICAL FIX: Classify impact level based on delay reduction magnitude.
    
    Thresholds calibrated from Monte Carlo noise floor (±0.5 days typical).
    """
    if estimated_delay_reduction >= 5.0:      # Significant reduction
        return "High"
    elif estimated_delay_reduction >= 2.0:    # Moderate reduction
        return "Medium"
    else:                                      # Minimal/noise
        return "Low"


def _resolve_category(
    project_state: ProjectState,
    affected_blocker_ids: List[str]
) -> Optional[str]:
    """
    HIGH FIX: Resolve category of first blocker in recommendation.
    
    If multiple blockers, returns the first blocker's category.
    Categories: "Technical Debt", "Team Capacity", "External Dependency", etc.
    """
    if not affected_blocker_ids:
        return None
    
    # Get first blocker
    first_blocker_id = affected_blocker_ids[0]
    for blocker in project_state.blockers:
        if blocker.blocker_id == first_blocker_id:
            return blocker.category.value

def _estimate_implementation_effort(
    action_type: RecommendationAction,
    affected_item_ids: List[str],
    affected_resource_ids: List[str],
    affected_blocker_ids: List[str],
) -> str:
    """
    HIGH FIX: Estimate implementation effort based on scope and action type.
    
    High: Multiple items, resource changes, blocker resolution
    Medium: Single item, reassignment
    Low: Item descope, priority change
    """
    scope_count = (
        len(affected_item_ids) +
        len(affected_resource_ids) +
        len(affected_blocker_ids)
    )
    
    # Blocker resolution is high-effort
    if action_type == RecommendationAction.RESOLVE_BLOCKER and len(affected_blocker_ids) > 0:
        return "High"
    
    # Resource changes are high-effort
    if action_type == RecommendationAction.ADD_RESOURCE_SKILL and len(affected_resource_ids) > 0:
        return "High"
    
    # Multiple items = more effort
    if scope_count > 3:
        return "High"
    elif scope_count > 1:
        return "Medium"
    else:
        return "Low"


def _compute_urgency(rec, project_state: Optional[ProjectState]) -> str:
    if not project_state or not rec.affected_sprint_ids:
        return "THIS_SPRINT"
    current_sprint = next(
        (s for s in project_state.sprints if getattr(s, "status", None) and str(s.status).upper() == "IN_PROGRESS"),
        None,
    )
    current_sprint_id = current_sprint.sprint_id if current_sprint else None
    if hasattr(RecommendationType, 'RESOLVE_BLOCKER') and rec.action_type == RecommendationType.RESOLVE_BLOCKER:
        return "TODAY"
    if current_sprint_id and current_sprint_id in rec.affected_sprint_ids:
        return "THIS_SPRINT"
    return "NEXT_SPRINT"


def _build_action_summary(rec) -> str:
    return rec.title


def _build_resource_load_impact(
    rec,
    project_state: Optional[ProjectState],
    metrics: Optional[ProjectMetrics],
) -> Optional[Dict[str, Dict[str, float]]]:
    if not rec.affected_resource_ids or not metrics:
        return None
    result = {}
    for resource_id in rec.affected_resource_ids:
        dev = next(
            (dm for dm in metrics.resource_metrics.developer_metrics if dm.resource_id == resource_id),
            None,
        )
        if dev:
            result[dev.name] = {
                "before": round(dev.remaining_effort_hours, 1),
                "after": round(dev.remaining_effort_hours, 1),
            }
    return result or None


def _recommendation_to_summary(
    rec,
    baseline_metrics: Optional[Dict[str, float]] = None,
    project_state: Optional[ProjectState] = None,
    metrics: Optional[ProjectMetrics] = None,
    dag: Optional[DependencyDAG] = None,
    validation: Optional[RecommendationValidation] = None,
) -> RecommendationSummary:
    """
    Convert internal Recommendation to API RecommendationSummary.
    
    CRITICAL FIXES:
    - Baseline metrics (probability, delay, risk) routed from upstream
    - After metrics estimated from recommendation impact
    
    HIGH FIXES:
    - implementation_effort computed from scope
    - impact_level computed from estimated impact
    - category resolved from blocker lookup
    - impact_evidence forwarded in details
    """
    if baseline_metrics is None:
        baseline_metrics = {
            "on_time_probability": 0.0,
            "expected_delay_days": 0.0,
            "overall_risk_score": 0.0,
        }
    
    # CRITICAL: Extract real baseline values from upstream
    baseline_prob = baseline_metrics.get("on_time_probability", 0.0)
    baseline_delay = baseline_metrics.get("expected_delay_days", 0.0)
    baseline_risk = baseline_metrics.get("overall_risk_score", 0.0)
    
    # Estimate after-state (simplified: subtract estimated reductions)
    after_prob = min(1.0, max(0.0, baseline_prob + rec.estimated_risk_reduction / 100.0))
    after_delay = max(0.0, baseline_delay - rec.estimated_delay_reduction_days)
    after_risk = max(0.0, baseline_risk - rec.estimated_risk_reduction)
    
    # HIGH: Compute real values instead of hardcoding
    implementation_effort = _estimate_implementation_effort(
        rec.action_type,
        rec.affected_item_ids,
        rec.affected_resource_ids,
        rec.affected_blocker_ids,
    )
    impact_level = _compute_impact_level(rec.estimated_delay_reduction_days)
    category = _resolve_category(project_state, rec.affected_blocker_ids) if project_state else None
    urgency = _compute_urgency(rec, project_state)
    action_summary = _build_action_summary(rec)
    blocker_overdue_days = rec.metadata.get("simulation_params", {}).get("overdue_days") if getattr(rec, "metadata", None) else None
    resource_load_impact = _build_resource_load_impact(rec, project_state, metrics)
    dependency_consequence = None
    if dag and rec.affected_item_ids:
        downstream_ids = set()
        for item_id in rec.affected_item_ids:
            downstream_ids.update(dag.transitive_closure.get(item_id, set()))
        dependency_consequence = ", ".join(sorted(downstream_ids)) if downstream_ids else None
    
    # HIGH: Forward impact_evidence to details
    impact_evidence = []
    if rec.impact_evidence:
        impact_evidence = [
            {
                "source_engine": sig.source_engine,
                "metric_name": sig.metric_name,
                "metric_value": sig.metric_value,
                "threshold": sig.threshold,
                "explanation": sig.explanation,
            }
            for sig in rec.impact_evidence
        ]

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
    
    return RecommendationSummary(
        recommendation_id=rec.recommendation_id,
        type=_recommendation_type_from_action(rec.action_type),
        action=rec.title,
        target_ids=rec.affected_item_ids + rec.affected_resource_ids + rec.affected_sprint_ids + rec.affected_blocker_ids,
        details={
            "affected_item_ids": rec.affected_item_ids,
            "affected_resource_ids": rec.affected_resource_ids,
            "affected_sprint_ids": rec.affected_sprint_ids,
            "affected_blocker_ids": rec.affected_blocker_ids,
            "metadata": rec.metadata,
            "impact_evidence": impact_evidence,  # HIGH FIX: Now included
        },
        reason=rec.description,
        implementation_effort=implementation_effort,  # HIGH FIX: Computed
        confidence=rec.confidence.value,
        priority_score=round(rec.priority_score * 100.0, 2),
        baseline_probability=round(baseline_prob, 4),  # CRITICAL FIX: From upstream
        after_probability=round(after_prob, 4),  # CRITICAL FIX: Estimated
        expected_probability_gain=round(after_prob - baseline_prob, 4),  # CRITICAL FIX
        baseline_delay_days=round(baseline_delay, 2),  # CRITICAL FIX: From upstream
        after_delay_days=round(after_delay, 2),  # CRITICAL FIX: Estimated
        expected_delay_gain_days=round(rec.estimated_delay_reduction_days, 2),
        baseline_risk_score=round(baseline_risk, 2),  # CRITICAL FIX: From upstream
        after_risk_score=round(after_risk, 2),  # CRITICAL FIX: Estimated
        expected_risk_reduction=round(rec.estimated_risk_reduction, 2),
        impact_level=impact_level,  # HIGH FIX: Computed
        impact_confidence=rec.confidence.value,
        impact_classification="Positive Impact" if rec.estimated_delay_reduction_days > 0.0 else "Negligible Impact",
        business_impact=rec.description,
        impact_summary=rec.description,
        category=category,  # HIGH FIX: Resolved
        recommended_actions=[rec.title],
        action_summary=action_summary,
        resource_load_impact=resource_load_impact,
        dependency_consequence=dependency_consequence,
        urgency=urgency,
        blocker_overdue_days=blocker_overdue_days,
        validation=validation_response,
    )


def _build_engine(session_id: str) -> RecommendationEngineV2:
    project_state = store.get_project_state(session_id)
    if not project_state:
        raise HTTPException(
            status_code=404,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.SESSION_NOT_FOUND,
                message=f"Session {session_id} not found",
            ).model_dump(mode='json'),
        )
    return RecommendationEngineV2(project_state=project_state, simulation_count=1000, scoring_weights=ScoringWeights())


_advisor_builder = AdvisorInputBuilder()


def _get_narrative_service(request: Request):
    narrative_service = getattr(request.app.state, "narrative_service", None)
    if narrative_service is None:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INTERNAL_ERROR,
                message="AI advisor service is unavailable",
            ).model_dump(mode='json'),
        )
    return narrative_service


def _fallback_text_by_recommendation(recommendations):
    return {rec.recommendation_id: rec.description for rec in recommendations}


@router.get("/recommendations")
async def get_recommendations(
    request: Request,
    session_id: str = Query(..., description="Session ID"),
    top_n: int = Query(5, description="Number of recommendations to return"),
):
    try:
        session_id = session_id.strip()
        recommendation_engine = _build_engine(session_id)
        candidates = recommendation_engine.generate(top_n=top_n)

        upstream = recommendation_engine._compute_upstream()
        baseline_metrics = {
            "on_time_probability": round(upstream.monte_carlo.on_time_probability, 4),
            "expected_delay_days": round(upstream.forecast.expected_delay_days, 2),
            "overall_risk_score": round(upstream.risk_result.overall_risk_score, 2),
        }

        advisor_input = _advisor_builder.build_recommendation_input(
            project_id=session_id,
            project_state=recommendation_engine.project_state,
            forecast=upstream.forecast,
            monte_carlo=upstream.monte_carlo,
            recommendations=candidates,
            metrics=upstream.metrics,
        )
        advisor_explanation = await _get_narrative_service(request).explain(
            advisor_input,
            _fallback_text_by_recommendation(candidates),
        )

        upstream_metrics = upstream.metrics
        response = RecommendationResponse(
            session_id=session_id,
            project_name=recommendation_engine.project_state.project_info.project_name,
            recommendations=[
                _recommendation_to_summary(
                    rec,
                    baseline_metrics,
                    recommendation_engine.project_state,
                    upstream_metrics,
                    upstream.dag,
                    recommendation_engine.get_validation(rec.recommendation_id),
                )
                for rec in candidates
            ],
            advisor_explanation=advisor_explanation,
        )
        return ApiResponse(success=True, data=response.model_dump(), message="Recommendations generated")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INTERNAL_ERROR,
                message=f"Error generating recommendations: {str(e)}",
            ).model_dump(mode='json'),
        )


@router.post("/recommendations/simulate")
async def simulate_recommendation(
    request: Request,
    session_id: str = Query(..., description="Session ID"),
    request_body: RecommendationSimulationRequest = ..., 
):
    try:
        recommendation_engine = _build_engine(session_id)
        simulation_result = recommendation_engine.simulate(request_body.recommendation_id)
        upstream = recommendation_engine._compute_upstream()
        recommendation = next(
            (rec for rec in recommendation_engine._cached_recommendations if rec.recommendation_id == request_body.recommendation_id),
            None,
        )
        if recommendation is None:
            raise KeyError(f"Recommendation {request_body.recommendation_id} not found")

        advisor_input = _advisor_builder.build_simulation_input(
            project_id=session_id,
            recommendation=recommendation,
            simulation_result=simulation_result,
            risk=upstream.risk_result,
            project_state=recommendation_engine.project_state,
            forecast=upstream.forecast,
            monte_carlo=upstream.monte_carlo,
            metrics=upstream.metrics,
        )
        advisor_explanation = await _get_narrative_service(request).explain(
            advisor_input,
            _fallback_text_by_recommendation([recommendation]),
        )

        # Cache simulation result on session for /api/reforecast-comparison
        _session = store.get_session(session_id)
        if _session:
            _session.last_simulation_result = {
                "recommendation_id": simulation_result.recommendation_ids[0] if simulation_result.recommendation_ids else None,
                "baseline_probability": simulation_result.baseline_metrics.on_time_probability,
                "after_probability": simulation_result.simulated_metrics.on_time_probability,
                "baseline_delay_days": simulation_result.baseline_metrics.expected_delay_days,
                "after_delay_days": simulation_result.simulated_metrics.expected_delay_days,
                "baseline_risk_score": simulation_result.baseline_metrics.overall_risk_score,
                "after_risk_score": simulation_result.simulated_metrics.overall_risk_score,
                "probability_gain": simulation_result.delta_on_time_probability,
                "delay_reduction_days": simulation_result.delta_expected_delay_days,
                "summary": simulation_result.summary,
            }

        response = RecommendationSimulationResponse(
            session_id=session_id,
            project_name=recommendation_engine.project_state.project_info.project_name,
            simulation_result=RecommendationSimulationResult(
                session_id=session_id,
                project_name=recommendation_engine.project_state.project_info.project_name,
                recommendation_id=simulation_result.recommendation_ids[0] if simulation_result.recommendation_ids else None,
                baseline_probability=simulation_result.baseline_metrics.on_time_probability,
                after_probability=simulation_result.simulated_metrics.on_time_probability,
                probability_gain=simulation_result.delta_on_time_probability,
                baseline_delay_days=simulation_result.baseline_metrics.expected_delay_days,
                after_delay_days=simulation_result.simulated_metrics.expected_delay_days,
                delay_reduction_days=simulation_result.delta_expected_delay_days,
                baseline_risk_score=simulation_result.baseline_metrics.overall_risk_score,
                after_risk_score=simulation_result.simulated_metrics.overall_risk_score,
                risk_reduction=simulation_result.delta_risk_score,
                baseline_schedule_risk=simulation_result.baseline_metrics.schedule_risk,
                after_schedule_risk=simulation_result.simulated_metrics.schedule_risk,
                baseline_resource_risk=simulation_result.baseline_metrics.resource_risk,
                after_resource_risk=simulation_result.simulated_metrics.resource_risk,
                delta_spillover_risk=simulation_result.delta_spillover_risk,
                delta_projected_velocity=simulation_result.delta_projected_velocity,
                seed_used=simulation_result.seed_used,
                is_positive_impact=simulation_result.is_positive_impact,
                summary=simulation_result.summary,
                scenario_recommendation_ids=simulation_result.recommendation_ids,
            ),
            advisor_explanation=advisor_explanation,
        )
        return ApiResponse(success=True, data=response.model_dump(), message="Simulation completed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INTERNAL_ERROR,
                message=f"Error simulating recommendation: {str(e)}",
            ).model_dump(mode='json'),
        )


@router.post("/recommendations/scenario")
async def simulate_scenario(
    request: Request,
    session_id: str = Query(..., description="Session ID"),
    request_body: RecommendationScenarioRequest = ..., 
):
    try:
        recommendation_engine = _build_engine(session_id)
        scenario = recommendation_engine.simulate_scenario(request_body.recommendation_ids)
        recommendations = [
            rec
            for rec in recommendation_engine._cached_recommendations
            if rec.recommendation_id in set(request_body.recommendation_ids)
        ]

        advisor_input = _advisor_builder.build_scenario_input(
            project_id=session_id,
            project_state=recommendation_engine.project_state,
            forecast=recommendation_engine._compute_upstream().forecast,
            monte_carlo=recommendation_engine._compute_upstream().monte_carlo,
            recommendations=recommendations,
            simulation_result=scenario,
            risk=recommendation_engine._compute_upstream().risk_result,
            metrics=recommendation_engine._compute_upstream().metrics,
        )
        advisor_explanation = await _get_narrative_service(request).explain(
            advisor_input,
            _fallback_text_by_recommendation(recommendations),
        )

        response = RecommendationSimulationResponse(
            session_id=session_id,
            project_name=recommendation_engine.project_state.project_info.project_name,
            simulation_result=RecommendationSimulationResult(
                session_id=session_id,
                project_name=recommendation_engine.project_state.project_info.project_name,
                recommendation_id=None,
                baseline_probability=scenario.baseline_metrics.on_time_probability,
                after_probability=scenario.simulated_metrics.on_time_probability,
                probability_gain=scenario.delta_on_time_probability,
                baseline_delay_days=scenario.baseline_metrics.expected_delay_days,
                after_delay_days=scenario.simulated_metrics.expected_delay_days,
                delay_reduction_days=scenario.delta_expected_delay_days,
                baseline_risk_score=scenario.baseline_metrics.overall_risk_score,
                after_risk_score=scenario.simulated_metrics.overall_risk_score,
                risk_reduction=scenario.delta_risk_score,
                baseline_schedule_risk=scenario.baseline_metrics.schedule_risk,
                after_schedule_risk=scenario.simulated_metrics.schedule_risk,
                baseline_resource_risk=scenario.baseline_metrics.resource_risk,
                after_resource_risk=scenario.simulated_metrics.resource_risk,
                delta_spillover_risk=scenario.delta_spillover_risk,
                delta_projected_velocity=scenario.delta_projected_velocity,
                seed_used=scenario.seed_used,
                is_positive_impact=scenario.is_positive_impact,
                summary=scenario.summary,
                scenario_recommendation_ids=request_body.recommendation_ids,
            ),
            advisor_explanation=advisor_explanation,
        )
        return ApiResponse(success=True, data=response.model_dump(), message="Scenario simulation completed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INTERNAL_ERROR,
                message=f"Error simulating recommendation scenario: {str(e)}",
            ).model_dump(mode='json'),
        )


@router.get("/recommendations/explain/{recommendation_id}")
async def explain_recommendation(
    recommendation_id: str,
    session_id: str = Query(..., description="Session ID"),
):
    try:
        session_id = session_id.strip()
        recommendation_engine = _build_engine(session_id)
        if not recommendation_engine._cached_recommendations:
            recommendation_engine.generate(top_n=100)

        recommendation = next(
            (rec for rec in recommendation_engine._cached_recommendations if rec.recommendation_id == recommendation_id),
            None,
        )
        if recommendation is None:
            raise KeyError(f"Recommendation {recommendation_id} not found")

        upstream = recommendation_engine._compute_upstream()
        signals = []
        signals.extend(BlockerDetector(recommendation_engine.project_state, upstream.cp_result, upstream.dag, upstream.impact_scores).detect())
        signals.extend(CapacityDetector(recommendation_engine.project_state, upstream.metrics, upstream.cp_result, upstream.impact_scores).detect())
        signals.extend(SprintDetector(recommendation_engine.project_state, upstream.metrics, upstream.spillover, upstream.forecast).detect())
        signals.extend(CriticalPathDetector(recommendation_engine.project_state, upstream.cp_result, upstream.dag, upstream.impact_scores).detect())
        signals.extend(ScheduleDetector(recommendation_engine.project_state, upstream.forecast, upstream.monte_carlo, upstream.risk_result, upstream.metrics).detect())

        candidates = CandidateGenerator(recommendation_engine.project_state, upstream).generate(signals)
        candidate = next((c for c in candidates if c.recommendation_id == recommendation_id), None)
        if candidate is None:
            raise KeyError(f"Recommendation candidate {recommendation_id} not found")

        impact = ImpactEstimator(recommendation_engine.project_state, upstream).estimate(candidate)
        trigger_signal = next((s for s in signals if s.signal_id == candidate.root_cause_signal_id), None)
        trigger_signal_payload = None
        if trigger_signal is not None:
            trigger_signal_payload = {
                "signal_id": trigger_signal.signal_id,
                "category": trigger_signal.category.value,
                "severity": trigger_signal.severity.value,
                "affected_item_ids": trigger_signal.affected_item_ids,
                "affected_resource_ids": trigger_signal.affected_resource_ids,
                "affected_sprint_ids": trigger_signal.affected_sprint_ids,
                "affected_blocker_ids": trigger_signal.affected_blocker_ids,
                "context": trigger_signal.context,
                "detected_at": trigger_signal.detected_at,
            }

        payload = {
            "recommendation_id": recommendation_id,
            "trigger_signal": trigger_signal_payload,
            "simulation_params": candidate.simulation_params,
            "calculation_notes": impact.calculation_notes,
        }

        return ApiResponse(success=True, data=payload, message="Recommendation explanation generated")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INTERNAL_ERROR,
                message=f"Error explaining recommendation: {str(e)}",
            ).model_dump(mode='json'),
        )
