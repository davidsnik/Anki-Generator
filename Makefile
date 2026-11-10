# Everyday commands. Complex desktop assembly stays in the packaging scripts.
.DEFAULT_GOAL := help
SHELL := /bin/bash
.SHELLFLAGS := -e -o pipefail -c

UV ?= uv
PNPM ?= pnpm
NODE ?= node
export UV PNPM NODE
TOOLCHAIN = source ./scripts/toolchain.sh;

PYTEST_ARGS ?=
ARGS ?=
PACKAGE_ARGS ?=
FROZEN_BACKEND ?= $(ANKI_TEST_FROZEN_BACKEND)
APPIMAGE ?=
UNPACKED ?= $(CURDIR)/dist/desktop/linux-unpacked

.PHONY: help setup setup-browser dev dev-browser run run-browser test test-backend test-frontend \
	test-desktop test-browser test-e2e test-anki test-frozen test-packaged lint \
	format format-check typecheck check build build-web package clean doctor
.PHONY: benchmark benchmark-smoke benchmark-report benchmark-engineering eval

help: ## Show everyday commands and release checks (default)
	@awk 'BEGIN {FS = ":.*## "; print "Anki Generator development\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-19s %s\n", $$1, $$2} END {print "\nGuide: docs/development.md. Overrides: UV, PNPM, NODE; options: ARGS, PYTEST_ARGS, PACKAGE_ARGS."}' $(MAKEFILE_LIST)

setup: ## Synchronize locked Python, frontend and Electron dependencies
	@./scripts/workflow.sh setup

setup-browser: ## Synchronize Python/frontend dependencies without downloading Electron
	@./scripts/workflow.sh setup-browser

dev: ## Launch the desktop app with frontend hot reload
	@./scripts/dev-desktop.sh --hmr $(ARGS)

dev-browser: ## Develop in a browser with Python and frontend live reload
	@./dev.sh $(ARGS)

run: ## Launch the unpacked desktop application produced by make build
	@./scripts/workflow.sh run $(ARGS)

run-browser: ## Launch the production browser interface (legacy run.sh)
	@./run.sh $(ARGS)

test: test-backend test-frontend test-desktop ## Run Python, frontend and desktop-shell unit tests

test-backend: ## Run offline Python tests (PYTEST_ARGS selects a subset)
	@$(TOOLCHAIN) "$(UV)" run --locked pytest $(PYTEST_ARGS)

test-frontend: ## Run frontend component and interaction tests
	@$(TOOLCHAIN) "$(PNPM)" --dir frontend test

test-desktop: ## Run desktop-shell lifecycle and security unit tests
	@$(TOOLCHAIN) "$(PNPM)" --dir desktop test

test-browser: build-web ## Build and run browser workflows against an isolated offline test host
	@$(TOOLCHAIN) "$(UV)" run --locked python scripts/browser-tests.py $(ARGS)

test-e2e: test-browser ## Alias for test-browser

test-anki: ## Run official Anki core tests in disposable collections
	@$(TOOLCHAIN) "$(UV)" run --locked --extra anki-integration pytest tests/integration/test_anki_roundtrip.py $(PYTEST_ARGS)

test-frozen: ## Test a copied backend outside the checkout (FROZEN_BACKEND=/path/to/executable)
	@test -n "$(FROZEN_BACKEND)" || { echo 'Set FROZEN_BACKEND to the copied executable outside the checkout.' >&2; exit 2; }
	@$(TOOLCHAIN) ANKI_TEST_FROZEN_BACKEND="$(FROZEN_BACKEND)" "$(UV)" run --locked pytest tests/test_frozen_desktop.py $(PYTEST_ARGS)

test-packaged: ## Run copied AppImage GUI checks (APPIMAGE=/outside/checkout/app.AppImage)
	@test -n "$(APPIMAGE)" || { echo 'Set APPIMAGE to a copied release outside the checkout; a graphical session is required.' >&2; exit 2; }
	@$(TOOLCHAIN) "$(NODE)" tests/desktop/launch-smoke.cjs "$(APPIMAGE)"
	@$(TOOLCHAIN) "$(NODE)" tests/desktop/workflow.cjs "$(APPIMAGE)"
	@$(TOOLCHAIN) "$(NODE)" tests/desktop/lifecycle.cjs "$(APPIMAGE)" "$(UNPACKED)"
	@$(TOOLCHAIN) "$(NODE)" tests/desktop/unsaved-close.cjs "$(APPIMAGE)"

lint: ## Check Python lint and shell syntax
	@$(TOOLCHAIN) "$(UV)" run --locked ruff check .
	@for script in install.sh run.sh dev.sh scripts/*.sh; do bash -n "$$script"; done

format: ## Format Python, frontend and desktop-shell sources
	@$(TOOLCHAIN) "$(UV)" run --locked ruff format .
	@$(TOOLCHAIN) "$(PNPM)" --dir frontend run format
	@$(TOOLCHAIN) "$(PNPM)" --dir frontend exec prettier --write '../desktop/**/*.{cjs,js,json,html,css}' '../tests/desktop/*.cjs'

format-check: ## Check formatting without changing sources
	@$(TOOLCHAIN) "$(UV)" run --locked ruff format --check .
	@$(TOOLCHAIN) "$(PNPM)" --dir frontend run format:check
	@$(TOOLCHAIN) "$(PNPM)" --dir frontend exec prettier --check '../desktop/**/*.{cjs,js,json,html,css}' '../tests/desktop/*.cjs'

typecheck: ## Check strict frontend TypeScript without producing build files
	@$(TOOLCHAIN) "$(PNPM)" --dir frontend exec tsc --noEmit

check: lint format-check typecheck test ## Run non-mutating source checks and all unit tests

build: ## Build a runnable desktop directory, including the frozen backend
	@./scripts/build-desktop.sh --dir $(PACKAGE_ARGS)

build-web: ## Build React and copy production assets into the Python package
	@./scripts/workflow.sh build-web

package: ## Build checked AppImage and Fedora RPM releases (PACKAGE_ARGS accepts build options)
	@./scripts/build-desktop.sh $(PACKAGE_ARGS)

clean: ## Remove generated outputs; preserve user data and development dependencies
	@./scripts/workflow.sh clean

doctor: ## Check required tools and explain optional Fedora/desktop dependencies
	@./scripts/workflow.sh doctor $(ARGS)

benchmark: ## Opt-in developer dataset/experiment tools (ARGS='--help' by default)
	@$(TOOLCHAIN) "$(UV)" run --locked anki-generator benchmark $(if $(strip $(ARGS)),$(ARGS),--help)

eval: benchmark ## Alias for developer benchmark commands; no GUI or paid default

benchmark-smoke: ## Exercise synthetic inventory/extraction/reporting without API calls
	@$(TOOLCHAIN) "$(UV)" run --locked anki-generator benchmark smoke $(ARGS)

benchmark-report: ## Generate a private standalone report (ARGS='<result.json> --output <report.md>')
	@$(TOOLCHAIN) "$(UV)" run --locked anki-generator benchmark report $(ARGS)

benchmark-engineering: ## Measure offline synthetic math/vector-cache controls (ARGS='--output <path>')
	@$(TOOLCHAIN) "$(UV)" run --locked anki-generator benchmark engineering $(ARGS)
