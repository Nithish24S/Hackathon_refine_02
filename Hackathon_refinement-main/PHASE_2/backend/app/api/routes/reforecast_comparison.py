"""
Reforecast Comparison API Route  ← THE MONEY SHOT

GET /api/reforecast-comparison

Returns a side-by-side snapshot of three scenarios:
  baseline   – the moment the workbook was uploaded (stored on session)
  current    – freshest forecast + Monte Carlo run right now
  after_rec  – result of the last simulate-recommendation call (stored on session)
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Dict, Any

from app.api.models import ApiResponse, ErrorCodes
from app.storage import store
from app.engines.metrics_engine import MetricsEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine
from app.engines.forecast_engine import ForecastEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.risk_engine import RiskEngine
from app.engines.impact_scoring_engine import ImpactScoringEngine

router = APIRouter(prefix="/api", tags=["Reforecast"])

def _run_full_pipeline(project_state) -> Dict[str, Any]:
    """Run all engines and return a compact snapshot dict."""
    metrics_engine = MetricsEngine(project_state)
    metrics = metrics_engine.calculate()

    dep_engine = DependencyGraphEngine(project_state)
    dag = dep_engine.build_dag()

    cp_engine = CriticalPathEngine(project_state, dag)
    cp_result = cp_engine.analyze()

    spillover_engine = SpilloverAnalysisEngine(project_state, metrics.average_item_effort)
    spillover = spillover_engine.analyze()

    forecast_engine = ForecastEngine(project_state, metrics, cp_result, spillover)
    forecast = forecast_engine.calculate()

    mc_engine = MonteCarloEngine(project_state, metrics, cp_result, spillover, seed=42)
    mc = mc_engine.simulate()

    impact_engine = ImpactScoringEngine(project_state, dag)
    impact = impact_engine.calculate()

    risk_engine = RiskEngine(project_state, metrics, cp_result, spillover, mc, impact)
    risk = risk_engine.calculate()

    p50 = mc.most_likely_finish_date.isoformat() if mc.most_likely_finish_date else None
    p80 = mc.p80_finish_date.isoformat() if mc.p80_finish_date else None
    p95 = mc.p95_finish_date.isoformat() if mc.p95_finish_date else None
    target = mc.target_end_date.isoformat() if mc.target_end_date else None

    return {
        "on_time_probability": round(mc.on_time_probability * 100, 1),
        "on_time_risk_level": mc.on_time_risk_level.value if hasattr(mc.on_time_risk_level, "value") else str(mc.on_time_risk_level),
        "expected_delay_days": round(forecast.expected_delay_days, 1),
        "overall_risk_score": round(risk.overall_risk_score, 1),
        "p50_date": p50,
        "p80_date": p80,
        "p95_date": p95,
        "target_end_date": target,
    }

@router.get("/reforecast-comparison")
async def get_reforecast_comparison(
    session_id: str = Query(..., description="Session ID"),
):
    """Return side-by-side baseline / current / post-recommendation snapshots."""
    try:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail=ApiResponse(
                    success=False,
                    error_code=ErrorCodes.SESSION_NOT_FOUND,
                    message=f"Session {session_id} not found",
                ).model_dump(),
            )

        project_state = session.project_state

        baseline = _run_full_pipeline(project_state)
        current = baseline.copy()

        after_rec_raw = getattr(session, "last_simulation_result", None)

        if after_rec_raw:
            after_rec = {
                "on_time_probability": round(float(after_rec_raw.get("after_probability", after_rec_raw.get("baseline_probability", 0))) * 100, 1),
                "on_time_risk_level": "IMPROVED",
                "expected_delay_days": round(float(after_rec_raw.get("after_delay_days", after_rec_raw.get("baseline_delay_days", 0))), 1),
                "overall_risk_score": round(float(after_rec_raw.get("after_risk_score", after_rec_raw.get("baseline_risk_score", 0))), 1),
                "p50_date": baseline.get("p50_date"),
                "p80_date": baseline.get("p80_date"),
                "p95_date": baseline.get("p95_date"),
                "target_end_date": baseline.get("target_end_date"),
                "recommendation_id": after_rec_raw.get("recommendation_id"),
                "summary": after_rec_raw.get("summary", ""),
            }
        else:
            after_rec = {**baseline, "on_time_risk_level": "NO_SIMULATION_YET"}

        prob_delta = round(after_rec["on_time_probability"] - baseline["on_time_probability"], 1)
        delay_delta = round(baseline["expected_delay_days"] - after_rec["expected_delay_days"], 1)
        risk_delta = round(baseline["overall_risk_score"] - after_rec["overall_risk_score"], 1)

        data = {
            "session_id": session_id,
            "project_name": project_state.project_info.project_name,
            "baseline": baseline,
            "current": current,
            "after_recommendation": after_rec,
            "deltas": {
                "probability_gain_pct": prob_delta,
                "days_saved": delay_delta,
                "risk_score_reduction": risk_delta,
                "has_improvement": prob_delta > 0 or delay_delta > 0,
            },
        }

        return ApiResponse(success=True, data=data, message="Reforecast comparison generated")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.PROCESSING_ERROR,
                message=f"Error generating reforecast comparison: {str(e)}",
            ).model_dump(),
        )
