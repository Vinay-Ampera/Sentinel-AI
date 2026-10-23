import { WORKFLOW } from './capabilities.js'
import './WorkflowSteps.css'

// The workflow as a bordered grid of numbered steps (shared cell borders, mono labels).
export default function WorkflowSteps() {
  const total = String(WORKFLOW.length).padStart(2, '0')
  return (
    <section className="workflow" aria-labelledby="workflow-title">
      <p className="section-tag">02 // HOW IT WORKS</p>
      <h2 id="workflow-title">From project to evidence in five steps</h2>
      <ol className="workflow-grid">
        {WORKFLOW.map((step, i) => (
          <li key={step.title} className="workflow-step">
            <p className="workflow-num" aria-hidden="true">{String(i + 1).padStart(2, '0')} / {total}</p>
            <h3>{step.title}</h3>
            <p>{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}
