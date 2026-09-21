#!/bin/bash
cd /mnt/data/guardian/agent-workspace/Guardian-full21-hybrid
exec /mnt/data/guardian/venv/bin/python experiments/full21/mini_openai_server.py > /mnt/data/guardian/agent-workspace/mini_mistral.log 2>&1
