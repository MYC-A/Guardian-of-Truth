set -a; . /data/.guardian_secrets.env; set +a
export PYTHONPATH=/data/compl/src:/data/compl GUARDIAN_DATA_ROOT=/data/compl LOCAL_VLLM_ENDPOINT=https://api.mistral.ai/v1/chat/completions LOCAL_VLLM_KEY=$MISTRAL_API_KEY
cd /data/compl
