# Working on this repository

This file is the short version of [docs/ai-assisted-development.md](docs/ai-assisted-development.md). It applies to people and to coding agents.

- Read the surrounding module before editing it. Match the types, error shape, and naming that are already there.
- Review the diff yourself. An assistant draft is a proposal, not a commit.
- Run the check that covers the change: `pytest` for platform logic, `ruff` and `mypy` for Python, `npm test` for the dashboard, `shellcheck` for scripts, `terraform fmt -check` and `terraform validate` for Terraform. Terraform is never applied from this repo.
- Do not put secrets, customer prompts, or production usage exports into a prompt, a fixture, or a commit. Local tokens such as `local-admin-token` are compose fixtures, not credentials.
- Do not log prompt or completion text. Tests may use obvious fake values (`ada@example.com`).
- Prices live in `aigw/catalog.py`. Do not invent a "live" provider quote.
- Keep the EU residency rule intact: an `eu` team cannot be routed to a `us` model, including through a fallback.
- Prefer a small, tested change over a new subsystem.
