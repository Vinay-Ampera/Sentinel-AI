// Wording for assistant runs. Honest by design: a model's answer is a suggestion built from
// stored evidence, never a verdict, and a failed model step is explained, not hidden.
export const WORKFLOW = {
  planning: 'Test planning',
  analysis: 'Analysis interpretation',
  investigation: 'Failure investigation',
  regression: 'Regression test draft',
  verification: 'Fix verification',
}

export const workflowLabel = (v) => WORKFLOW[v] || String(v).replace(/_/g, ' ')

export const DEGRADED = {
  llm_disabled: 'The assistant model is not configured on this server, so only the built-in checks ran.',
  llm_unavailable: 'The model service was unavailable.',
  llm_timeout: 'The model did not answer in time.',
  budget_blocked: 'The model usage limit was reached.',
  invalid_output: 'The model reply did not pass validation and was discarded.',
  deadline_exceeded: 'The time limit for this run was reached.',
  prompt_too_large: 'There was too much evidence to send safely.',
}

export const degradedLabel = (reason) => DEGRADED[reason] || 'A model step did not complete.'

export const SOURCE = { keywords: 'Matched by keywords (no model used)', model: 'Suggested by the model', cache: 'Reused from an earlier identical request' }

export const CAUSE_LABEL = { likely: 'Likely', hypothesis: 'Hypothesis' }
export const CLAIM_LABEL = { inference: 'Inference', hypothesis: 'Hypothesis' }

export const VERDICT = {
  fixed_by_rescan: 'No longer reported by a complete re-scan',
  still_present: 'Reported again by the re-scan',
  inconclusive: 'Inconclusive',
}

export const STEP_KIND = { deterministic: 'Built-in', decision: 'Decision', llm: 'Model', policy: 'Policy check' }

export const canRun = (project) => project.your_access === 'run' || project.your_access === 'manage'
