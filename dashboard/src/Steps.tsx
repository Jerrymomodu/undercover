import type { Step, StepKind } from "./api";

const KIND_LABELS: Record<StepKind, string> = {
  tool_call: "Called",
  tool_result: "Result",
  reply: "Reply",
  note: "Note",
};

export function Steps({
  steps,
  working,
}: Readonly<{ steps: Step[]; working: boolean }>) {
  return (
    <section className="panel" aria-labelledby="steps-heading">
      <h2 id="steps-heading">Agent steps</h2>
      {steps.length === 0 ? (
        <p className="muted">The agent hasn't worked on this claim yet.</p>
      ) : (
        <ol className="steps" aria-live="polite">
          {steps.map((step) => (
            <li key={step.step_id} className={`step step-${step.kind}`}>
              <span className="step-kind">{KIND_LABELS[step.kind]}</span>
              <span className="step-text">{step.text}</span>
            </li>
          ))}
        </ol>
      )}
      {working && <p className="muted working">The agent is working</p>}
    </section>
  );
}
