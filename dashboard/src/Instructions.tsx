import { api } from "./api";
import { useData } from "./useData";

export function Instructions() {
  const { data, error } = useData(api.instructions);

  if (error) return <p role="alert">Couldn't load the instructions: {error}</p>;
  if (!data) return <p>Loading the instructions</p>;

  return (
    <>
      <h1>Agent instructions</h1>
      <p className="muted">
        Read only. The agent reads these from the backend at the start of every
        run.
      </p>
      <pre className="panel instructions">{data.content}</pre>
    </>
  );
}
