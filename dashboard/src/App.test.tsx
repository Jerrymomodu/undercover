import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { stubApi, summary } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

it("shows the queue by default", async () => {
  stubApi({ "GET /api/claims": [summary({})] });
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Claims queue" }),
  ).toBeDefined();
  expect(
    screen.getByRole("link", { name: "Queue" }).getAttribute("aria-current"),
  ).toBe("page");
});

it("moves between pages as the hash changes", async () => {
  stubApi({
    "GET /api/claims": [summary({})],
    "GET /api/instructions": { content: "Decide claims." },
  });
  render(<App />);
  await screen.findByRole("heading", { name: "Claims queue" });

  act(() => {
    window.location.hash = "#/instructions";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  expect(await screen.findByText("Decide claims.")).toBeDefined();
  expect(
    screen
      .getByRole("link", { name: "Agent instructions" })
      .getAttribute("aria-current"),
  ).toBe("page");

  act(() => {
    window.location.hash = "#/claims/CLM-1001";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  expect((await screen.findByRole("alert")).textContent).toMatch(
    /^Couldn't load CLM-1001/,
  );
});
