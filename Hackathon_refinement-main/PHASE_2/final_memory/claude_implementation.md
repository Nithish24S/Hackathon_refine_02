You are working on Sprint Whisperer, a FastAPI + React hackathon project for sprint forecasting.

I have 6 new files that need to be integrated into the existing codebase. Apply every change below exactly as described. Do not modify any other files. Do not refactor existing code unless explicitly told to.

---

## FILE 1 — CREATE NEW FILE
Path: `PHASE_2/backend/app/api/routes/reforecast_comparison.py`
Action: Create this file with the following content exactly:

```python
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
```

---

## FILE 2 — REPLACE EXISTING FILE
Path: `PHASE_2/backend/app/api/routes/demo.py`
Action: Replace the entire file content with the following:

```python
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
```

---

## FILE 3 — EDIT EXISTING FILE
Path: `PHASE_2/backend/app/api/routes/recommendations.py`
Action: Two targeted edits only. Do not touch anything else in this file.

### Edit 3a — Register the new route in main.py
Skip to Edit 3b first, then come back to this.

### Edit 3b — Cache simulation result on session
Find the `simulate_recommendation` function. Inside it, find this exact line:
```python
        response = RecommendationSimulationResponse(
```
Insert these lines IMMEDIATELY BEFORE that line (preserving indentation):
```python
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
```
Also verify that `from app.storage import store` is already imported at the top of this file. If not, add it.

---

## FILE 4 — EDIT EXISTING FILE
Path: `PHASE_2/backend/app/main.py`
Action: Find where other routers are registered with `app.include_router(...)`. Add this new router registration alongside them:
```python
from app.api.routes.reforecast_comparison import router as reforecast_router
app.include_router(reforecast_router)
```

---

## FILE 5 — EDIT EXISTING FILE
Path: `PHASE_2/Frontend/src/api/client.js`
Action: Find the closing `}` of the `api` object (the line just before `export const api` or the closing brace of the object). Add these two new methods inside the object, before the closing brace:
```javascript
  reforecastComparison: async (sessionId = '') => {
    let url = `${API_ROOT}/reforecast-comparison`
    if (sessionId) url += `?session_id=${encodeURIComponent(sessionId)}`
    const resp = await fetch(url)
    return unwrapResponse(resp)
  },

  narrative: async (sessionId = '') => {
    let url = `${API_ROOT}/narrative`
    if (sessionId) url += `?session_id=${encodeURIComponent(sessionId)}`
    const resp = await fetch(url)
    return unwrapResponse(resp)
  },
```

---

## FILE 6 — EDIT EXISTING FILE (largest change)
Path: `PHASE_2/Frontend/src/pages/Dashboard.jsx`
Action: Six targeted edits. Apply in order.

### Edit 6a — Add Compare tab
Find:
```javascript
const tabs = [
  { key: 'overview', label: 'Overview' },
  { key: 'risk', label: 'Risk' },
  { key: 'critical-path', label: 'Critical Path' },
  { key: 'forecast', label: 'Forecast' },
  { key: 'recovery-plans', label: 'Recovery Plans' },
  { key: 'actions', label: 'Actions' },
]
```
Replace with:
```javascript
const tabs = [
  { key: 'overview', label: 'Overview' },
  { key: 'risk', label: 'Risk' },
  { key: 'critical-path', label: 'Critical Path' },
  { key: 'forecast', label: 'Forecast' },
  { key: 'recovery-plans', label: 'Recovery Plans' },
  { key: 'actions', label: 'Actions' },
  { key: 'compare', label: '📊 Compare' },
]
```

