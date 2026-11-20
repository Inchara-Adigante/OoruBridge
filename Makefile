# Override the connection with DATABASE_URL, e.g.
#   make setup DATABASE_URL=postgresql://postgres:postgres@localhost:5432/oorubridge
PY ?= .venv/bin/python

.PHONY: venv db setup run test

venv:
	python3 -m venv .venv && $(PY) -m pip install -r requirements.txt

db:
	docker compose up -d --wait

setup:              ## create the database, apply migrations, load the sample catalog
	$(PY) scripts/migrate.py --reset --seed

run:                ## API on http://localhost:8000 (interactive docs at /docs)
	$(PY) -m uvicorn oorubridge.api:app --reload

test:
	$(PY) -m pytest
