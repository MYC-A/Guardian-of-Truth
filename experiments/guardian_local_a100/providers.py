"""Register LOCAL OpenAI-compatible endpoints as first-class providers.

Cache identity stays honest: provider name + endpoint + model id all enter the
exact-equivalence cache key (sha256(provider, endpoint, model, request, attempt)),
so a locally served model is never masked as a Mistral API model. Endpoints and
key names are read from the environment at import time; defaults match the
server lifecycle scripts in /workspace/guardian/scripts_a100/ (vLLM on :8000,
llama.cpp llama-server on :8080). Local servers do not authenticate; a dummy
key is set only to satisfy the transport's missing-key guard.

Call register_local_providers() once before constructing Transport/ReadThrough
for a local backend. Registering the same provider twice is a no-op, and an
endpoint supplied via the environment wins over the default.
"""
import os

from guardian_truth.integrated.transport import PROVIDERS

LOCAL_PROVIDERS = {
    # provider name -> (endpoint env var, default endpoint, api key env var)
    'local-vllm': ('LOCAL_VLLM_ENDPOINT', 'http://127.0.0.1:8000/v1/chat/completions', 'LOCAL_VLLM_KEY'),
    'local-llamacpp': ('LOCAL_LLAMACPP_ENDPOINT', 'http://127.0.0.1:8080/v1/chat/completions', 'LOCAL_LLAMACPP_KEY'),
}

# Model identity convention (served name == cache identity, never a Mistral name):
#   <checkpoint>@<revision12>:<precision|quant>:<backend>-<backend_version>
# e.g. ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0
#      qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459


def register_local_providers():
    """Idempotent; environment-supplied endpoints take precedence over defaults."""
    for name, (env, default, keyenv) in LOCAL_PROVIDERS.items():
        if name not in PROVIDERS:
            PROVIDERS[name] = (os.environ.get(env, default), keyenv)
        os.environ.setdefault(keyenv, 'local-noauth')


def backend_endpoint(provider):
    register_local_providers()
    return PROVIDERS[provider][0]
