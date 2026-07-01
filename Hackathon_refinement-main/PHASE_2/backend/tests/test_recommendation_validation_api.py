from app.api.models_phase3 import RecommendationSummary
from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    Recommendation,
    RecommendationAction,
    RecommendationValidation,
    TradeOff,
)
from app.api.routes.recommendations import _recommendation_to_summary


def test_recommendation_to_summary_includes_validation_payload() -> None:
    recommendation = Recommendation(
        recommendation_id="rec-001",
        title="Reassign WI-001 to Ravi",
        description="Reassign the item to a less loaded resource.",
        action_type=RecommendationAction.REASSIGN_ITEM,
        priority_score=0.91,
        confidence=ConfidenceLevel.HIGH,
        estimated_hours_recovered=12.0,
        estimated_delay_reduction_days=3.0,
        estimated_risk_reduction=0.23,
        affected_item_ids=["WI-001"],
        affected_resource_ids=["R1"],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="sig-1",
        metadata={},
    )

    validation = RecommendationValidation(
        recommendation_id="rec-001",
        why_selected=["Meena is overloaded by 38%"],
        why_better_than_alternatives=["Recovers 2.3 more days"],
        rejected_alternatives=["Alternative A"],
        delay_reduction_summary="8.4d → 5.4d",
        probability_improvement_summary="68% → 91%",
        confidence_label=ConfidenceLevel.HIGH,
        confidence_reasoning="Based on direct staffing data.",
        trade_offs=[TradeOff(description="Uses extra context switching", severity="minor")],
        one_line_pitch="Reassign the item to Ravi — recovers 3.0 days.",
    )

    summary = _recommendation_to_summary(recommendation, validation=validation)

    assert isinstance(summary, RecommendationSummary)
    assert summary.validation is not None
    assert summary.validation.why_selected == ["Meena is overloaded by 38%"]
    assert summary.validation.confidence_label == "HIGH"
