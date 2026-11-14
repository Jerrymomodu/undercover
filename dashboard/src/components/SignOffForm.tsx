import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../useLoad";
import { useSubmit } from "../useSubmit";

export function SignOffForm({
  claimId,
  onSignedOff,
}: Readonly<{ claimId: string; onSignedOff: () => void }>) {
  const { data: handlers } = useLoad(api.listHandlers);
  const [handlerId, setHandlerId] = useState("");
  const { submit, sending, error } = useSubmit(
    () => api.signOff(claimId, handlerId),
    onSignedOff,
    "Sign-off failed",
  );

  return (
    <form className="sign-off-form" onSubmit={submit}>
      <label>
        Handler
        <select
          value={handlerId}
          onChange={(event) => {
            setHandlerId(event.target.value);
          }}
        >
          <option value="" disabled>
            Choose a handler
          </option>
          {handlers
            ?.filter((handler) => handler.can_approve_over_limit)
            .map((handler) => (
              <option key={handler.handler_id} value={handler.handler_id}>
                {handler.name}
              </option>
            ))}
        </select>
      </label>
      <button type="submit" disabled={!handlerId || sending}>
        Sign off
      </button>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
