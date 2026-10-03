# From Prompt to Payload

.PHONY: help provision lab test verify score corpus bundle check clean

help:
	@echo "  make provision   phase 1: build lab, interposer, config (needs network once)"
	@echo "  make lab         build and verify the RE target only"
	@echo "  make test        agent loop + egress guard + lab bugs (no model, no network)"
	@echo "  make verify      everything in 'test' plus full egress verification"
	@echo "  make corpus      embed corpus/notes into the retrieval store"
	@echo "  make bundle      portable bundle for an air-gapped host"
	@echo "  make score       score your model against the lab target"
	@echo "  make check       confirm the environment is working"
	@echo "  make clean       remove build artifacts and run output"

provision:
	./provision/provision.sh

lab:
	$(MAKE) -C lab/re-target all
	./lab/re-target/verify.sh

test: lab
	@echo
	@cd harness && python3 tests/test_agent.py
	@echo
	@cd harness && python3 tests/test_egress.py
	@echo
	@cd harness && python3 tests/test_score.py

verify: test
	@echo
	./scripts/egress-test.sh

corpus:
	cd harness && python3 -m payload corpus build ../corpus/notes --name local-notes
	cd harness && python3 -m payload corpus stats

bundle:
	./provision/bundle.sh --tar

score: lab
	cd harness && python3 -m payload score --runs $${RUNS:-1}

# Run after any toolchain change: a compiler or SDK update can quietly mitigate
# one of the lab bugs, and then a score means nothing.
check:
	@echo "== lab target"
	@./lab/re-target/verify.sh
	@echo
	@echo "== harness"
	@cd harness && python3 -m payload doctor
	@echo
	@echo "If every role above is reachable and the lab reports 10 passed,"
	@echo "the harness is working. Run 'make score' to find out whether your"
	@echo "model is."

clean:
	$(MAKE) -C lab/re-target clean
	$(MAKE) -C scripts/noegress clean
	rm -rf dist harness/runs runs
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