### Edit 6b — Replace HeroBanner function
Find the entire `function HeroBanner({session}){` function (from its declaration to its closing `}`). Replace it entirely with:
```jsx
function HeroBanner({ session, onNavigate }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [mc, setMc] = useState(null)
  const sessionId = session?.project_summary?.session_id || ''

  const fetchData = async () => {
    if (!sessionId) { setError(new Error('Missing session id')); setLoading(false); return }
    setLoading(true)
    setError(null)
    try {
      const [f, m] = await Promise.all([api.forecast(sessionId), api.monteCarlo(sessionId)])
      setForecast(f?.forecast ?? f)
      setMc(m?.monte_carlo ?? m)
      setLoading(false)
    } catch (err) {
      setError(err)
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [sessionId])

  if (loading) return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
      <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Project status</p>
      <h2 className="mt-2 text-3xl font-extrabold text-white">Computing forecast…</h2>
      <p className="mt-2 text-sm text-slate-400">Running Monte Carlo simulation</p>
    </section>
  )

  if (error) return (
    <section className="rounded-3xl border border-rose-600 bg-rose-900/10 p-6">
      <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Project status</p>
      <h2 className="mt-2 text-3xl font-extrabold text-rose-200">Status unavailable</h2>
      <p className="mt-2 text-sm text-rose-300">{error.message || 'Failed to load forecast or Monte Carlo results'}</p>
      <button onClick={fetchData} className="mt-4 rounded-2xl border border-rose-500 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200">Retry</button>
    </section>
  )

  const prob = mc && mc.on_time_probability !== undefined ? Math.round(mc.on_time_probability * 100) : null
  const expected = forecast && typeof forecast.expected_delay_days === 'number' ? Math.round(forecast.expected_delay_days) : null

  const probColor = prob === null ? 'text-slate-400'
    : prob >= 70 ? 'text-emerald-400'
    : prob >= 40 ? 'text-amber-400'
    : 'text-rose-400'

  const probLabel = prob === null ? 'No data'
    : prob >= 70 ? 'On track'
    : prob >= 40 ? 'At risk'
    : 'Critical risk'

  const delayText = expected === null ? null
    : expected < 0 ? `${Math.abs(expected)} days ahead of schedule`
    : expected === 0 ? 'On schedule'
    : `${expected} days late`

  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-inner shadow-black/20">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-end gap-5">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-slate-400">On-time probability</p>
            <div className={`mt-1 text-8xl font-extrabold leading-none ${probColor}`}>
              {prob !== null ? `${prob}%` : '—'}
            </div>
            <div className={`mt-2 text-sm font-semibold uppercase tracking-[0.15em] ${probColor}`}>{probLabel}</div>
            {expected !== null && expected > 0 && (
              <div className="mt-2 flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-rose-500"></span>
                <span className="text-sm text-rose-300 font-semibold">{delayText}</span>
              </div>
            )}
            {expected !== null && expected <= 0 && (
              <div className="mt-2 text-sm text-emerald-400">{delayText}</div>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-3">
          <button
            onClick={() => onNavigate && onNavigate('actions')}
            className="rounded-2xl border border-amber-500 bg-amber-500/15 px-6 py-3 text-sm font-bold text-amber-200 hover:bg-amber-500/25 transition text-center"
          >
            What should I do? →
          </button>
          <button
            onClick={() => onNavigate && onNavigate('compare')}
            className="rounded-2xl border border-slate-600 bg-slate-800 px-6 py-3 text-sm font-semibold text-slate-200 hover:bg-slate-700 transition text-center"
          >
            Compare forecasts →
          </button>
          {mc?.on_time_risk_level && (
            <div className="text-center text-xs uppercase tracking-[0.2em] text-slate-500">
              Risk level: <span className={`font-semibold ${probColor}`}>{mc.on_time_risk_level}</span>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
```

### Edit 6c — Add SprintRiskHeatmap and ReforecastPage components
Find the line:
```javascript
function ActionsPage({session}){
```
Insert the following two complete component definitions IMMEDIATELY BEFORE that line:

