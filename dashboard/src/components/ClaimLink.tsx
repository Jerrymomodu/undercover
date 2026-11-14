import { Fragment } from "react";
import { Link } from "react-router";
import { claimPage } from "../paths";

export function ClaimLink({ claimId }: Readonly<{ claimId: string }>) {
  return (
    <Link className="mono" to={claimPage(claimId)}>
      {claimId}
    </Link>
  );
}

// Claims named in a sentence, each linked to its page, with commas between, and
// each followed by its note, such as an amount, when notes are given.
export function ClaimLinks({
  claimIds,
  notes,
}: Readonly<{ claimIds: string[]; notes?: string[] }>) {
  return claimIds.map((claimId, index) => (
    <Fragment key={claimId}>
      {index > 0 && ", "}
      <ClaimLink claimId={claimId} />
      {notes && <span className="mono"> {notes[index]}</span>}
    </Fragment>
  ));
}
