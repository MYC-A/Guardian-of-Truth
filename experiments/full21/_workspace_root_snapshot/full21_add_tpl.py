#!/usr/bin/env python3
"""Add official Mistral-7B-Instruct-v0.3 chat template to tokenizer_config.json."""
import json

P = "/mnt/data/guardian/agent-workspace/superz_models/mistral-7b-instruct-v0.3/tokenizer_config.json"
d = json.load(open(P))
CHAT_TEMPLATE = (
    "{{ bos_token }}{% for message in messages %}"
    "{% if (message['role'] == 'user') != (loop.index0 % 2 == 0) %}"
    "{{ raise_exception('Conversation roles must alternate user/assistant/user/assistant/...') }}"
    "{% endif %}"
    "{% if message['role'] == 'user' %}"
    "{{ '[INST] ' + message['content'] + ' [/INST]' }}"
    "{% elif message['role'] == 'assistant' %}"
    "{{ ' ' + message['content'] + eos_token }}"
    "{% else %}"
    "{{ raise_exception('Only user and assistant roles are supported!') }}"
    "{% endif %}"
    "{% endfor %}"
)
d["chat_template"] = CHAT_TEMPLATE
json.dump(d, open(P, "w"), indent=2)
print("chat_template added, len:", len(CHAT_TEMPLATE))
print("tokenizer_class:", d.get("tokenizer_class"))
