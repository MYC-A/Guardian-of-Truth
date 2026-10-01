#!/usr/bin/env bash
set -euo pipefail
utils=/opt/supervisor-scripts/utils
. "${utils}/logging.sh"
. "${utils}/environment.sh"
repo=${GUARDIAN_REPO:-/workspace/guardian/repos/hybrid-service-worktree}
export GUARDIAN_CONFIG=${GUARDIAN_CONFIG:-structural-v02}
export GUARDIAN_AUDIT_PATH=${GUARDIAN_AUDIT_PATH:-/workspace/guardian/results/hybrid_service/audit.jsonl}
export GUARDIAN_MAX_QUEUE=${GUARDIAN_MAX_QUEUE:-4}
export GUARDIAN_WORKERS=1
export PYTHONUNBUFFERED=1
cd "$repo"
pty /workspace/guardian/venv/bin/python -m uvicorn service.app:app \
  --host 127.0.0.1 --port "${GUARDIAN_PORT:-18090}" --workers 1
