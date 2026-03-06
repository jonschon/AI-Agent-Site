.PHONY: smoke backend-test

smoke:
	./scripts/smoke_mvp.sh

backend-test:
	cd backend && PYTHONPATH=. python3 -m pytest -q
