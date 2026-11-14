import { generatePath } from "react-router";

export const QUEUE = "/";
export const INSTRUCTIONS = "/instructions";

// The route of a claim's page, and the link to one claim's page.
export const CLAIM_PAGE = "/claims/:claimId";
export const claimPage = (claimId: string) =>
  generatePath(CLAIM_PAGE, { claimId });

// The scoreboard, and the route of and link to one evaluation's page.
export const SCOREBOARD = "/scoreboard";
export const EVALUATION_PAGE = "/scoreboard/:runId";
export const evaluationPage = (runId: string) =>
  generatePath(EVALUATION_PAGE, { runId });
