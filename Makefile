include .env
export

.PHONY: deploy setup run

setup:
	bash deploy/setup.sh

deploy:
	bash deploy/deploy.sh

run:
	uvicorn app.main:app --reload --port 8080
