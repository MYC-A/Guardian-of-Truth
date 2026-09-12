import argparse
import json
import os
from unittest.mock import patch

import pytest

from guardian_truth.llm_client import ChatClient, ChatClientError, ClientConfig, ConfigurationError, HTTPResponse
from guardian_truth.runtime import add_runtime_arguments, provider_config
from guardian_truth.settings import load_env_file


def test_bai_dotenv_alias_and_default_model(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('b_ai_api_key=synthetic-bai-key\nb_ai_model=qwen3.8-flash\n', encoding='utf-8')
    with patch.dict(os.environ, {}, clear=True):
        assert load_env_file(env_file)
        config = provider_config(ClientConfig(), 'bai')
        assert config.api_key_env.casefold() == 'b_ai_api_key'
        assert config.model == 'qwen3.8-flash'
        assert config.base_url == 'https://api.b.ai/v1'


def test_bai_never_falls_back_to_another_provider_key():
    with patch.dict(os.environ, {'GROQ_API_KEY': 'synthetic-groq-key'}, clear=True):
        client = ChatClient(provider_config(ClientConfig(), 'bai'))
        with pytest.raises(ChatClientError) as caught:
            client.validate_configuration()
        assert caught.value.category == 'missing_api_key'


def test_bai_rejects_cross_host_endpoint():
    with pytest.raises(ConfigurationError):
        provider_config(ClientConfig(), 'bai', base_url='https://api.groq.com/openai/v1')


def test_bai_chat_payload_uses_max_tokens_and_only_its_key():
    requests = []

    def transport(request, timeout):
        requests.append(request)
        return HTTPResponse(200, json.dumps({
            'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
            'model': 'qwen3.8-flash', 'usage': {'total_tokens': 8},
        }).encode())

    with patch.dict(os.environ, {'b_ai_api_key': 'synthetic-bai-key'}, clear=True):
        config = provider_config(ClientConfig(max_retries=0, response_format_mode='none'), 'bai')
        result = ChatClient(config, transport=transport).complete([
            {'role': 'user', 'content': 'Return {"ok":true}.'},
        ])
    assert result.model == 'qwen3.8-flash'
    payload = json.loads(requests[0].data)
    assert requests[0].full_url == 'https://api.b.ai/v1/chat/completions'
    assert requests[0].get_header('Authorization') == 'Bearer synthetic-bai-key'
    assert payload['max_tokens'] == 2048
    assert 'max_completion_tokens' not in payload
    assert 'response_format' not in payload
    assert payload['temperature'] == 0


def test_bai_is_available_through_runtime_cli():
    parser = argparse.ArgumentParser()
    add_runtime_arguments(parser)
    assert parser.parse_args(['--backend', 'bai']).backend == 'bai'
