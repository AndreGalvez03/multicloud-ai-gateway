"""Operator CLI: `aigw usage`, `aigw cost`, `aigw models`, `aigw health`."""

from __future__ import annotations

import os
from typing import Any

import httpx
import typer

from aigw.reports import format_usage

app = typer.Typer(add_completion=False, no_args_is_help=True, help="AI Gateway operator CLI.")


def _base_url() -> str:
    return os.environ.get("AIGW_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def _admin_token() -> str:
    return os.environ.get("AIGW_ADMIN_TOKEN", "local-admin-token")


def fetch_json(path: str, *, admin: bool = True) -> Any:
    headers = {}
    if admin:
        headers["Authorization"] = f"Bearer {_admin_token()}"
    with httpx.Client(timeout=10.0) as client:
        response = client.get(f"{_base_url()}{path}", headers=headers)
    if response.status_code >= 400:
        typer.echo(f"request failed: HTTP {response.status_code} {response.text}", err=True)
        raise typer.Exit(code=1)
    return response.json()


@app.command()
def health() -> None:
    """Check the platform health endpoint."""
    payload = fetch_json("/healthz", admin=False)
    typer.echo(f"status={payload.get('status')} service={payload.get('service')}")


@app.command()
def models() -> None:
    """List models, providers, regions, and illustrative prices."""
    payload = fetch_json("/v1/models")
    for spec in payload["models"]:
        typer.echo(
            f"{spec['name']:<16} {spec['provider']:<10} {spec['region']:<6} "
            f"in ${spec['input_per_mtok']}/MTok  out ${spec['output_per_mtok']}/MTok  "
            f"{spec['kind']}"
        )


@app.command()
def usage(team: str = typer.Option(..., "--team", help="Team id.")) -> None:
    """Print the current month of usage and spend for a team."""
    payload = fetch_json(f"/v1/teams/{team}/usage")
    typer.echo(format_usage(payload))


@app.command()
def cost(team: str = typer.Option(..., "--team", help="Team id.")) -> None:
    """Print incremental spend and any provisioned-throughput commitment."""
    payload = fetch_json(f"/v1/teams/{team}/usage")
    typer.echo(
        f"{team} {payload['month']}: incremental ${float(payload['incremental_usd']):,.4f}  "
        f"commitment ${float(payload['commitment_usd']):,.2f}  "
        f"total ${float(payload['total_usd']):,.4f}"
    )
    provisioned = payload.get("provisioned_models") or []
    if provisioned:
        typer.echo("provisioned models: " + ", ".join(provisioned))


@app.command()
def alerts(team: str = typer.Option(..., "--team", help="Team id.")) -> None:
    """List budget alerts for a team in the current month."""
    payload = fetch_json(f"/v1/teams/{team}/alerts")
    rows = payload.get("alerts") or []
    if not rows:
        typer.echo(f"{team}: no alerts this month")
        return
    for row in rows:
        typer.echo(f"{row['threshold']}% {row['metric']}: {row['message']}")


if __name__ == "__main__":
    app()
