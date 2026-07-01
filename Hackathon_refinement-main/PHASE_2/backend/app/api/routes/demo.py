"""
Demo API routes — patched version with engine pre-warming.

POST /api/demo/load  - load the validated workbook into session storage
                       AND immediately run all engines so the dashboard
                       loads with data already populated (no 8-second wait).
POST /api/demo/reset - clear demo sessions
"""

from fastapi import APIRouter, HTTPException

from app.api.models import ApiResponse, ErrorCodes, ProjectSummary, UploadResponse, ValidationIssue
from app.core.config import settings
from app.domain.models import SprintStatus
from app.parsers import WorkbookParseError, WorkbookParser
from app.storage import store
from app.validators import ValidationError as ValidatorError, WorkbookValidator

from app.engines.metrics_engine import MetricsEngine
from app.engines.dependency_engine import DependencyGraphEngine
from app.engines.critical_path_engine import CriticalPathEngine
from app.engines.spillover_engine import SpilloverAnalysisEngine
from app.engines.forecast_engine import ForecastEngine
from app.engines.monte_carlo_engine import MonteCarloEngine
from app.engines.impact_scoring_engine import ImpactScoringEngine
from app.engines.risk_engine import RiskEngine

router = APIRouter(prefix="/api/demo", tags=["Demo"])

def _prewarm_session(session_id: str) -> None:
    """Run all engines immediately so the dashboard loads with data pre-populated."""
    try:
        project_state = store.get_project_state(session_id)
        if not project_state:
            return

        metrics = MetricsEngine(project_state).calculate()
        dag = DependencyGraphEngine(project_state).build_dag()
        cp_result = CriticalPathEngine(project_state, dag).analyze()
        spillover = SpilloverAnalysisEngine(project_state, metrics.average_item_effort).analyze()
        forecast = ForecastEngine(project_state, metrics, cp_result, spillover).calculate()
        mc = MonteCarloEngine(project_state, metrics, cp_result, spillover, seed=42).simulate()
        impact = ImpactScoringEngine(project_state, dag).calculate()
        risk = RiskEngine(project_state, metrics, cp_result, spillover, mc, impact).calculate()

        session = store.get_session(session_id)
        if session:
            session.baseline_snapshot = {
                "on_time_probability": round(mc.on_time_probability * 100, 1),
                "expected_delay_days": round(forecast.expected_delay_days, 1),
                "overall_risk_score": round(risk.overall_risk_score, 1),
                "p50_date": mc.most_likely_finish_date.isoformat() if mc.most_likely_finish_date else None,
                "p80_date": mc.p80_finish_date.isoformat() if mc.p80_finish_date else None,
                "p95_date": mc.p95_finish_date.isoformat() if mc.p95_finish_date else None,
                "target_end_date": mc.target_end_date.isoformat() if mc.target_end_date else None,
                "on_time_risk_level": mc.on_time_risk_level.value if hasattr(mc.on_time_risk_level, "value") else str(mc.on_time_risk_level),
            }
    except Exception:
        pass  # Never crash demo load due to pre-warm failure

@router.post("/load")
async def load_demo_workbook():
    """Load the validated demo workbook into session storage."""
    try:
        parser = WorkbookParser(settings.demo_workbook_path)
        project_state = parser.parse()
        validator = WorkbookValidator(project_state)
        warnings = validator.validate()
    except WorkbookParseError as e:
        raise HTTPException(
            status_code=400,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.PARSE_ERROR,
                message=f"Failed to load demo workbook: {str(e)}",
            ).model_dump(),
        )
    except ValidatorError as e:
        raise HTTPException(
            status_code=400,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.VALIDATION_ERROR,
                message=f"Demo workbook validation failed: {str(e)}",
            ).model_dump(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ApiResponse(
                success=False,
                error_code=ErrorCodes.INTERNAL_ERROR,
                message=f"Error loading demo workbook: {str(e)}",
            ).model_dump(),
        )

    session_id = store.create_session(project_state)
    _prewarm_session(session_id)  # Pre-warm engines immediately

    completed_sprints = sum(1 for sprint in project_state.sprints if sprint.status == SprintStatus.COMPLETED)

    project_summary = ProjectSummary(
        session_id=session_id,
        project_name=project_state.project_info.project_name,
        project_manager=project_state.project_info.project_manager,
        customer=project_state.project_info.customer,
        start_date=project_state.project_info.start_date,
        target_end_date=project_state.project_info.target_end_date,
        total_sprints=len(project_state.sprints),
        total_work_items=len(project_state.work_items),
        total_resources=len(project_state.team),
        total_dependencies=len(project_state.dependencies),
        total_blockers=len(project_state.blockers),
        completed_sprints=completed_sprints,
    )

    response = UploadResponse(
        session_id=session_id,
        project_summary=project_summary,
        validation_warnings=[ValidationIssue(**warning.to_dict()) for warning in warnings],
    )

    return ApiResponse(success=True, data=response.model_dump(), message="Demo workbook loaded")

@router.post("/reset")
async def reset_demo():
    """Clear all sessions so the demo can restart from a clean state."""
    store.clear_all()
    return ApiResponse(success=True, message="Demo sessions cleared", data={"reset": True})