import { useCallback, useState } from "react";
import { api, type Claim } from "./api";
import { DecisionPanel } from "./DecisionPanel";
import { claimType, date, money } from "./format";
import { CustomerPanel, PolicyPanel } from "./Parties";
import { StatusBadge } from "./StatusBadge";
import { Steps } from "./Steps";
import { useData } from "./useData";

const WORKING_REFRESH_MS = 1000;
const IDLE_REFRESH_MS = 3000;

function ClaimDetails({ claim }: Readonly<{ claim: Claim }>) {
  return (
    <>
      <section className="panel" aria-labelledby="story-heading">
        <h2 id="story-heading">The claim</h2>
        <dl className="facts">
          <dt>Type</dt>
          <dd>{claimType(claim.claim_type)}</dd>
          <dt>Incident</dt>
          <dd>
            {date(claim.incident_date)}, {claim.incident_location}
          </dd>
          <dt>Submitted</dt>
          <dd>{date(claim.submitted_on)}</dd>
        </dl>
        <p className="story">{claim.story}</p>
      </section>

      <section className="panel" aria-labelledby="items-heading">
        <h2 id="items-heading">Items claimed</h2>
        <table className="items">
          <thead>
            <tr>
              <th>Item</th>
              <th>Category</th>
              <th className="number">Amount</th>
            </tr>
          </thead>
          <tbody>
            {claim.items.map((item) => (
              <tr key={item.description}>
                <td>{item.description}</td>
                <td>{item.category}</td>
                <td className="number">{money(item.amount)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={2}>Total claimed</th>
              <td className="number">{money(claim.amount_claimed)}</td>
            </tr>
          </tfoot>
        </table>
      </section>

      <section className="panel" aria-labelledby="documents-heading">
        <h2 id="documents-heading">Documents</h2>
        {claim.documents.map((doc) => (
          <article key={doc.name} className="document">
            <h3>{doc.name}</h3>
            <p>{doc.content}</p>
          </article>
        ))}
      </section>
    </>
  );
}

export function ClaimPage({ claimId }: Readonly<{ claimId: string }>) {
  const load = useCallback(
    () => Promise.all([api.claim(claimId), api.steps(claimId)]),
    [claimId],
  );
  const [refreshMs, setRefreshMs] = useState(IDLE_REFRESH_MS);
  const { data, error, refresh } = useData(load, refreshMs);
  const [runError, setRunError] = useState<string | null>(null);

  if (error)
    return (
      <p role="alert">
        Couldn't load {claimId}: {error}
      </p>
    );
  if (!data) return <p>Loading {claimId}</p>;

  const [claim, steps] = data;
  const working = claim.status === "in_progress";
  const wantedMs = working ? WORKING_REFRESH_MS : IDLE_REFRESH_MS;
  if (wantedMs !== refreshMs) setRefreshMs(wantedMs);

  const runAgent = () => {
    setRunError(null);
    api.runAgent(claimId).then(
      () => void refresh(),
      (e: unknown) => {
        setRunError(e instanceof Error ? e.message : String(e));
      },
    );
  };

  return (
    <>
      <p>
        <a href="#/">Back to the queue</a>
      </p>
      <div className="claim-heading">
        <h1 className="mono">{claim.claim_id}</h1>
        <StatusBadge status={claim.status} />
        {claim.status === "waiting" && (
          <button type="button" onClick={runAgent}>
            Run the agent
          </button>
        )}
      </div>
      <p className="summary">{claim.summary}</p>
      {runError && <p role="alert">{runError}</p>}

      <div className="claim-grid">
        <div className="column">
          <DecisionPanel claim={claim} onChange={() => void refresh()} />
          <Steps steps={steps} working={working} />
          <ClaimDetails claim={claim} />
        </div>
        <div className="column">
          <PolicyPanel policyId={claim.policy_id} />
          <CustomerPanel customerId={claim.customer_id} />
        </div>
      </div>
    </>
  );
}
