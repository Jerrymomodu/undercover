import { api, type Run } from "../api";
import { time } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";
import { TodoChip } from "./Chips";
import { Message } from "./Message";

export function RunPanel() {
  const { data: run, error } = useLoad(api.getCurrentRun, REFRESH_MS);

  return (
    <section className="panel run" aria-labelledby="run-title">
      {run === undefined && (
        <>
          <h2 id="run-title">This run</h2>
          <Message error={error} />
        </>
      )}
      {run === null && (
        <>
          <h2 id="run-title">This run</h2>
          <p className="muted">
            No run yet. The agent's to-do list appears here when a run starts.
          </p>
        </>
      )}
      {run && <RunDetails run={run} />}
    </section>
  );
}

function RunDetails({ run }: Readonly<{ run: Run }>) {
  const finished = run.finished_at !== null;
  return (
    <>
      <div className="run-heading">
        <h2 id="run-title">This run</h2>
        <span
          className={`chip ${finished ? "status-decided" : "status-in_progress"}`}
        >
          {finished ? "Finished" : "Running"}
        </span>
        <span className="small muted">
          Started {time(run.started_at)},{" "}
          {run.cap === null ? "whole queue" : `up to ${String(run.cap)} claims`}
        </span>
      </div>
      {run.todos.length === 0 ? (
        <p className="muted">The agent hasn't written its to-do list yet.</p>
      ) : (
        <ol className="todos" aria-label="To-do list">
          {run.todos.map((todo, index) => (
            <li key={`${String(index)}-${todo.content}`}>
              <TodoChip status={todo.status} />
              <span>{todo.content}</span>
            </li>
          ))}
        </ol>
      )}
      {run.summary && <p className="summary">{run.summary}</p>}
    </>
  );
}
