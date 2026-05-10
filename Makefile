include .env
export

.PHONY: deploy setup run dev

dev:
	pip install -r requirements-dev.txt
	git config core.hooksPath .githooks

setup:
	bash deploy/setup.sh

deploy:
	bash deploy/deploy.sh

run:
	uvicorn app.main:app --reload --port 8080
