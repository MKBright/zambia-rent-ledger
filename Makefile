PY = .venv/bin/python

.PHONY: install seed run test

install:
	python3 -m venv .venv
	$(PY) -m pip install -r requirements.txt

seed:
	$(PY) seed.py

run:
	$(PY) run.py

test:
	$(PY) -m pytest
