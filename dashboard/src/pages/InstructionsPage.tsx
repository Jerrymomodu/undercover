import { api } from "../api";
import { Message } from "../components/Message";
import { useLoad } from "../useLoad";

export function InstructionsPage() {
  const { data, error } = useLoad(api.getInstructions);

  return (
    <>
      <h1>Agent instructions</h1>
      <p className="lead">
        What the agent reads before it starts: its instructions for running the
        queue, and for working each claim. It looks up the policy wording and
        the claims manual as it needs them. This page is read only.
      </p>
      {data ? (
        <>
          <section className="panel" aria-labelledby="queue-title">
            <h2 id="queue-title">Running the queue</h2>
            <pre className="instructions">{data.queue}</pre>
          </section>
          <section className="panel" aria-labelledby="claim-title">
            <h2 id="claim-title">Working a claim</h2>
            <pre className="instructions">{data.claim}</pre>
          </section>
        </>
      ) : (
        <section className="panel">
          <Message error={error} />
        </section>
      )}
    </>
  );
}
