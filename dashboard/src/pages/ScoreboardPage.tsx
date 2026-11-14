import { useState } from "react";
import { Link } from "react-router";
import { api, type EvalSet, type Evaluation } from "../api";
import { AgentsInput, DEFAULT_AGENTS } from "../components/AgentsInput";
import { RunChip } from "../components/Chips";
import { Message } from "../components/Message";
import { dateTime, measureColumns, setLabels, setName } from "../format";
import { evaluationPage } from "../paths";
import { REFRESH_MS, useLoad } from "../useLoad";
import { useSubmit } from "../useSubmit";

export function ScoreboardPage() {
  const {
    data: evaluations,
    error,
    reload,
  } = useLoad(api.listEvaluations, REFRESH_MS);

  return (
    <>
      <h1>Scoreboard</h1>
      <p className="lead">
        Each evaluation works copies of a labeled set of claims, away from the
        queue, and scores the agent against our handlers' decisions.
      </p>
      <section className="panel run" aria-labelledby="start-title">
        <h2 id="start-title">Start an evaluation</h2>
        <StartEvaluation onStarted={reload} />
      </section>
      <section
        className="panel table-scroll"
        aria-labelledby="evaluations-title"
      >
        <h2 id="evaluations-title">Evaluations</h2>
        {evaluations === undefined && <Message error={error} />}
        {evaluations?.length === 0 && (
          <p className="muted">No evaluations yet.</p>
        )}
        {evaluations && evaluations.length > 0 && (
          <EvaluationTable evaluations={evaluations} />
        )}
      </section>
    </>
  );
}

function StartEvaluation({ onStarted }: Readonly<{ onStarted: () => void }>) {
  const [evalSet, setEvalSet] = useState<EvalSet>("evaluation");
  const [tiny, setTiny] = useState(false);
  const [agents, setAgents] = useState(DEFAULT_AGENTS);
  const { submit, sending, error } = useSubmit(
    () => api.startEvaluation(Number(agents), evalSet, tiny),
    onStarted,
    "The evaluation didn't start",
  );

  return (
    <form className="start-form" onSubmit={submit}>
      <label>
        Set
        <select
          value={evalSet}
          onChange={(event) => {
            setEvalSet(event.target.value as EvalSet);
          }}
        >
          {Object.entries(setLabels).map(([value, name]) => (
            <option key={value} value={value}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={tiny}
          onChange={(event) => {
            setTiny(event.target.checked);
          }}
        />
        Just its five tiny claims
      </label>
      <AgentsInput value={agents} onChange={setAgents} />
      <button type="submit" disabled={sending}>
        Start evaluation
      </button>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function EvaluationTable({
  evaluations,
}: Readonly<{ evaluations: Evaluation[] }>) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Evaluation</th>
          <th>Started</th>
          <th>Set</th>
          <th className="num">Agents</th>
          <th>Model</th>
          <th>State</th>
          {measureColumns.map(({ name }) => (
            <th className="num" key={name}>
              {name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {evaluations.map(({ run, measures }) => (
          <tr key={run.run_id}>
            <td className="nowrap">
              <Link to={evaluationPage(run.run_id)}>
                Evaluation {run.number}
              </Link>
            </td>
            <td className="nowrap">{dateTime(run.started_at)}</td>
            <td className="nowrap">{setName(run)}</td>
            <td className="num mono">{run.agents}</td>
            <td className="nowrap">
              <span className="mono">{run.model}</span>
              <span className="muted small">
                , effort {run.reasoning_effort}
              </span>
            </td>
            <td>
              <RunChip status={run.status} />
            </td>
            {measureColumns.map(({ name, format }) => (
              <td className="num mono" key={name}>
                {format(measures)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
