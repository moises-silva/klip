include .env
export

export PATH := $(CURDIR)/.venv/bin:$(PATH)

.PHONY: deploy setup run dev fmt lint fix test

dev:
	pip install -r requirements-dev.txt
	git config core.hooksPath .githooks

fmt:
	ruff format app tests

lint:
	ruff check app tests

fix:
	ruff check --fix app tests

test:
	pytest tests/ -v

setup:
	bash deploy/setup.sh

deploy:
	bash deploy/deploy.sh

run:
	uvicorn app.main:app --reload --port 8080
