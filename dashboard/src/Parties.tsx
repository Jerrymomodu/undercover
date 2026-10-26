import { useCallback } from "react";
import { api } from "./api";
import { claimType, date, money } from "./format";
import { useData } from "./useData";

export function PolicyPanel({ policyId }: Readonly<{ policyId: string }>) {
  const load = useCallback(() => api.policy(policyId), [policyId]);
  const { data: policy } = useData(load);

  return (
    <section className="panel" aria-labelledby="policy-heading">
      <h2 id="policy-heading">Policy</h2>
      {policy && (
        <dl className="facts">
          <dt>Policy</dt>
          <dd className="mono">{policy.policy_id}</dd>
          <dt>Plan</dt>
          <dd>{policy.plan.name}</dd>
          <dt>Add-ons</dt>
          <dd>{policy.add_ons.map((a) => a.name).join(", ") || "None"}</dd>
          <dt>Trip</dt>
          <dd>
            {policy.trip.destination}, {date(policy.trip.departs_on)} to{" "}
            {date(policy.trip.returns_on)}
          </dd>
          <dt>Trip cost</dt>
          <dd className="number">{money(policy.trip.trip_cost)}</dd>
          <dt>Travelers</dt>
          <dd>{policy.travelers.join(", ")}</dd>
          <dt>Bought</dt>
          <dd>{date(policy.purchased_on)}</dd>
        </dl>
      )}
    </section>
  );
}

export function CustomerPanel({
  customerId,
}: Readonly<{ customerId: string }>) {
  const load = useCallback(() => api.customer(customerId), [customerId]);
  const { data: customer } = useData(load);

  return (
    <section className="panel" aria-labelledby="customer-heading">
      <h2 id="customer-heading">Customer</h2>
      {customer && (
        <>
          <dl className="facts">
            <dt>Name</dt>
            <dd>{customer.name}</dd>
            <dt>Email</dt>
            <dd>{customer.email}</dd>
            <dt>Phone</dt>
            <dd>{customer.phone}</dd>
            <dt>Customer since</dt>
            <dd>{date(customer.customer_since)}</dd>
          </dl>
          <h3>Earlier claims</h3>
          {customer.previous_claims.length === 0 ? (
            <p className="muted">None.</p>
          ) : (
            <ul className="history">
              {customer.previous_claims.map((c) => (
                <li key={c.claim_id}>
                  <span className="mono">{c.claim_id}</span>{" "}
                  {`${date(c.filed_on)}, ${claimType(c.claim_type)}: ${c.summary}. `}
                  {c.outcome === "approved"
                    ? `Paid ${money(c.amount_paid)}.`
                    : "Declined."}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
