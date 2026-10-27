import { compactTokens, percent, tone, usd } from "./format";
import { describe, expect, it } from "vitest";

describe("formatters", () => {
  it("renders dollars and token counts", () => {
    expect(usd(10.5)).toBe("$10.50");
    expect(usd(80)).toBe("$80.00");
    expect(usd(0.0042)).toBe("$0.0042");
    expect(usd(1500)).toBe("$1,500");
    expect(compactTokens(32_000_000)).toBe("32.0M");
    expect(compactTokens(999_950)).toBe("1.0M");
    expect(compactTokens(1500)).toBe("1.5k");
  });

  it("caps the warning tone at the budget thresholds", () => {
    expect(percent(8, 10)).toBe(80);
    expect(tone(79.9)).toBe("ok");
    expect(tone(80)).toBe("warn");
    expect(tone(100)).toBe("hot");
  });
});
