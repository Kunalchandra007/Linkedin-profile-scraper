# LinkedIn Profile API — common commands.
# On Windows without `make`, run the underlying commands shown here directly,
# or use Git Bash / WSL. See README "Setup" for Windows/PowerShell equivalents.

.DEFAULT_GOAL := help
PY ?= python

.PHONY: help install install-scraper run worker login smoke test lint fmt \
        fixtures docker-build docker-up docker-down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	 awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install the app + dev dependencies (editable)
	$(PY) -m pip install -e ".[dev]"

install-scraper: ## Install the optional Playwright scraper + browser
	$(PY) -m pip install -e ".[scraper]"
	$(PY) -m playwright install --with-deps chromium

run: ## Run the API locally (http://localhost:8000, includes inline worker)
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker: ## Run a standalone job worker (set RUN_INLINE_WORKER=false in .env first)
	$(PY) -m app.worker

login: ## Launch a headed browser to log into LinkedIn and save session state
	$(PY) -m scripts.login

smoke: ## Manual live smoke test against real LinkedIn (NOT for CI)
	$(PY) -m scripts.smoke_live $(URL)

test: ## Run the test suite (no live LinkedIn, no credentials needed)
	$(PY) -m pytest

lint: ## Lint with ruff
	$(PY) -m ruff check .

fmt: ## Auto-format + fix with ruff
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

fixtures: ## Regenerate the mock/fixture profile JSON in tests/fixtures
	$(PY) -m scripts.make_fixtures

docker-build: ## Build the Docker image
	docker compose build

docker-up: ## Start the API in Docker (http://localhost:8000)
	docker compose up

docker-down: ## Stop and remove Docker containers
	docker compose down

clean: ## Remove caches and local runtime data
	$(PY) -c "import shutil,glob,os; [shutil.rmtree(p,ignore_errors=True) for p in ['.pytest_cache','.ruff_cache','data','build','dist']]; [shutil.rmtree(p,ignore_errors=True) for p in glob.glob('**/__pycache__',recursive=True)]"
