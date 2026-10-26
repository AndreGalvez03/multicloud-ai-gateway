import { useEffect, useState } from "react";
import { compactTokens, percent, tone, usd } from "./format";
import type { DashboardSummary, TeamSummary } from "./types";

export function App() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/dashboard/summary")
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`platform returned HTTP ${response.status}`);
        }
        return (await response.json()) as DashboardSummary;
      })
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setData(payload);
        const hottest = [...payload.teams].sort(
          (a, b) => percent(b.spend_usd, b.usd_budget) - percent(a.spend_usd, a.usd_budget),
        )[0];
        setSelected(hottest?.id ?? null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "could not load usage");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const team = data?.teams.find((item) => item.id === selected) ?? null;
  const overBudget = data?.teams.filter((item) => percent(item.spend_usd, item.usd_budget) >= 80).length ?? 0;
  const rateLimits = data?.teams.reduce((sum, item) => sum + item.rate_limit_hits, 0) ?? 0;
  const spend = data?.teams.reduce((sum, item) => sum + item.spend_usd, 0) ?? 0;

  return (
    <div className="page">
      <header className="top">
        <div>
          <p className="eyebrow">Platform console</p>
          <h1>AI Gateway</h1>
        </div>
        <div className="meta">
          <span className="pill">local</span>
          <span>{data ? data.month : "—"}</span>
        </div>
      </header>

      {error && (
        <section className="banner">
          The dashboard could not read the platform API ({error}). Start it with <code>make up</code> and reload.
        </section>
      )}

      <section className="stats">
        <Stat label="Teams" value={String(data?.teams.length ?? "—")} detail="with a virtual key and a budget" />
        <Stat label="Spend this month" value={data ? usd(spend) : "—"} detail="incremental token charges" />
        <Stat label="Teams at 80%" value={String(overBudget)} detail="USD budget warning" />
        <Stat label="429s" value={String(rateLimits)} detail="rate-limit hits this month" />
      </section>

      <section className="layout">
        <div className="panel">
          <div className="panel-head">
            <h2>Teams</h2>
            <p>Token use and spend against the monthly budget.</p>
          </div>
          <table>
            <thead>
              <tr>
                <th>Team</th>
                <th>Residency</th>
                <th>Spend</th>
                <th>Tokens</th>
                <th>429s</th>
              </tr>
            </thead>
            <tbody>
              {data?.teams.map((item) => (
                <tr
                  key={item.id}
                  className={item.id === selected ? "selected" : undefined}
                  onClick={() => setSelected(item.id)}
                >
                  <td>
                    <button type="button" className="link" onClick={() => setSelected(item.id)}>
                      {item.name}
                    </button>
                    <span className="muted">{item.id}</span>
                  </td>
                  <td>{item.residency}</td>
                  <td>
                    <Bar used={item.spend_usd} budget={item.usd_budget} label={usd(item.spend_usd)} />
                  </td>
                  <td>
                    <Bar
                      used={item.tokens_used}
                      budget={item.token_budget}
                      label={compactTokens(item.tokens_used)}
                    />
                  </td>
                  <td>{item.rate_limit_hits}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {team && <TeamDetail team={team} />}
      </section>
      <footer>Illustrative prices. Grafana on port 3000 is the operational view of live latency, errors, and 429s.</footer>
    </div>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="stat">
      <p className="label">{label}</p>
      <p className="value">{value}</p>
      <p className="detail">{detail}</p>
    </article>
  );
}

function Bar({ used, budget, label }: { used: number; budget: number; label: string }) {
  const ratio = percent(used, budget);
  return (
    <div className="bar">
      <div className="bar-track">
        <div className={`bar-fill ${tone(ratio)}`} style={{ width: `${Math.min(ratio, 100)}%` }} />
      </div>
      <span>
        {label}
        <em>{ratio.toFixed(0)}%</em>
      </span>
    </div>
  );
}

function TeamDetail({ team }: { team: TeamSummary }) {
  const maxTokens = Math.max(...team.model_mix.map((row) => row.tokens), 1);
  return (
    <aside className="panel detail">
      <div className="panel-head">
        <h2>{team.name}</h2>
        <p>
          {team.residency} residency · {team.rpm_limit} rpm · {compactTokens(team.tpm_limit)} tpm ·{" "}
          {team.avg_latency_ms} ms average
        </p>
      </div>
      <dl className="facts">
        <div>
          <dt>Spend</dt>
          <dd>
            {usd(team.spend_usd)} / {usd(team.usd_budget)}
          </dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd>
            {compactTokens(team.tokens_used)} / {compactTokens(team.token_budget)}
          </dd>
        </div>
        <div>
          <dt>Guardrail blocks</dt>
          <dd>{team.guardrail_blocks}</dd>
        </div>
        <div>
          <dt>Errors</dt>
          <dd>{team.errors}</dd>
        </div>
      </dl>
      <h3>Model mix</h3>
      <ul className="mix">
        {team.model_mix.map((row) => (
          <li key={row.model}>
            <div className="mix-label">
              <strong>{row.model}</strong>
              <span>{row.provider}</span>
            </div>
            <div className="bar-track">
              <div className="bar-fill ok" style={{ width: `${(row.tokens / maxTokens) * 100}%` }} />
            </div>
            <span className="muted">
              {compactTokens(row.tokens)} · {usd(row.spend_usd)}
            </span>
          </li>
        ))}
        {team.model_mix.length === 0 && <li className="muted">No successful calls this month.</li>}
      </ul>
      <h3>Alerts</h3>
      <ul className="alerts">
        {team.alerts.map((alert) => (
          <li key={`${alert.metric}-${alert.threshold}`}>
            <span className={`pill ${alert.threshold === "100" ? "hot" : "warn"}`}>{alert.threshold}%</span>
            {alert.message}
          </li>
        ))}
        {team.alerts.length === 0 && <li className="muted">No budget alerts this month.</li>}
      </ul>
    </aside>
  );
}
