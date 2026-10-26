.PHONY: up down test lint smoke fmt tf-validate helm-lint screenshot pull-model

PYTHON ?= python3
VENV ?= .venv

up:
	docker compose up --build -d
	./scripts/healthcheck.sh

down:
	docker compose down

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check aigw tests services
	$(PYTHON) -m ruff format --check aigw tests services
	$(PYTHON) -m mypy
	shellcheck scripts/*.sh
	cd dashboard && npm run lint && npm test && npx tsc --noEmit

fmt:
	$(PYTHON) -m ruff format aigw tests services
	$(PYTHON) -m ruff check --fix aigw tests services
	terraform fmt -recursive infra/terraform

smoke:
	./scripts/smoke-test.sh

tf-validate:
	terraform -chdir=infra/terraform/aws init -backend=false
	terraform -chdir=infra/terraform/aws validate
	terraform -chdir=infra/terraform/gcp init -backend=false
	terraform -chdir=infra/terraform/gcp validate
	terraform -chdir=infra/terraform/azure init -backend=false
	terraform -chdir=infra/terraform/azure validate

helm-lint:
	helm lint deploy/helm/aigw
	helm template aigw deploy/helm/aigw | kubeconform -strict -summary -kubernetes-version 1.31.0 -

pull-model:
	docker compose exec ollama ollama pull llama3.2

screenshot:
	./scripts/screenshot.sh
