# Contributing

Issues and pull requests are welcome. Please keep the change small enough that the diff explains itself.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd dashboard && npm ci && cd ..
```

Docker is only required for `make up`. Unit tests use sqlite and an in-process mock.

## Checks

```bash
make test          # pytest
make lint          # ruff, mypy, shellcheck, eslint, vitest, tsc
make tf-validate   # terraform fmt is separate; this inits with -backend=false and validates
make helm-lint
```

`terraform apply` is out of scope. Do not add a workflow job that plans against a live account.

## Secrets

Do not commit cloud keys, `.env`, or a Terraform state file. `.env.example` holds the local fixtures. If a change needs a credential, document the IAM role or the secret manager path instead of a value. gitleaks runs in CI.

## Tests that should move with the code

- Budget math and the worked example in `docs/cost-model.md` (`tests/test_pricing.py`).
- The 60-second rate-limit window (`tests/test_ratelimit.py`).
- Redaction and blocked topics (`tests/test_guardrails.py`).
- EU models cannot be a US fallback (`tests/test_routing.py` and the API tests).

## Assistants

If a coding assistant wrote part of the change, you still own the diff. Read [docs/ai-assisted-development.md](docs/ai-assisted-development.md) before you paste this repo, or any data from it, into a prompt.
