import React from 'react'

/**
 * RecoveryPlanCard - Individual card for a recovery plan
 * 
 * Displays:
 * - Archetype label with "Recommended" badge if applicable
 * - Key metrics: deadline probability, delay, actions, complexity
 * - Click to expand
 */
function RecoveryPlanCard({ plan, isRecommended, onExpand }) {
  const archetypeLabelMap = {
    SAFE: 'Safe Plan',
    AGGRESSIVE: 'Aggressive Plan',
    MINIMAL_DISRUPTION: 'Minimal Disruption',
  }

  const archetypeDescMap = {
    SAFE: 'High-confidence actions only',
    AGGRESSIVE: 'Maximum delay recovery',
    MINIMAL_DISRUPTION: 'Minimal team disruption',
  }

  const label = archetypeLabelMap[plan.archetype] || plan.archetype
  const description = archetypeDescMap[plan.archetype] || ''

  return (
    <div
      onClick={onExpand}
      className={`rounded-2xl border-2 p-6 cursor-pointer transition hover:shadow-lg ${
        isRecommended
          ? 'border-emerald-500 bg-emerald-500/10 hover:bg-emerald-500/15 shadow-emerald-500/20'
          : 'border-slate-600 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-500'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-bold text-white">{label}</h3>
            {isRecommended && (
              <span className="inline-block rounded-full bg-emerald-500 px-2.5 py-0.5 text-xs font-semibold text-slate-950">
                ⭐ Recommended
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-400">{description}</p>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="mt-6 space-y-4">
        {/* Deadline Probability */}
        <div>
          <div className="flex items-center justify-between text-xs">
            <span className="uppercase tracking-wide text-slate-400">Deadline Probability</span>
            <span className="text-lg font-bold text-emerald-400">
              {Math.round(plan.score.deadline_probability * 100)}%
            </span>
          </div>
          <div className="mt-1.5 h-2 w-full bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400"
              style={{ width: `${plan.score.deadline_probability * 100}%` }}
            ></div>
          </div>
        </div>

        {/* Expected Delay */}
        <div>
          <div className="flex items-center justify-between text-xs">
            <span className="uppercase tracking-wide text-slate-400">Expected Delay</span>
            <span className={`font-bold ${
              plan.score.expected_delay_days <= 0
                ? 'text-emerald-400'
                : plan.score.expected_delay_days <= 5
                ? 'text-amber-400'
                : 'text-rose-400'
            }`}>
              {plan.score.expected_delay_days.toFixed(1)} days
            </span>
          </div>
        </div>

        {/* Risk Score */}
        <div>
          <div className="flex items-center justify-between text-xs">
            <span className="uppercase tracking-wide text-slate-400">Overall Risk</span>
            <span className="font-bold text-slate-300">
              {plan.score.overall_risk_score.toFixed(2)}
            </span>
          </div>
        </div>

        {/* Actions & Complexity */}
        <div className="flex gap-4 pt-2">
          <div className="flex-1">
            <div className="text-xs uppercase tracking-wide text-slate-400">Actions</div>
            <div className="mt-1 text-2xl font-bold text-white">
              {plan.score.actions_required}
            </div>
          </div>
          <div className="flex-1">
            <div className="text-xs uppercase tracking-wide text-slate-400">Complexity</div>
            <div className={`mt-1 inline-block rounded-lg px-2.5 py-1 text-xs font-bold ${
              plan.score.execution_complexity === 'Low'
                ? 'bg-emerald-500/20 text-emerald-300'
                : plan.score.execution_complexity === 'Medium'
                ? 'bg-amber-500/20 text-amber-300'
                : 'bg-rose-500/20 text-rose-300'
            }`}>
              {plan.score.execution_complexity}
            </div>
          </div>
        </div>
      </div>

      {/* Action Button */}
      <button
        onClick={(e) => {
          e.stopPropagation()
          onExpand()
        }}
        className="mt-6 w-full rounded-lg border border-slate-500 bg-slate-700/30 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-700/50 transition"
      >
        View Details →
      </button>
    </div>
  )
}

export default RecoveryPlanCard
