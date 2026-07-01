import React from 'react'

/**
 * ComparePlansTable - Side-by-side comparison of all 3 recovery plans
 * 
 * This is the highest-value UI element for judges:
 * - 3 rows (one per plan)
 * - 5 columns (Archetype, Probability, Delay, Risk, Complexity)
 * - Recommended plan is highlighted
 * - Click row to expand details
 */
function ComparePlansTable({ plans, onSelectPlan }) {
  if (!plans || plans.length === 0) {
    return <div className="text-center text-slate-400">No plans to compare</div>
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-700 bg-slate-900">
      <table className="w-full text-sm">
        <thead className="border-b border-slate-700 bg-slate-800">
          <tr>
            <th className="px-4 py-3 text-left font-semibold text-slate-300">Plan</th>
            <th className="px-4 py-3 text-left font-semibold text-slate-300">Strategy</th>
            <th className="px-4 py-3 text-center font-semibold text-slate-300">
              <div className="text-xs uppercase tracking-wide">Deadline</div>
              <div className="text-xs text-slate-400">Probability</div>
            </th>
            <th className="px-4 py-3 text-center font-semibold text-slate-300">
              <div className="text-xs uppercase tracking-wide">Expected</div>
              <div className="text-xs text-slate-400">Delay (days)</div>
            </th>
            <th className="px-4 py-3 text-center font-semibold text-slate-300">
              <div className="text-xs uppercase tracking-wide">Risk</div>
              <div className="text-xs text-slate-400">Score</div>
            </th>
            <th className="px-4 py-3 text-center font-semibold text-slate-300">
              <div className="text-xs uppercase tracking-wide">Complexity</div>
              <div className="text-xs text-slate-400">Actions</div>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700">
          {plans.map((plan) => (
            <tr
              key={plan.plan_id}
              onClick={() => onSelectPlan(plan.plan_id)}
              className={`cursor-pointer transition hover:bg-slate-800/50 ${
                plan.label === 'Recommended' ? 'bg-emerald-500/10 border-l-4 border-emerald-500' : ''
              }`}
            >
              {/* Plan Label */}
              <td className="px-4 py-4">
                <div className="flex items-center gap-2">
                  {plan.label === 'Recommended' && (
                    <span className="text-lg">⭐</span>
                  )}
                  <div>
                    <div className="font-semibold text-slate-200">{plan.label}</div>
                    <div className="text-xs text-slate-500">{plan.archetype}</div>
                  </div>
                </div>
              </td>

              {/* Strategy Description */}
              <td className="px-4 py-4 text-xs text-slate-400">
                {_getStrategyDescription(plan.archetype)}
              </td>

              {/* Deadline Probability */}
              <td className="px-4 py-4">
                <div className="text-center">
                  <div className="text-lg font-bold text-emerald-400">
                    {Math.round(plan.score.deadline_probability * 100)}%
                  </div>
                  <div className="mt-1 h-1.5 w-12 mx-auto bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-emerald-500"
                      style={{ width: `${plan.score.deadline_probability * 100}%` }}
                    ></div>
                  </div>
                </div>
              </td>

              {/* Expected Delay */}
              <td className="px-4 py-4 text-center">
                <div className={`font-semibold ${
                  plan.score.expected_delay_days <= 0
                    ? 'text-emerald-400'
                    : plan.score.expected_delay_days <= 5
                    ? 'text-amber-400'
                    : 'text-rose-400'
                }`}>
                  {plan.score.expected_delay_days.toFixed(1)}
                </div>
              </td>

              {/* Risk Score */}
              <td className="px-4 py-4 text-center">
                <div className="font-semibold text-slate-300">
                  {plan.score.overall_risk_score.toFixed(2)}
                </div>
              </td>

              {/* Complexity & Actions */}
              <td className="px-4 py-4">
                <div className="text-center">
                  <div className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${
                    plan.score.execution_complexity === 'Low'
                      ? 'bg-emerald-500/20 text-emerald-300'
                      : plan.score.execution_complexity === 'Medium'
                      ? 'bg-amber-500/20 text-amber-300'
                      : 'bg-rose-500/20 text-rose-300'
                  }`}>
                    {plan.score.execution_complexity}
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {plan.score.actions_required} {plan.score.actions_required === 1 ? 'action' : 'actions'}
                  </div>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Instructions */}
      <div className="border-t border-slate-700 bg-slate-800 px-4 py-3 text-center text-xs text-slate-400">
        Click a row to view detailed plan breakdown
      </div>
    </div>
  )
}

function _getStrategyDescription(archetype) {
  const descriptions = {
    SAFE: 'High-confidence actions only',
    AGGRESSIVE: 'Maximum delay recovery',
    MINIMAL_DISRUPTION: 'Minimal team disruption',
  }
  return descriptions[archetype] || archetype
}

export default ComparePlansTable