```jsx
function SprintRiskHeatmap({ session }) {
  const [loading, setLoading] = useState(true)
  const [sprints, setSprints] = useState([])
  const sessionId = session?.project_summary?.session_id || ''

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    api.risk(sessionId)
      .then(r => {
        const riskData = r?.risk_assessment ?? r
        setSprints(riskData?.sprint_risks || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [sessionId])

  if (loading) return (
    <div className="rounded-2xl border border-slate-700 bg-slate-900 p-4">
      <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Sprint risk heatmap</p>
      <p className="mt-2 text-sm text-slate-500">Loading sprint risks…</p>
    </div>
  )

  if (!sprints.length) return null

  const riskColor = (score) => {
    if (score >= 70) return 'bg-rose-500'
    if (score >= 45) return 'bg-amber-500'
    return 'bg-emerald-500'
  }

  const riskTextColor = (score) => {
    if (score >= 70) return 'text-rose-400'
    if (score >= 45) return 'text-amber-400'
    return 'text-emerald-400'
  }

  return (
    <div className="rounded-3xl border border-slate-700 bg-slate-900 p-5">
      <p className="text-xs uppercase tracking-[0.3em] text-amber-400 mb-1">Sprint risk heatmap</p>
      <h3 className="text-lg font-semibold text-white mb-4">At a glance — which sprint is your problem?</h3>
      <div className="flex flex-wrap gap-3">
        {sprints.map((sprint, i) => {
          const score = Math.round(sprint.risk_score ?? sprint.score ?? 0)
          const name = sprint.sprint_name || sprint.sprint_id || `Sprint ${i + 1}`
          const blockerCount = sprint.blocker_count ?? sprint.active_blockers ?? 0
          const spilloverCount = sprint.spillover_count ?? sprint.spillover_items ?? 0
          return (
            <div key={sprint.sprint_id || i} className="relative group cursor-default">
              <div className={`${riskColor(score)} rounded-2xl w-20 h-20 flex flex-col items-center justify-center gap-1 transition hover:opacity-80`}>
                <div className="text-xs font-bold text-white/90 truncate px-2 text-center leading-tight">{name}</div>
                <div className="text-xl font-extrabold text-white">{score}</div>
              </div>
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-10 hidden group-hover:block w-48">
                <div className="rounded-2xl border border-slate-600 bg-slate-800 p-3 shadow-xl text-xs">
                  <div className={`font-bold mb-1 ${riskTextColor(score)}`}>{name} — risk {score}/100</div>
                  {blockerCount > 0 && <div className="text-rose-300">⛔ {blockerCount} active blocker{blockerCount > 1 ? 's' : ''}</div>}
                  {spilloverCount > 0 && <div className="text-amber-300">⚠ {spilloverCount} spillover item{spilloverCount > 1 ? 's' : ''}</div>}
                  {sprint.overload_pct !== undefined && sprint.overload_pct > 100 && <div className="text-amber-300">📈 {Math.round(sprint.overload_pct)}% loaded</div>}
                  {blockerCount === 0 && spilloverCount === 0 && <div className="text-slate-400">No critical issues</div>}
                </div>
                <div className="w-2 h-2 border-b border-r border-slate-600 bg-slate-800 rotate-45 mx-auto -mt-1"></div>
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-4 flex gap-4 text-xs text-slate-400">
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-emerald-500"></span> Low (&lt;45)</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-amber-500"></span> Medium (45–69)</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-rose-500"></span> High (70+)</span>
      </div>
    </div>
  )
}

function ScenarioColumn({ label, badge, badgeColor, data, probColor, formatDate, summary }) {
  if (!data) return null
  const prob = data.on_time_probability
  const delay = data.expected_delay_days
  const risk = data.overall_risk_score
  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6 space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-sm uppercase tracking-[0.3em] text-slate-400">{label}</p>
        <span className={`text-xs font-bold px-3 py-1 rounded-full border ${badgeColor}`}>{badge}</span>
      </div>
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-slate-500 mb-1">On-time probability</div>
        <div className={`text-6xl font-extrabold ${probColor(prob)}`}>
          {prob !== undefined && prob !== null ? `${prob}%` : '—'}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl bg-slate-950 p-3">
          <div className="text-xs text-slate-500 uppercase tracking-wide">Delay</div>
          <div className={`mt-1 text-xl font-bold ${delay > 0 ? 'text-rose-300' : 'text-emerald-300'}`}>
            {delay !== undefined ? (delay > 0 ? `+${delay}d` : `${delay}d`) : '—'}
          </div>
        </div>
        <div className="rounded-2xl bg-slate-950 p-3">
          <div className="text-xs text-slate-500 uppercase tracking-wide">Risk score</div>
          <div className={`mt-1 text-xl font-bold ${risk >= 60 ? 'text-rose-300' : risk >= 40 ? 'text-amber-300' : 'text-emerald-300'}`}>
            {risk !== undefined ? Math.round(risk) : '—'}<span className="text-sm text-slate-500">/100</span>
          </div>
        </div>
        <div className="rounded-2xl bg-slate-950 p-3 col-span-2">
          <div className="text-xs text-slate-500 uppercase tracking-wide">P50 finish</div>
          <div className="mt-1 text-sm font-semibold text-white">{formatDate(data.p50_date)}</div>
        </div>
        <div className="rounded-2xl bg-slate-950 p-3">
          <div className="text-xs text-slate-500 uppercase tracking-wide">P80</div>
          <div className="mt-1 text-sm font-semibold text-slate-200">{formatDate(data.p80_date)}</div>
        </div>
        <div className="rounded-2xl bg-slate-950 p-3">
          <div className="text-xs text-slate-500 uppercase tracking-wide">P95</div>
          <div className="mt-1 text-sm font-semibold text-slate-200">{formatDate(data.p95_date)}</div>
        </div>
      </div>
      {summary && (
        <div className="rounded-2xl border border-emerald-800 bg-emerald-900/10 p-3">
          <div className="text-xs uppercase tracking-wide text-emerald-400 mb-1">What changed</div>
          <p className="text-sm text-slate-300">{summary}</p>
        </div>
      )}
    </section>
  )
}

function ReforecastPage({ session }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)
  const sessionId = session?.project_summary?.session_id || ''

  const load = () => {
    if (!sessionId) { setError(new Error('Missing session id')); setLoading(false); return }
    setLoading(true)
    setError(null)
    api.reforecastComparison(sessionId)
      .then(d => { setData(d); setLoading(false) })
      .catch(err => { setError(err); setLoading(false) })
  }

  useEffect(() => { load() }, [sessionId])

  if (loading) return (
    <section className="rounded-3xl border border-slate-700 bg-slate-900 p-8 text-center">
      <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Reforecast</p>
      <p className="mt-3 text-sm text-slate-400">Computing comparison…</p>
    </section>
  )

  if (error) return (
    <section className="rounded-3xl border border-rose-600 bg-rose-900/10 p-8">
      <p className="text-sm uppercase tracking-[0.3em] text-rose-400">Reforecast unavailable</p>
      <p className="mt-2 text-sm text-rose-300">{error.message}</p>
      <button onClick={load} className="mt-4 rounded-2xl border border-rose-500 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200">Retry</button>
    </section>
  )

  if (!data) return null

  const { baseline, after_recommendation, deltas } = data
  const hasSimulation = after_recommendation?.on_time_risk_level !== 'NO_SIMULATION_YET'

  const probColor = (p) => {
    if (p >= 70) return 'text-emerald-400'
    if (p >= 40) return 'text-amber-400'
    return 'text-rose-400'
  }

  const formatDate = (iso) => {
    if (!iso) return '—'
    try { return new Date(iso).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) }
    catch { return iso }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-700 bg-slate-900 p-6">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Reforecast comparison</p>
        <h2 className="mt-2 text-2xl font-bold text-white">Before vs. After</h2>
        <p className="mt-1 text-sm text-slate-400">
          {hasSimulation ? 'Showing impact of your last simulated recommendation.' : 'Simulate a recommendation in the Actions tab to see the after column.'}
        </p>
      </section>
      {hasSimulation && deltas && (
        <section className={`rounded-3xl border p-5 flex flex-col sm:flex-row gap-6 items-center justify-center ${deltas.has_improvement ? 'border-emerald-600 bg-emerald-900/20' : 'border-slate-700 bg-slate-900'}`}>
          <div className="text-center">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Probability gain</div>
            <div className={`mt-1 text-4xl font-extrabold ${deltas.probability_gain_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {deltas.probability_gain_pct >= 0 ? '+' : ''}{deltas.probability_gain_pct}%
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Days saved</div>
            <div className={`mt-1 text-4xl font-extrabold ${deltas.days_saved >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {deltas.days_saved >= 0 ? '+' : ''}{deltas.days_saved}d
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Risk reduction</div>
            <div className={`mt-1 text-4xl font-extrabold ${deltas.risk_score_reduction >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {deltas.risk_score_reduction >= 0 ? '−' : '+'}{Math.abs(deltas.risk_score_reduction)}
            </div>
          </div>
        </section>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <ScenarioColumn label="Baseline" badge="BEFORE" badgeColor="text-rose-300 border-rose-600 bg-rose-900/20" data={baseline} probColor={probColor} formatDate={formatDate} />
        {hasSimulation ? (
          <ScenarioColumn label="After recommendation" badge="AFTER" badgeColor="text-emerald-300 border-emerald-600 bg-emerald-900/20" data={after_recommendation} probColor={probColor} formatDate={formatDate} summary={after_recommendation.summary} />
        ) : (
          <section className="rounded-3xl border border-dashed border-slate-600 bg-slate-900/40 p-6 flex items-center justify-center text-center">
            <div>
              <div className="text-slate-500 text-4xl mb-3">?</div>
              <p className="text-sm uppercase tracking-[0.2em] text-slate-500">No simulation yet</p>
              <p className="mt-2 text-xs text-slate-600">Go to Actions → pick a recommendation → Simulate.</p>
            </div>
          </section>
        )}
      </div>
      <div className="flex justify-center">
        <button onClick={load} className="rounded-2xl border border-slate-600 bg-slate-800 px-5 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-700">Refresh comparison</button>
      </div>
    </div>
  )
}
```

### Edit 6d — Wire ActionsPage onSimulated prop
Find:
```javascript
function ActionsPage({session}){
```
Replace with:
```javascript
function ActionsPage({ session, onSimulated }) {
```

Then inside the `simulate` function, find:
```javascript
      setSimulationResult(resp.simulation_result || resp)
```
Add immediately after it:
```javascript
      onSimulated && onSimulated()
```

### Edit 6e — Wire OverviewPage onNavigate prop
Find:
```javascript
function OverviewPage({session, metrics}){
```
Replace with:
```javascript
function OverviewPage({ session, metrics, onNavigate }) {
```

Then find `<HeroBanner session={session} />` inside OverviewPage and replace with:
```jsx
<HeroBanner session={session} onNavigate={onNavigate} />
```

### Edit 6f — Wire SprintRiskHeatmap into RiskPage
Find the `function RiskPage({session}){` function. Inside its JSX return, at the very top before any other content, add:
```jsx
<SprintRiskHeatmap session={session} />
```

### Edit 6g — Update Dashboard render calls
Find:
```jsx
      {active === 'overview' && <>
        <OverviewPage session={session} metrics={metrics} />
```
Replace with:
```jsx
      {active === 'overview' && <>
        <OverviewPage session={session} metrics={metrics} onNavigate={setActive} />
```

Find:
```jsx
      {active === 'actions' && <ActionsPage session={session} />}
```
Replace with:
```jsx
      {active === 'actions' && <ActionsPage session={session} onSimulated={() => setActive('compare')} />}
      {active === 'compare' && <ReforecastPage session={session} />}
```

---

## VERIFICATION CHECKLIST
After applying all changes, confirm:
- [ ] `PHASE_2/backend/app/api/routes/reforecast_comparison.py` exists
- [ ] `PHASE_2/backend/app/api/routes/demo.py` has `_prewarm_session` function
- [ ] `PHASE_2/backend/app/api/routes/recommendations.py` has the `last_simulation_result` cache block before `RecommendationSimulationResponse(`
- [ ] `PHASE_2/backend/app/main.py` includes `reforecast_router`
- [ ] `PHASE_2/Frontend/src/api/client.js` has `reforecastComparison` method
- [ ] `PHASE_2/Frontend/src/pages/Dashboard.jsx` has `compare` tab key in tabs array
- [ ] `PHASE_2/Frontend/src/pages/Dashboard.jsx` has `ReforecastPage`, `SprintRiskHeatmap`, `ScenarioColumn` components defined
- [ ] `HeroBanner` has `onNavigate` prop and `text-8xl` probability number

Do not change anything else. If any file has syntax errors after editing, fix them before finishing.