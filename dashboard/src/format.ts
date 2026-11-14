import type {
  DecisionKind,
  EvalSet,
  Measures,
  Run,
  RunStatus,
  Status,
} from "./api";

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

// Model calls cost fractions of a cent, so their costs show four decimal places.
const modelCosts = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
});

const day = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

const dayAndClock = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const clock = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

export function money(amount: number): string {
  return dollars.format(amount);
}

export function cost(amount: number): string {
  return modelCosts.format(amount);
}

export function duration(seconds: number): string {
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return minutes ? `${String(minutes)}m ${String(rest)}s` : `${String(rest)}s`;
}

export function percent(share: number): string {
  return `${String(Math.round(share * 100))}%`;
}

export interface MeasureColumn {
  name: string;
  format: (measures: Measures) => string;
}

// The scoreboard's measures, each with its label and format, in the order shown.
export const measureColumns: MeasureColumn[] = [
  { name: "Decision accuracy", format: (m) => percent(m.decision_accuracy) },
  { name: "Accuracy", format: (m) => percent(m.accuracy) },
  { name: "Cost of mistakes", format: (m) => money(m.cost_of_mistakes) },
  { name: "Straight through", format: (m) => percent(m.straight_through) },
  { name: "Model cost per claim", format: (m) => cost(m.cost_per_claim) },
  { name: "Time per claim", format: (m) => duration(m.seconds_per_claim) },
  {
    name: "Whole run",
    format: (m) =>
      m.run_seconds === null ? "Not finished" : duration(m.run_seconds),
  },
];

export function agentsAtOnce(agents: number): string {
  return `${String(agents)} ${agents === 1 ? "claim agent" : "claim agents"} at once`;
}

// An evaluation's set, such as "Held-out set, tiny claims".
export function setName(run: Run): string {
  const name = run.eval_set ? setLabels[run.eval_set] : "";
  return run.tiny ? `${name}, tiny claims` : name;
}

export function dateTime(isoTime: string): string {
  return dayAndClock.format(new Date(isoTime));
}

export function date(isoDate: string): string {
  return day.format(new Date(`${isoDate}T00:00:00Z`));
}

export function time(isoTime: string): string {
  return clock.format(new Date(isoTime));
}

export function label(code: string): string {
  const words = code.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const statusLabels: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  waiting_for_sign_off: "Waiting for sign-off",
  decided: "Decided",
  left_for_handler: "Left for a handler",
};

export const runLabels: Record<RunStatus, string> = {
  running: "Running",
  finished: "Finished",
  stopped: "Stopped",
};

export const setLabels: Record<EvalSet, string> = {
  evaluation: "Evaluation set",
  held_out: "Held-out set",
};

export const decisionLabels: Record<DecisionKind, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};

const addOnNames: Record<string, string> = {
  adventure_sports: "Adventure Sports",
  pre_existing_waiver: "Pre-Existing Condition Waiver",
  electronics_plus: "Electronics Plus",
};

export function addOnName(code: string): string {
  return addOnNames[code] ?? label(code);
}
