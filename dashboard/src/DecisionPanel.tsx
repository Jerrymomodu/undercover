import { useState } from "react";
import { api, type Claim } from "./api";
import { date, money, OUTCOME_LABELS } from "./format";
import { useData } from "./useData";

function SignOffForm({
  claim,
  onSignedOff,
}: Readonly<{ claim: Claim; onSignedOff: () => void }>) {
  const { data: handlers } = useData(api.handlers);
  const [handlerId, setHandlerId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const payout = claim.decision?.payout ?? 0;
  const signers = handlers?.filter((h) => h.can_approve_over_limit) ?? [];

  const signOff = () => {
    api.signOff(claim.claim_id, handlerId).then(onSignedOff, (e: unknown) => {
      setError(e instanceof Error ? e.message : String(e));
    });
  };

  return (
    <div className="sign-off">
      <p>
        A payout over $1,000.00 needs a handler's sign-off. The payment waits
        until then.
      </p>
      <label htmlFor="handler">Handler</label>
      <div className="sign-off-row">
        <select
          id="handler"
          value={handlerId}
          onChange={(e) => {
            setHandlerId(e.target.value);
          }}
        >
          <option value="">Choose a handler</option>
          {signers.map((h) => (
            <option key={h.handler_id} value={h.handler_id}>
              {h.name}
            </option>
          ))}
        </select>
        <button type="button" disabled={!handlerId} onClick={signOff}>
          Sign off and pay {money(payout)}
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

function PaymentLine({ claim }: Readonly<{ claim: Claim }>) {
  if (claim.payment) {
    return (
      <p className="payment">
        Paid {money(claim.payment.amount)} on {date(claim.payment.paid_at)}
        {claim.sign_off && `, signed off by ${claim.sign_off.handler_name}`}.
      </p>
    );
  }
  return <p className="payment">Not paid yet.</p>;
}

export function DecisionPanel({
  claim,
  onChange,
}: Readonly<{ claim: Claim; onChange: () => void }>) {
  const decision = claim.decision;
  return (
    <section className="panel" aria-labelledby="decision-heading">
      <h2 id="decision-heading">Decision</h2>
      {decision ? (
        <>
          <p className={`outcome outcome-${decision.decision}`}>
            {OUTCOME_LABELS[decision.decision]}
            {decision.decision === "approve" && (
              <span className="number"> {money(decision.payout)}</span>
            )}
          </p>
          <p>{decision.reason}</p>
          <p className="muted">Policy section: {decision.policy_section}</p>
          {claim.status === "awaiting_sign_off" && (
            <SignOffForm claim={claim} onSignedOff={onChange} />
          )}
          {claim.status === "decided" && decision.decision === "approve" && (
            <PaymentLine claim={claim} />
          )}
        </>
      ) : (
        <p className="muted">No decision yet.</p>
      )}
    </section>
  );
}
