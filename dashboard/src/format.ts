export function usd(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value < 20 ? 2 : 0,
  });
}

export function compactTokens(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}k`;
  }
  return String(value);
}

export function percent(used: number, budget: number): number {
  if (budget <= 0) {
    return 0;
  }
  return Math.round((used / budget) * 1000) / 10;
}

export function tone(ratioPercent: number): "ok" | "warn" | "hot" {
  if (ratioPercent >= 100) {
    return "hot";
  }
  if (ratioPercent >= 80) {
    return "warn";
  }
  return "ok";
}
