#!/bin/bash
export PYTHONPATH=/mnt/data/guardian/agent-workspace/superz_pylibs
/mnt/data/guardian/venv/bin/python -m vllm.entrypoints.openai.api_server   --model /mnt/data/guardian/agent-workspace/superz_models/mistral-7b-instruct-v0.3   --tokenizer-mode auto   --served-model-name mistral-7b-instruct-v0.3   --port 8001 --gpu-memory-utilization 0.90 --max-model-len 16384 --max-num-seqs 4   --disable-log-requests > /mnt/data/guardian/agent-workspace/vllm_mistral4.log 2>&1
