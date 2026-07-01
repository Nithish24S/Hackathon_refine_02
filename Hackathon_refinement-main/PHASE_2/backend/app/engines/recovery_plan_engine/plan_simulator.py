"""
Recovery Plan Simulator

Thin wrapper around SimulationEngine.simulate_scenario() for evaluating entire plans.

No new simulation logic is required — SimulationEngine already:
- Clones the project state
- Applies multiple recommendations in sequence
- Recalculates the engine pipeline
- Returns a complete ScenarioResult

This layer just adapts the interface to work with RecoveryPlanCandidate objects.
"""

from app.engines.recovery_plan_engine.models import RecoveryPlanCandidate
from app.engines.simulation_engine import ScenarioResult, SimulationEngine


class RecoveryPlanSimulator:
    """
    Simulates a complete recovery plan by applying all its actions together
    and capturing the resulting scenario outcome.
    """

    def __init__(self, simulation_engine: SimulationEngine):
        """
        Args:
            simulation_engine: The existing SimulationEngine configured with project state and upstream outputs.
        """
        self.simulation_engine = simulation_engine

    def simulate_plan(self, plan: RecoveryPlanCandidate) -> ScenarioResult:
        """
        Simulate a recovery plan.
        
        Internally, this:
        1. Passes all plan actions to SimulationEngine.simulate_scenario()
        2. SimulationEngine clones the project, applies all actions in order, and recalculates
        3. Returns the complete ScenarioResult with before/after metrics
        
        Args:
            plan: RecoveryPlanCandidate with list of actions to apply.
        
        Returns:
            ScenarioResult with detailed simulation output (probability, delay, risk, etc.)
        """
        # This is literally a 1-line delegation to the existing simulate_scenario method
        # which already supports multiple recommendations
        return self.simulation_engine.simulate_scenario(plan.actions)
