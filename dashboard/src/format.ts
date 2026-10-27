export function usd(value: number): string {
  if (!Number.isFinite(value)) {
    return "$0.00";
  }
  const abs = Math.abs(value);
  if (abs >= 1000) {
    return value.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    });
  }
  if (abs > 0 && abs < 0.01) {
    return value.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 6,
    });
  }
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function compactTokens(value: number): string {
  if (value >= 999_950) {
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
