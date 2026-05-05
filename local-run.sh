#!/bin/bash
rm -f app.log
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/klip-sa-key.json"
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload | tee app.log
