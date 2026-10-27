# Using coding assistants on this repo

Assistants (Cursor, Claude Code, Codex, and others) are part of how this codebase is written. They are useful when the task is specific and the result is reviewed. They are a liability when they are given secrets, customer prompts, or a blank cheque to invent infrastructure.

## What we give the assistant

- The files it needs, named. "The rate-limit window is `aigw/ratelimit.py`; denials must not consume the window" beats "make rate limiting better."
- The constraint that already exists: EU teams stay on EU or local models, money is `Decimal`, Terraform is validated and never applied.
- A test that should fail before the change and pass after it.

## What we do not give the assistant

- Cloud keys, database passwords, identity-provider tokens, or the contents of Secrets Manager.
- Customer prompts, completions, or a production usage export. Fixtures use obvious fake values.
- A request to disable a guardrail, a budget check, or secret scanning to "get the demo green."

Local compose values (`local-admin-token`, `local-vk-payments`, `aigw_local`) are fixtures for `make up`. They are documented in `.env.example` and allowlisted in `.gitleaks.toml` so the scanner can still catch a real key.

## What we do with the result

1. Read the diff. Reject code that logs prompt text, weakens residency, or adds a static cloud key.
2. Run the check that covers the change (`make test`, `make lint`, `terraform validate`, `shellcheck`).
3. Commit only what a reviewer could explain without the chat transcript.

`AGENTS.md` and `.cursor/rules/ai-development.mdc` are the same rules in the places an agent will read first.
