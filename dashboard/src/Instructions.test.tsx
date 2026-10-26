import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Instructions } from "./Instructions";
import { stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the agent's instructions, read only", async () => {
  stubApi({
    "GET /api/instructions": { content: "# The UnderCover Agent\n\nDecide." },
  });
  render(<Instructions />);
  expect(await screen.findByText(/# The UnderCover Agent/)).toBeDefined();
  expect(screen.getByText(/Read only/)).toBeDefined();
  expect(screen.queryByRole("textbox")).toBeNull();
});

it("says when the instructions can't be loaded", async () => {
  stubApi({});
  render(<Instructions />);
  expect((await screen.findByRole("alert")).textContent).toMatch(
    /Couldn't load the instructions/,
  );
});
