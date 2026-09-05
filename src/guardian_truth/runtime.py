"""Explicit provider selection. Merely installing the package makes no API calls."""

from dataclasses import replace
import os
from urllib.parse import urlsplit

from .language import LanguageAnalyzer, LanguageConfig, RunBudget
from .llm_client import ChatClient, ClientConfig, ConfigurationError
from .pipeline import Detector


def make_detector(*, backend='none', mode='graph', model=None, base_url=None,
                  max_requests=100, max_input_chars=2_000_000, seconds=1500,
                  max_rounds=3, max_evidence_chars=24000, max_prompt_chars=120000,
                  max_output_tokens=2048, timeout_seconds=30, retries=0,
                  checks=frozenset({'availability','schema','provenance','rules','planning'})):
    if backend == 'none':
        return Detector(enabled=checks)
    if backend not in ('groq','local'):
        raise ValueError('Unknown backend')
    config = ClientConfig.from_env()
    if backend == 'local':
        endpoint = base_url or os.environ.get('GUARDIAN_LOCAL_BASE_URL','http://127.0.0.1:8000/v1')
        if urlsplit(endpoint).hostname not in ('localhost','127.0.0.1','::1'):
            raise ConfigurationError()
        # Never send a Groq secret to another endpoint when switching providers.
        config = replace(config, base_url=endpoint, api_key_env='GUARDIAN_LOCAL_API_KEY')
    else:
        endpoint = base_url or config.base_url
        if urlsplit(endpoint).hostname != 'api.groq.com':
            raise ConfigurationError()
        config = replace(config, base_url=endpoint, api_key_env='GROQ_API_KEY')
    config = replace(config, model=model or config.model, max_output_tokens=max_output_tokens,
                     timeout_seconds=timeout_seconds, max_retries=retries)
    client = ChatClient(config)
    client.validate_configuration()
    language = LanguageAnalyzer(client, LanguageConfig(mode,max_rounds,max_evidence_chars,max_prompt_chars),
                                budget=RunBudget(max_requests,max_input_chars,seconds))
    return Detector(enabled=checks, semantic=language)


def add_runtime_arguments(parser):
    parser.add_argument('--backend', choices=('none','groq','local'), default='none')
    parser.add_argument('--mode', choices=('direct','graph','rlm'), default='graph')
    parser.add_argument('--model')
    parser.add_argument('--base-url')
    parser.add_argument('--max-requests', type=int, default=100)
    parser.add_argument('--max-input-chars', type=int, default=2_000_000)
    parser.add_argument('--seconds', type=float, default=1500)
    parser.add_argument('--max-rounds', type=int, default=3)
    parser.add_argument('--max-evidence-chars', type=int, default=24000)
    parser.add_argument('--max-prompt-chars', type=int, default=120000)
    parser.add_argument('--max-output-tokens', type=int, default=2048)
    parser.add_argument('--timeout-seconds', type=float, default=30)
    parser.add_argument('--retries', type=int, default=0)
    parser.add_argument('--threshold', type=float, default=0.5,
                        help='Uncalibrated model-score threshold unless chosen on separate calibration data')
    parser.add_argument('--checks', default='availability,schema,provenance,rules,planning')


def detector_from_args(args):
    fields = ('backend','mode','model','base_url','max_requests','max_input_chars','seconds',
              'max_rounds','max_evidence_chars','max_prompt_chars','max_output_tokens','timeout_seconds','retries')
    return make_detector(**{key:getattr(args,key) for key in fields},
                         checks=frozenset(x.strip() for x in args.checks.split(',') if x.strip()))
