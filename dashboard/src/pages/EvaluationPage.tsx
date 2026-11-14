import { useCallback } from "react";
import { Link, useParams } from "react-router";
import {
  ApiError,
  api,
  type DecisionKind,
  type RunStatus,
  type ScoredClaim,
} from "../api";
import { DecisionChip, RunChip } from "../components/Chips";
import { ClaimLink } from "../components/ClaimLink";
import { Message } from "../components/Message";
import {
  agentsAtOnce,
  cost,
  duration,
  measureColumns,
  money,
  setName,
  time,
} from "../format";
import { SCOREBOARD } from "../paths";
import { REFRESH_MS, useLoad } from "../useLoad";

export function EvaluationPage() {
  const { runId = "" } = useParams();
  const load = useCallback(() => api.getEvaluation(runId), [runId]);
  const { data: evaluation, error } = useLoad(load, REFRESH_MS);

  if (!evaluation) {
    if (error instanceof ApiError && error.status === 404)
      return <p className="message">Evaluation not found</p>;
    return <Message error={error} />;
  }
  const { run, measures, claims } = evaluation;

  return (
    <>
      <p className="muted small">
        <Link to={SCOREBOARD}>Scoreboard</Link>
      </p>
      <div className="claim-heading">
        <h1>
          Evaluation {run.number}: {setName(run)}
        </h1>
        <RunChip status={run.status} />
        <p className="muted small">
          Started at {time(run.started_at)} with {agentsAtOnce(run.agents)}, on{" "}
          <span className="mono">{run.model}</span> with reasoning effort{" "}
          {run.reasoning_effort}
        </p>
      </div>
      <h2 id="measures-title">Measures</h2>
      <section className="tiles" aria-labelledby="measures-title">
        {measureColumns.map(({ name, format }) => (
          <div
            className="panel tile"
            role="group"
            key={name}
            aria-label={`${name}: ${format(measures)}`}
          >
            <span className="small">{name}</span>
            <span className="tile-count mono">{format(measures)}</span>
          </div>
        ))}
      </section>
      <section className="panel table-scroll" aria-labelledby="claims-title">
        <h2 id="claims-title">Claims</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Claim</th>
              <th>Handler</th>
              <th>Agent</th>
              <th className="num">Cost of the mistake</th>
              <th className="num">Model cost</th>
              <th className="num">Time</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim) => (
              <ClaimRow
                key={claim.claim_id}
                claim={claim}
                status={run.status}
              />
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function ClaimRow({
  claim,
  status,
}: Readonly<{ claim: ScoredClaim; status: RunStatus }>) {
  // A copy the agent hasn't reached yet isn't a miss until the run ends.
  const missed =
    !claim.right && (claim.decision !== null || status !== "running");
  return (
    <tr>
      <td className="nowrap">
        <ClaimLink claimId={claim.claim_id} />
        {missed && <span className="chip miss">Miss</span>}
      </td>
      <td className="nowrap">
        <Outcome
          decision={claim.handler_decision}
          payout={claim.handler_payout}
        />
      </td>
      <td className="nowrap">
        {claim.decision ? (
          <Outcome decision={claim.decision} payout={claim.payout ?? 0} />
        ) : (
          <span className="muted">Undecided</span>
        )}
      </td>
      <td className="num mono">{money(claim.mistake_cost)}</td>
      <td className="num mono">{cost(claim.cost)}</td>
      <td className="num mono">{duration(claim.seconds)}</td>
      <td>{claim.reason}</td>
    </tr>
  );
}

function Outcome({
  decision,
  payout,
}: Readonly<{ decision: DecisionKind; payout: number }>) {
  return (
    <>
      <DecisionChip decision={decision} />{" "}
      <span className="mono">{money(payout)}</span>
    </>
  );
}
