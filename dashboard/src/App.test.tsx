import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { DashboardSummary } from "./types";

const summary: DashboardSummary = {
  month: "2026-10",
  generated_at: "2026-10-26T12:00:00Z",
  teams: [
    {
      id: "payments",
      name: "Payments",
      residency: "eu",
      rpm_limit: 120,
      tpm_limit: 200000,
      tokens_used: 40000000,
      token_budget: 50000000,
      spend_usd: 9.5,
      usd_budget: 10.5,
      requests: 42000,
      rate_limit_hits: 18,
      guardrail_blocks: 3,
      errors: 1,
      error_rate: 0.01,
      avg_latency_ms: 40,
      model_mix: [{ model: "azure-gpt", provider: "azure", tokens: 40000000, spend_usd: 9.5 }],
      alerts: [],
    },
  ],
};

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a loading state and then the team", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => summary,
      }),
    );
    render(<App />);
    expect(screen.getByRole("status").textContent).toContain("Loading");
    expect(await screen.findByRole("button", { name: "Payments" })).toBeTruthy();
    expect(screen.getByText("2026-10-26 12:00 UTC")).toBeTruthy();
  });

  it("shows an error when the platform is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("offline");
    });
  });

  it("aborts the in-flight load when refresh is clicked again", async () => {
    const signals: AbortSignal[] = [];
    let releaseFirst: (() => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        const signal = init?.signal;
        if (signal) {
          signals.push(signal);
        }
        if (signals.length === 1) {
          return new Promise((resolve) => {
            releaseFirst = () => {
              resolve({ ok: true, json: async () => summary });
            };
          });
        }
        return Promise.resolve({
          ok: true,
          json: async () => summary,
        });
      }),
    );
    render(<App />);
    await waitFor(() => {
      expect(signals).toHaveLength(1);
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(signals).toHaveLength(2);
    });
    expect(signals[0]?.aborted).toBe(true);
    expect(signals[1]?.aborted).toBe(false);
    releaseFirst?.();
    expect(await screen.findByRole("button", { name: "Payments" })).toBeTruthy();
  });

  it("shows an empty state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ month: "2026-10", generated_at: "2026-10-26T12:00:00Z", teams: [] }),
      }),
    );
    render(<App />);
    expect(await screen.findByText(/No teams yet/)).toBeTruthy();
  });
});
