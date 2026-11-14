import { useState } from "react";
import { api, type Run, type RunSummary } from "../api";
import { agentsAtOnce, cost, duration, money, time } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";
import { useSubmit } from "../useSubmit";
import { AgentsInput, DEFAULT_AGENTS } from "./AgentsInput";
import { DecisionChip, RunChip, StatusChip } from "./Chips";
import { ClaimLink, ClaimLinks } from "./ClaimLink";
import { Message } from "./Message";

export function DispatchPanel() {
  const {
    data: run,
    error,
    reload,
  } = useLoad(api.getLatestDispatch, REFRESH_MS);

  return (
    <section className="panel run" aria-labelledby="dispatch-title">
      <div className="run-heading">
        <h2 id="dispatch-title">Dispatch</h2>
        {run && <RunChip status={run.status} />}
      </div>
      <StartDispatch onStarted={reload} />
      {run === undefined && <Message error={error} />}
      {run === null && <p className="muted">No dispatch yet.</p>}
      {run && <DispatchDetails run={run} />}
    </section>
  );
}

function StartDispatch({ onStarted }: Readonly<{ onStarted: () => void }>) {
  const [agents, setAgents] = useState(DEFAULT_AGENTS);
  const { submit, sending, error } = useSubmit(
    () => api.startDispatch(Number(agents)),
    onStarted,
    "The dispatch didn't start",
  );

  return (
    <form className="start-form" onSubmit={submit}>
      <AgentsInput value={agents} onChange={setAgents} />
      <button type="submit" disabled={sending}>
        Start dispatch
      </button>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function secondsBetween(start: string, end: string): number {
  return (Date.parse(end) - Date.parse(start)) / 1000;
}

function DispatchDetails({ run }: Readonly<{ run: Run }>) {
  const { finished_at } = run;
  return (
    <>
      <p className="muted small">
        Started at {time(run.started_at)} with {agentsAtOnce(run.agents)}
        {finished_at && `, finished at ${time(finished_at)}`}
      </p>
      <p className="small">
        Model cost <span className="mono">{cost(run.cost)}</span>, agent time{" "}
        <span className="mono">{duration(run.agent_seconds)}</span>
        {finished_at && (
          <>
            , the whole run{" "}
            <span className="mono">
              {duration(secondsBetween(run.started_at, finished_at))}
            </span>
          </>
        )}
      </p>
      <h3>Claims</h3>
      {run.claims.length === 0 ? (
        <p className="muted">No claims to work.</p>
      ) : (
        <ol className="run-claims">
          {run.claims.map((claim) => (
            <li className="run-claim" key={claim.claim_id}>
              <StatusChip status={claim.status} />
              <ClaimLink claimId={claim.claim_id} />
              {claim.decision && <DecisionChip decision={claim.decision} />}
              {claim.payout !== null && (
                <span className="mono">{money(claim.payout)}</span>
              )}
            </li>
          ))}
        </ol>
      )}
      {run.status !== "running" && <Summary summary={run.summary} />}
    </>
  );
}

function Summary({ summary }: Readonly<{ summary: RunSummary }>) {
  const held = summary.waiting_for_sign_off;
  return (
    <>
      <h3>Summary</h3>
      <div className="summary">
        <p>
          {summary.approved} approved, {summary.declined} declined and{" "}
          {summary.referred} referred.
        </p>
        {held.length > 0 && (
          <p>
            Waiting for sign-off:{" "}
            <ClaimLinks
              claimIds={held.map((h) => h.claim_id)}
              notes={held.map((h) => money(h.payout))}
            />
          </p>
        )}
        <ClaimList
          title="Left for a handler"
          claimIds={summary.left_for_handler}
        />
        <ClaimList title="Still in progress" claimIds={summary.in_progress} />
        <ClaimList title="Not started" claimIds={summary.waiting} />
      </div>
    </>
  );
}

function ClaimList({
  title,
  claimIds,
}: Readonly<{ title: string; claimIds: string[] }>) {
  if (claimIds.length === 0) return null;
  return (
    <p>
      {title}: <ClaimLinks claimIds={claimIds} />
    </p>
  );
}
