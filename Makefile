.PHONY: smoke backend-test live-check live-publish-check release-gate

smoke:
	./scripts/smoke_mvp.sh

backend-test:
	cd backend && PYTHONPATH=. python3 -m pytest -q

live-check:
	./scripts/live_check.sh

live-publish-check:
	TRIGGER_PUBLISH=1 ./scripts/live_check.sh

release-gate:
	$(MAKE) backend-test
	$(MAKE) smoke
	$(MAKE) live-check
