#!/bin/bash
set -euo pipefail

DEST=/home/klip/klip
SERVICE=klip

echo "Syncing files to $DEST..."
sudo rsync -a \
    --exclude='.venv' \
    --exclude='.env' \
    --exclude='*.log' \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='tmp' \
    --exclude='klip-sa-key.json' \
    "$(dirname "$0")/" "$DEST/"

echo "Fixing ownership..."
sudo chown -R klip:klip "$DEST"

echo "Installing dependencies..."
sudo -u klip "$DEST/.venv/bin/pip" install -q -r "$DEST/requirements.txt"

echo "Restarting $SERVICE..."
sudo systemctl restart "$SERVICE"

echo "Done. Logs: journalctl -u $SERVICE -f"
