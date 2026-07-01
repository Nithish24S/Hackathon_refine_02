"""
Recovery Plan Scorer

Scores recovery plans based on simulated outcomes.

Scoring happens AFTER simulation, not before. A plan's composite score
is NOT the sum of individual recommendation scores (which would double-count
overlapping effects and miss interaction effects). Instead, we run the
actual simulation and read the real resulting state.

Composite score formula (deterministic, no ML):
    0.45 * deadline_probability
    + 0.30 * (1 - normalized_expected_delay_days)
    + 0.15 * (1 - normalized_risk_score)
    - 0.10 * normalized_execution_complexity

The complexity penalty is critical: it stops the system from always
recommending the most aggressive plan. A 7-action plan needs to lose
points relative to a 3-action plan with similar probability, because
the 3-action plan is more likely to actually get executed correctly.
"""

from typing import Any, List, Union

from app.engines.recovery_plan_engine.models import RecoveryPlanCandidate, RecoveryPlanScore
from app.engines.simulation_engine import ScenarioResult, SimulationResultV2


class RecoveryPlanScorer:
    """
    Scores recovery plans based on simulated outcomes.
    
    Normalizes all metrics to 0-1 range before combining them into
    a weighted composite score.
    """

    # Normalization constants (tuned based on typical project scenarios)
    MAX_EXPECTED_DELAY_DAYS = 30.0  # Projects typically won't be delayed by more than 30 days
    MAX_RISK_SCORE = 100.0  # RiskEngine outputs a 0-100 scale
    MAX_EXECUTION_COMPLEXITY = 3.0  # "High" complexity is ~5+ actions

    # Composite score weights (must sum to 1.0)
    WEIGHT_DEADLINE_PROBABILITY = 0.45  # Most important: getting the deadline
    WEIGHT_DELAY_REDUCTION = 0.30  # Second most important: how much time saved
    WEIGHT_RISK_REDUCTION = 0.15  # Third: overall risk reduction
    WEIGHT_COMPLEXITY_PENALTY = -0.10  # Penalty: prefer simpler plans

    def score_plan(self, plan: RecoveryPlanCandidate, scenario_result: Union[ScenarioResult, SimulationResultV2]) -> RecoveryPlanScore:
        """
        Score a recovery plan based on its simulation result.
        
        Args:
            plan: RecoveryPlanCandidate to score.
            scenario_result: ScenarioResult or SimulationResultV2 from simulating the plan.
        
        Returns:
            RecoveryPlanScore with all metrics and composite score.
        """
        # Extract metrics from scenario result depending on version
        if hasattr(scenario_result, "simulated_metrics"):
            deadline_probability = scenario_result.simulated_metrics.on_time_probability
            expected_delay_days = scenario_result.simulated_metrics.expected_delay_days
            risk_score = scenario_result.simulated_metrics.overall_risk_score
        else:
            deadline_probability = scenario_result.monte_carlo_comparison.simulated_on_time_probability
            expected_delay_days = scenario_result.forecast_comparison.simulated_delay_days
            risk_score = scenario_result.risk_comparison.simulated_risk_score
        
        # Derive execution complexity from number of actions and action types
        complexity_str = self._derive_complexity(plan.actions)
        complexity_score = self._complexity_to_score(complexity_str)
        
        # Normalize metrics to 0-1 range
        normalized_delay = min(expected_delay_days / self.MAX_EXPECTED_DELAY_DAYS, 1.0)
        normalized_risk = min(risk_score / self.MAX_RISK_SCORE, 1.0)
        normalized_complexity = min(complexity_score / self.MAX_EXECUTION_COMPLEXITY, 1.0)
        
        # Compute composite score
        composite_score = (
            self.WEIGHT_DEADLINE_PROBABILITY * deadline_probability
            + self.WEIGHT_DELAY_REDUCTION * (1.0 - normalized_delay)
            + self.WEIGHT_RISK_REDUCTION * (1.0 - normalized_risk)
            + self.WEIGHT_COMPLEXITY_PENALTY * normalized_complexity
        )
        
        # Clamp to 0-1 range
        composite_score = max(0.0, min(1.0, composite_score))
        
        return RecoveryPlanScore(
            deadline_probability=deadline_probability,
            expected_delay_days=expected_delay_days,
            overall_risk_score=risk_score,
            actions_required=len(plan.actions),
            execution_complexity=complexity_str,
            composite_score=composite_score,
        )

    def score_all_plans(
        self,
        plans: List[RecoveryPlanCandidate],
        scenario_results: List[ScenarioResult],
    ) -> List[RecoveryPlanScore]:
        """
        Score multiple plans.
        
        Args:
            plans: List of RecoveryPlanCandidate objects.
            scenario_results: Corresponding list of ScenarioResult objects (same order).
        
        Returns:
            List of RecoveryPlanScore objects (same order).
        """
        if len(plans) != len(scenario_results):
            raise ValueError("Number of plans must match number of scenario results")
        
        return [self.score_plan(plan, result) for plan, result in zip(plans, scenario_results)]

    @staticmethod
    def _derive_complexity(actions: list) -> str:
        """
        Derive execution complexity from action count and types.

        The SAFE archetype can legitimately include up to 5 actions when they
        are mostly low-disruption reassignments or rebalances, so the classifier
        should look at both count and the presence of externally coordinated work.
        """
        num_actions = len(actions)
        external_count = sum(
            1
            for action in actions
            if action.action_type.value in [
                "resolve_blocker",
                "remove_dependency_bottleneck",
                "add_resource_skill",
            ]
        )

        if num_actions <= 2 and external_count == 0:
            return "Low"
        elif num_actions <= 5 and external_count <= 1:
            return "Medium"
        else:
            return "High"

    @staticmethod
    def _complexity_to_score(complexity: str) -> float:
        """Convert complexity string to numeric score for normalization."""
        complexity_map = {
            "Low": 1.0,
            "Medium": 2.0,
            "High": 3.0,
        }
        return complexity_map.get(complexity, 2.0)  # Default to Medium if unknown
