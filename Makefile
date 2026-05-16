include .env
export

.PHONY: deploy setup run dev fmt lint test

dev:
	pip install -r requirements-dev.txt
	git config core.hooksPath .githooks

fmt:
	ruff format app tests

lint:
	ruff check app tests

test:
	pytest tests/ -v

setup:
	bash deploy/setup.sh

deploy:
	bash deploy/deploy.sh

run:
	uvicorn app.main:app --reload --port 8080
