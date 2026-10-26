import { api, type Status } from "./api";
import {
  claimType,
  date,
  money,
  OUTCOME_LABELS,
  STATUS_LABELS,
} from "./format";
import { StatusBadge } from "./StatusBadge";
import { useData } from "./useData";

const STATUSES: Status[] = [
  "waiting",
  "in_progress",
  "awaiting_sign_off",
  "decided",
];

export function Queue() {
  const { data: claims, error } = useData(api.claims, 3000);

  if (error) return <p role="alert">Couldn't load the queue: {error}</p>;
  if (!claims) return <p>Loading the queue</p>;

  return (
    <>
      <h1>Claims queue</h1>
      <ul className="counts" aria-label="Claims by status">
        {STATUSES.map((status) => (
          <li key={status} className={`panel count count-${status}`}>
            <span className="count-number">
              {claims.filter((c) => c.status === status).length}
            </span>
            <span>{STATUS_LABELS[status]}</span>
          </li>
        ))}
      </ul>
      <div className="panel table-panel">
        <table>
          <thead>
            <tr>
              <th>Claim</th>
              <th>Customer</th>
              <th>Type</th>
              <th className="number">Claimed</th>
              <th>Submitted</th>
              <th>Status</th>
              <th>Decision</th>
              <th className="number">Payout</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim) => (
              <tr key={claim.claim_id}>
                <td>
                  <a className="mono" href={`#/claims/${claim.claim_id}`}>
                    {claim.claim_id}
                  </a>
                </td>
                <td>{claim.customer_name}</td>
                <td>{claimType(claim.claim_type)}</td>
                <td className="number">{money(claim.amount_claimed)}</td>
                <td>{date(claim.submitted_on)}</td>
                <td>
                  <StatusBadge status={claim.status} />
                </td>
                <td>{claim.decision && OUTCOME_LABELS[claim.decision]}</td>
                <td className="number">
                  {claim.payout !== null && money(claim.payout)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
