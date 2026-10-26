import type { Outcome, Status } from "./api";

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

export function money(amount: number): string {
  return dollars.format(amount);
}

export function date(isoDate: string): string {
  return new Date(`${isoDate.slice(0, 10)}T00:00:00Z`).toLocaleDateString(
    "en-US",
    { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" },
  );
}

export function claimType(type: string): string {
  const words = type.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const STATUS_LABELS: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  awaiting_sign_off: "Waiting for sign-off",
  decided: "Decided",
};

export const OUTCOME_LABELS: Record<Outcome, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};
