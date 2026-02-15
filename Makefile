VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
DEV_STAMP := $(VENV)/.dev-deps-installed

.PHONY: test

test: $(DEV_STAMP)
	$(PYTHON) -m pytest -q

$(VENV)/bin/python:
	python3 -m venv $(VENV)

$(DEV_STAMP): requirements.txt requirements-dev.txt | $(VENV)/bin/python
	$(PIP) install -r requirements-dev.txt
	touch $(DEV_STAMP)
