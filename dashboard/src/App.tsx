import { useCallback, useEffect, useState } from "react";
import { compactTokens, percent, tone, usd } from "./format";
import type { DashboardSummary, TeamSummary } from "./types";

export function App() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
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
        setSelected((current) => {
          if (current && payload.teams.some((team) => team.id === current)) {
            return current;
          }
          const hottest = [...payload.teams].sort(
            (a, b) => Math.max(percent(b.spend_usd, b.usd_budget), percent(b.tokens_used, b.token_budget))
              - Math.max(percent(a.spend_usd, a.usd_budget), percent(a.tokens_used, a.token_budget)),
          )[0];
          return hottest?.id ?? null;
        });
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setData(null);
          setError(reason instanceof Error ? reason.message : "could not load usage");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => load(), [load]);

  const team = data?.teams.find((item) => item.id === selected) ?? null;
  const warningTeams = data?.teams.filter((item) => (
    percent(item.spend_usd, item.usd_budget) >= 80 || percent(item.tokens_used, item.token_budget) >= 80
  )).length ?? 0;
  const rateLimits = data?.teams.reduce((sum, item) => sum + item.rate_limit_hits, 0) ?? 0;
  const spend = data?.teams.reduce((sum, item) => sum + item.spend_usd, 0) ?? 0;
  const requests = data?.teams.reduce((sum, item) => sum + item.requests, 0) ?? 0;
  const errors = data?.teams.reduce((sum, item) => sum + item.errors, 0) ?? 0;
  const attempts = requests + errors + rateLimits;
  const errorRate = attempts === 0 ? 0 : errors / attempts;

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
          {data && <time dateTime={data.generated_at}>{data.generated_at.slice(0, 16).replace("T", " ")} UTC</time>}
          <button type="button" className="refresh" onClick={() => load()}>Refresh</button>
        </div>
      </header>

      {loading && !data && <p className="banner" role="status">Loading this month's usage.</p>}
      {error && (
        <section className="banner" role="alert">
          The dashboard could not read the platform API ({error}). Start it with <code>make up</code> and reload.
        </section>
      )}
      {data && data.teams.length === 0 && (
        <p className="banner" role="status">No teams yet. Create one with the admin API.</p>
      )}

      <section className="stats" aria-label="Month totals">
        <Stat label="Teams" value={data ? String(data.teams.length) : "—"} detail="with a virtual key and a budget" />
        <Stat label="Spend this month" value={data ? usd(spend) : "—"} detail="incremental token charges" />
        <Stat label="Teams at 80%" value={data ? String(warningTeams) : "—"} detail="token or USD budget" />
        <Stat label="Error rate" value={data ? `${(errorRate * 100).toFixed(1)}%` : "—"} detail={`${requests} successful requests`} />
        <Stat label="429s" value={data ? String(rateLimits) : "—"} detail="rate-limit hits this month" />
      </section>

      <section className="layout">
        <div className="panel">
          <div className="panel-head">
            <h2>Teams</h2>
            <p>Token use and spend against the monthly budget.</p>
          </div>
          <div className="table-scroll">
            <table>
              <caption className="sr-only">Teams, residency, spend, tokens, and rate-limit hits</caption>
              <thead>
                <tr>
                  <th scope="col">Team</th>
                  <th scope="col">Residency</th>
                  <th scope="col">Spend</th>
                  <th scope="col">Tokens</th>
                  <th scope="col">429s</th>
                </tr>
              </thead>
              <tbody>
                {data?.teams.map((item) => (
                  <tr key={item.id} className={item.id === selected ? "selected" : undefined}>
                    <td>
                      <button
                        type="button"
                        className="link"
                        aria-pressed={item.id === selected}
                        onClick={() => setSelected(item.id)}
                      >
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
      <p className="stat-detail">{detail}</p>
    </article>
  );
}

function Bar({ used, budget, label }: { used: number; budget: number; label: string }) {
  const ratio = percent(used, budget);
  return (
    <div className="bar">
      <div
        className="bar-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.min(Math.round(ratio), 100)}
        aria-label={label}
      >
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
    <aside className="panel team-detail">
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
          <dt>Requests</dt>
          <dd>{team.requests}</dd>
        </div>
        <div>
          <dt>Error rate</dt>
          <dd>{(team.error_rate * 100).toFixed(1)}%</dd>
        </div>
        <div>
          <dt>Guardrail blocks</dt>
          <dd>{team.guardrail_blocks}</dd>
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
              <div className="bar-fill mix" style={{ width: `${(row.tokens / maxTokens) * 100}%` }} />
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
