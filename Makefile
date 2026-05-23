.PHONY: help test test-unit test-integration test-e2e test-smoke verify-% clean up down logs

help:  ## show this help
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

test:              ## run full test suite (unit + integration + e2e + smoke)
	scripts/run-tests.sh all

test-unit:         ## run unit tests only
	scripts/run-tests.sh unit

test-integration:  ## run integration tests (uses testcontainers)
	scripts/run-tests.sh integration

test-e2e:          ## run e2e tests (requires running stack)
	scripts/run-tests.sh e2e

test-smoke:        ## run bats smoke tests (requires running stack)
	scripts/run-tests.sh smoke

verify-%:          ## run phase verification script, e.g. `make verify-00`
	bash scripts/verify-phase-$*.sh

up:                ## bring up core stack (postgres only at this phase)
	docker compose up -d

down:              ## stop stack, keep data
	docker compose down

logs:              ## tail logs across all services
	docker compose logs -f

clean:             ## stop stack and wipe data volume (DESTRUCTIVE)
	docker compose down -v
