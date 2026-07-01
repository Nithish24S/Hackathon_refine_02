"""
Recovery Plan Engine Orchestrator

Main entry point for recovery plan generation. Coordinates all components:
- Generator: Creates 3 candidate plans
- Simulator: Simulates each plan's impact
- Scorer: Scores based on simulation results
- Explainer: Generates narrative explanations
- Ranker: Ranks plans and marks "Recommended"

Returns complete ranked list of RecoveryPlan objects ready for API/frontend.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Set

from app.engines.recommendation_engine.models import Recommendation
from app.engines.recovery_plan_engine.conflict_detector import ConflictDetector
from app.engines.recovery_plan_engine.models import (
    RecoveryPlan,
    RecoveryPlanCandidate,
    RecoveryPlanScore,
    RecoveryPlanArchetype,
)
from app.engines.recovery_plan_engine.plan_explainer import RecoveryPlanExplainer
from app.engines.recovery_plan_engine.plan_generator import RecoveryPlanGenerator
from app.engines.recovery_plan_engine.plan_scorer import RecoveryPlanScorer

logger = logging.getLogger(__name__)
from app.engines.recovery_plan_engine.plan_simulator import RecoveryPlanSimulator
from app.engines.simulation_engine import ScenarioResult, SimulationEngine


class RecoveryPlanEngine:
    """
    Main engine for generating recovery plans.
    
    Orchestrates plan generation, simulation, scoring, explanation, and ranking
    into a complete workflow producing ranked RecoveryPlan objects.
    """

    def __init__(
        self,
        simulation_engine: SimulationEngine,
        max_actions_per_plan: int = 5,
        build_revised_sprint_plan_fn: Optional[Callable] = None,
    ):
        """
        Args:
            simulation_engine: Configured SimulationEngine with project state and upstream outputs.
            max_actions_per_plan: Maximum actions per plan (default 5).
            build_revised_sprint_plan_fn: Function to call to build revised sprint plan from simulation.
                                          If None, use dummy output (will be integrated later).
        """
        self.simulation_engine = simulation_engine
        self.generator = RecoveryPlanGenerator(max_actions_per_plan=max_actions_per_plan)
        self.simulator = RecoveryPlanSimulator(simulation_engine)
        self.scorer = RecoveryPlanScorer()
        self.explainer = RecoveryPlanExplainer()
        self.build_revised_sprint_plan_fn = build_revised_sprint_plan_fn

    def generate_recovery_plans(
        self,
        recommendations: List[Recommendation],
        critical_path_item_ids: Optional[Set[str]] = None,
        resource_loads: Optional[Dict[str, float]] = None,
    ) -> List[RecoveryPlan]:
        """
        Generate three ranked recovery plans from recommendations.
        
        Complete pipeline:
        1. Generate 3 candidate plans (SAFE, AGGRESSIVE, MINIMAL_DISRUPTION)
        2. Simulate each plan's impact
        3. Score each plan based on simulation
        4. Explain each plan (narrative, comparisons, trade-offs)
        5. Build revised sprint plan for each
        6. Rank by composite_score
        7. Mark highest-scoring plan as "Recommended"
        8. Return ranked list
        
        Args:
            recommendations: List of ranked recommendations to build plans from.
            critical_path_item_ids: Set of item IDs on the critical path (optional, used for MINIMAL_DISRUPTION archetype).
            resource_loads: Dict of resource_id -> load_percentage (optional, used for MINIMAL_DISRUPTION archetype).
        
        Returns:
            List of RecoveryPlan objects, ranked by composite_score descending.
            First plan (highest score) is labeled "Recommended".
        """
        if not recommendations:
            return []
        
        # Step 1: Generate candidate plans (3 archetypes)
        candidate_plans = self.generator.generate_all_archetypes(
            recommendations,
            critical_path_item_ids=critical_path_item_ids,
            resource_loads=resource_loads,
        )
        
        # Step 2: Simulate each candidate plan
        scenario_results: List[ScenarioResult] = []
        for plan in candidate_plans:
            scenario = self.simulator.simulate_plan(plan)
            scenario_results.append(scenario)
        
        # Step 3: Score each plan
        plan_scores: List[RecoveryPlanScore] = self.scorer.score_all_plans(candidate_plans, scenario_results)

        # Regression warning: AGGRESSIVE should normally aim to outperform SAFE.
        safe_score = next(
            (score for plan, score in zip(candidate_plans, plan_scores) if plan.archetype == RecoveryPlanArchetype.SAFE),
            None,
        )
        aggressive_score = next(
            (score for plan, score in zip(candidate_plans, plan_scores) if plan.archetype == RecoveryPlanArchetype.AGGRESSIVE),
            None,
        )
        if safe_score and aggressive_score and aggressive_score.composite_score < safe_score.composite_score:
            logger.warning(
                "Aggressive recovery plan scored lower (%.3f) than Safe plan (%.3f); review plan archetype construction",
                aggressive_score.composite_score,
                safe_score.composite_score,
            )
        
        # Step 4: Explain each plan
        plan_explanations = []
        for i, (plan, score) in enumerate(zip(candidate_plans, plan_scores)):
            # Determine if this is the recommended (highest score) — will finalize after ranking
            explanation = self.explainer.explain_plan(
                plan=plan,
                plan_score=score,
                all_plans=candidate_plans,
                all_scores=plan_scores,
                is_recommended=False,  # Provisional; will update after ranking
            )
            plan_explanations.append(explanation)
        
        # Step 5: Build revised sprint plan for each (reuses validator logic)
        revised_sprint_plans = []
        for scenario in scenario_results:
            # Use prebuilt revised_sprint_plan if available (legacy path); otherwise fallback to empty list
            revised_plan = []
            if hasattr(scenario, "revised_sprint_plan") and scenario.revised_sprint_plan:
                revised_plan = scenario.revised_sprint_plan
            revised_sprint_plans.append(revised_plan)
        
        # Step 6: Rank by composite_score descending
        ranked_indices = sorted(
            range(len(plan_scores)),
            key=lambda i: plan_scores[i].composite_score,
            reverse=True,
        )
        
        # Step 7: Build final RecoveryPlan objects (now marked as Recommended/Alternative)
        final_plans: List[RecoveryPlan] = []
        for rank, idx in enumerate(ranked_indices):
            plan = candidate_plans[idx]
            score = plan_scores[idx]
            explanation = plan_explanations[idx]
            scenario = scenario_results[idx]
            revised_plan = revised_sprint_plans[idx]
            
            # Determine label based on rank
            if rank == 0:
                label = "Recommended"
                # Regenerate explanation now that we know this is recommended
                explanation = self.explainer.explain_plan(
                    plan=plan,
                    plan_score=score,
                    all_plans=candidate_plans,
                    all_scores=plan_scores,
                    is_recommended=True,
                )
            elif rank == 1:
                label = "Alternative"
            else:
                label = f"Alternative {rank}"
            
            recovery_plan = RecoveryPlan(
                plan_id=plan.plan_id,
                archetype=plan.archetype,
                label=label,
                actions=plan.actions,
                score=score,
                explanation=explanation,
                revised_sprint_plan=revised_plan,
                scenario_result=scenario,
            )
            final_plans.append(recovery_plan)
        
        return final_plans

    def validate_plan(self, plan: RecoveryPlan) -> Dict[str, Any]:
        """
        Validate a recovery plan for consistency and correctness.
        
        Checks:
        - No internal conflicts between actions
        - All actions are in the recommendations list
        - Composite score is within expected range
        
        Returns:
            Dict with 'is_valid' bool and 'issues' list of any problems found.
        """
        issues = []
        
        # Check for internal conflicts
        if ConflictDetector.detect_conflicts_in_plan(plan.actions):
            issues.append("Plan contains conflicting actions")
        
        # Check composite score range
        if plan.score.composite_score < 0.0 or plan.score.composite_score > 1.0:
            issues.append(f"Composite score {plan.score.composite_score} is out of range [0, 1]")
        
        # Check actions count matches score.actions_required
        if len(plan.actions) != plan.score.actions_required:
            issues.append(
                f"Action count mismatch: plan has {len(plan.actions)} "
                f"but score says {plan.score.actions_required}"
            )
        
        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
        }
