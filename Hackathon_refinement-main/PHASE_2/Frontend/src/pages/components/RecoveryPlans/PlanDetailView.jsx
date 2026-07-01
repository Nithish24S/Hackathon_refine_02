import React, { useState } from 'react'
import ApplyPlanModal from './ApplyPlanModal'

/**
 * PlanDetailView - Expanded view for a single recovery plan
 * 
 * Shows:
 * - Full plan details (archetype, metrics)
 * - List of actions in the plan
 * - Narrative explanation
 * - Trade-offs
 * - Revised sprint plan
 * - Apply Plan button
 */
function PlanDetailView({ plan, session, onBack }) {
  const [showApplyModal, setShowApplyModal] = useState(false)

  return (
    <div className="space-y-6">
      {/* Back Button & Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={onBack}
          className="rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-700"
        >
          ← Back
        </button>
        <div>
          <h2 className="text-2xl font-bold text-white">
            {plan.label} Plan: {plan.archetype}
          </h2>
          <p className="mt-1 text-sm text-slate-400">Recovery strategy and detailed breakdown</p>
        </div>
      </div>

      {/* Metrics Summary */}
      <div className="grid gap-4 grid-cols-1 md:grid-cols-4 rounded-2xl border border-slate-700 bg-slate-900 p-6">
        <div>
          <div className="text-sm uppercase tracking-wide text-slate-400">Deadline Probability</div>
          <div className="mt-2 text-3xl font-bold text-emerald-400">
            {Math.round(plan.score.deadline_probability * 100)}%
          </div>
        </div>
        <div>
          <div className="text-sm uppercase tracking-wide text-slate-400">Expected Delay</div>
          <div className={`mt-2 text-3xl font-bold ${
            plan.score.expected_delay_days <= 0
              ? 'text-emerald-400'
              : plan.score.expected_delay_days <= 5
              ? 'text-amber-400'
              : 'text-rose-400'
          }`}>
            {plan.score.expected_delay_days.toFixed(1)} days
          </div>
        </div>
        <div>
          <div className="text-sm uppercase tracking-wide text-slate-400">Risk Score</div>
          <div className="mt-2 text-3xl font-bold text-slate-300">
            {plan.score.overall_risk_score.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-sm uppercase tracking-wide text-slate-400">Complexity</div>
          <div className={`mt-2 inline-block rounded-lg px-3 py-1 text-lg font-bold ${
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

      {/* Narrative Explanation */}
      <div className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
        <h3 className="text-lg font-bold text-white">Why This Plan</h3>
        <p className="mt-3 text-slate-300 leading-relaxed">
          {plan.explanation.narrative_summary}
        </p>

        {plan.explanation.why_recommended && plan.explanation.why_recommended.length > 0 && (
          <div className="mt-4">
            <p className="text-sm font-semibold text-slate-300">Strengths:</p>
            <ul className="mt-2 space-y-1">
              {plan.explanation.why_recommended.map((reason, idx) => (
                <li key={idx} className="flex items-start gap-2 text-sm text-slate-400">
                  <span className="text-emerald-400 mt-0.5">✓</span>
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {plan.explanation.comparison_to_alternatives && plan.explanation.comparison_to_alternatives.length > 0 && (
          <div className="mt-4">
            <p className="text-sm font-semibold text-slate-300">Compared to Alternatives:</p>
            <ul className="mt-2 space-y-1">
              {plan.explanation.comparison_to_alternatives.map((comparison, idx) => (
                <li key={idx} className="text-sm text-slate-400">
                  • {comparison}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Trade-offs */}
      {plan.explanation.trade_offs && plan.explanation.trade_offs.length > 0 && (
        <div className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
          <h3 className="text-lg font-bold text-white">Trade-offs & Risks</h3>
          <div className="mt-4 space-y-3">
            {plan.explanation.trade_offs.map((tradeoff, idx) => (
              <div
                key={idx}
                className={`rounded-lg border-l-4 p-3 ${
                  tradeoff.severity === 'high'
                    ? 'border-rose-500 bg-rose-500/10'
                    : tradeoff.severity === 'medium'
                    ? 'border-amber-500 bg-amber-500/10'
                    : 'border-slate-500 bg-slate-500/10'
                }`}
              >
                <p className="text-sm text-slate-300">{tradeoff.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions in Plan */}
      {plan.actions && plan.actions.length > 0 && (
        <div className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
          <h3 className="text-lg font-bold text-white">
            Actions in This Plan ({plan.actions.length})
          </h3>
          <div className="mt-4 space-y-3">
            {plan.actions.map((action) => (
              <div
                key={action.recommendation_id}
                className="rounded-lg border border-slate-700 bg-slate-800 p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <h4 className="font-semibold text-white">{action.title}</h4>
                    <p className="mt-1 text-sm text-slate-400">{action.description}</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <span className="inline-block rounded-full bg-slate-700 px-2.5 py-0.5 text-xs text-slate-300">
                        {action.action_type}
                      </span>
                      <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        action.confidence === 'HIGH'
                          ? 'bg-emerald-500/20 text-emerald-300'
                          : action.confidence === 'MEDIUM'
                          ? 'bg-amber-500/20 text-amber-300'
                          : 'bg-rose-500/20 text-rose-300'
                      }`}>
                        {action.confidence} confidence
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-slate-400">Delay reduction</div>
                    <div className="text-xl font-bold text-emerald-400">
                      {action.estimated_delay_reduction_days.toFixed(1)}d
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Revised Sprint Plan */}
      {plan.revised_sprint_plan && plan.revised_sprint_plan.length > 0 && (
        <div className="rounded-2xl border border-slate-700 bg-slate-900 p-6">
          <h3 className="text-lg font-bold text-white">Revised Sprint Plan</h3>
          <div className="mt-4 overflow-x-auto">
            {/* Placeholder for sprint plan table */}
            <p className="text-sm text-slate-400">Sprint assignments and resource allocation after plan applied</p>
          </div>
        </div>
      )}

      {/* Apply Plan Button */}
      <div className="flex gap-3">
        <button
          onClick={() => setShowApplyModal(true)}
          className="flex-1 rounded-lg bg-emerald-500 px-6 py-3 text-lg font-bold text-slate-950 hover:bg-emerald-400 transition"
        >
          Apply This Plan
        </button>
        <button
          onClick={onBack}
          className="rounded-lg border border-slate-600 bg-slate-800 px-6 py-3 font-medium text-slate-300 hover:bg-slate-700 transition"
        >
          Cancel
        </button>
      </div>

      {/* Apply Modal */}
      {showApplyModal && (
        <ApplyPlanModal
          plan={plan}
          session={session}
          onClose={() => setShowApplyModal(false)}
          onConfirm={() => {
            setShowApplyModal(false)
            onBack()
          }}
        />
      )}
    </div>
  )
}

export default PlanDetailView
