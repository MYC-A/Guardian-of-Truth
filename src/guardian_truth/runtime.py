"""Explicit provider selection. Merely installing the package makes no API calls."""

from dataclasses import replace
import os
from urllib.parse import urlsplit

from .language import LanguageAnalyzer, LanguageConfig, RunBudget
from .llm_client import ChatClient, ClientConfig, ConfigurationError
from .pipeline import Detector


REMOTE_PROVIDERS = {
    'groq': ('api.groq.com', 'https://api.groq.com/openai/v1', 'GROQ_API_KEY'),
    'openrouter': ('openrouter.ai', 'https://openrouter.ai/api/v1', 'OPENROUTER_API_KEY'),
    'gemini': ('generativelanguage.googleapis.com',
               'https://generativelanguage.googleapis.com/v1beta/openai', 'GEMINI_API_KEY'),
}

PROVIDER_ALIASES = {
    'openrouter': (('OPENROUTER_API_KEY','OPENROUTE_API_KEY'),
                   ('OPENROUTER_MODEL','OPENROUTE_MODEL')),
    'gemini': (('GEMINI_API_KEY','GEMENI_API_KEY'),('GEMINI_MODEL','GEMENI_MODEL')),
}


def provider_config(config, backend, *, model=None, base_url=None):
    """Bind an endpoint to its own credential; never reuse another provider key."""
    if backend == 'local':
        endpoint = base_url or os.environ.get('GUARDIAN_LOCAL_BASE_URL','http://127.0.0.1:8000/v1')
        if urlsplit(endpoint).hostname not in ('localhost','127.0.0.1','::1'):
            raise ConfigurationError()
        return replace(config,base_url=endpoint,api_key_env='GUARDIAN_LOCAL_API_KEY',
                       model=model or config.model)
    if backend not in REMOTE_PROVIDERS:
        raise ValueError('Unknown backend')
    host,default_endpoint,key_env=REMOTE_PROVIDERS[backend]
    configured_model=None
    if backend in PROVIDER_ALIASES:
        key_names,model_names=PROVIDER_ALIASES[backend]
        key_env=next((name for name in key_names if os.environ.get(name)),key_env)
        configured_model=next((os.environ[name] for name in model_names if os.environ.get(name)),None)
    endpoint=base_url or default_endpoint
    if urlsplit(endpoint).hostname != host:
        raise ConfigurationError()
    return replace(config,base_url=endpoint,api_key_env=key_env,
                   model=model or configured_model or config.model)


def make_detector(*, backend='none', mode='graph', model=None, base_url=None,
                  max_requests=100, max_input_chars=2_000_000, seconds=1500,
                  max_rounds=3, max_evidence_chars=24000, max_prompt_chars=120000, rolling_evidence=False,
                  max_output_tokens=2048, timeout_seconds=30, retries=0, recovery='off',
                  semantic_protocol='baseline', decomposition_max_checks=12,
                  decomposition_group_size=4,
                  checks=frozenset({'availability','schema','provenance','rules','planning'})):
    if backend == 'none':
        return Detector(enabled=checks)
    if backend not in (*REMOTE_PROVIDERS,'local'):
        raise ValueError('Unknown backend')
    config = ClientConfig.from_env()
    # A configured Groq URL remains backward compatible only for the Groq
    # profile. Other profiles always use their own explicit default endpoint.
    selected_url=base_url or (config.base_url if backend=='groq' else None)
    config = provider_config(config,backend,model=model,base_url=selected_url)
    config = replace(config, max_output_tokens=max_output_tokens,
                     timeout_seconds=timeout_seconds, max_retries=retries)
    client = ChatClient(config)
    client.validate_configuration()
    budget=RunBudget(max_requests,max_input_chars,seconds)
    if semantic_protocol=='decomposed':
        from .decomposition import DecomposedAnalyzer,DecompositionConfig
        from .decomposition_exact import resolve_exact
        language=DecomposedAnalyzer(client,DecompositionConfig(max_evidence_chars=max_evidence_chars,
            max_prompt_chars=max_prompt_chars,max_checks=decomposition_max_checks,
            group_size=decomposition_group_size),budget=budget,deterministic_resolver=resolve_exact)
    else:
        language = LanguageAnalyzer(client, LanguageConfig(mode,max_rounds,max_evidence_chars,max_prompt_chars,
                                                           rolling_evidence,recovery,semantic_protocol),
                                    budget=budget)
    return Detector(enabled=checks, semantic=language)


def add_runtime_arguments(parser):
    parser.add_argument('--backend', choices=('none','groq','openrouter','gemini','local'), default='none')
    parser.add_argument('--mode', choices=('direct','graph','rlm'), default='graph')
    parser.add_argument('--model')
    parser.add_argument('--base-url')
    parser.add_argument('--max-requests', type=int, default=100)
    parser.add_argument('--max-input-chars', type=int, default=2_000_000)
    parser.add_argument('--seconds', type=float, default=1500)
    parser.add_argument('--max-rounds', type=int, default=3)
    parser.add_argument('--max-evidence-chars', type=int, default=24000)
    parser.add_argument('--max-prompt-chars', type=int, default=120000)
    parser.add_argument('--rolling-evidence', action='store_true',
                        help='Experimental RLM window replacement; evicted sources cannot be cited')
    parser.add_argument('--recovery', choices=('off','observe','directed','repeat'), default='off',
                        help='Experimental graph-mode uncertainty diagnostics and at most one recheck')
    parser.add_argument('--semantic-protocol', choices=('baseline','strict','decomposed'), default='baseline',
                        help='Semantic architecture; strict remains one-shot')
    parser.add_argument('--decomposition-max-checks',type=int,default=12)
    parser.add_argument('--decomposition-group-size',type=int,default=4)
    parser.add_argument('--max-output-tokens', type=int, default=2048)
    parser.add_argument('--timeout-seconds', type=float, default=30)
    parser.add_argument('--retries', type=int, default=0)
    parser.add_argument('--threshold', type=float, default=0.5,
                        help='Uncalibrated model-score threshold unless chosen on separate calibration data')
    parser.add_argument('--checks', default='availability,schema,provenance,rules,planning')


def detector_from_args(args):
    fields = ('backend','mode','model','base_url','max_requests','max_input_chars','seconds',
              'max_rounds','max_evidence_chars','max_prompt_chars','rolling_evidence','max_output_tokens','timeout_seconds','retries','recovery','semantic_protocol','decomposition_max_checks','decomposition_group_size')
    return make_detector(**{key:getattr(args,key) for key in fields},
                         checks=frozenset(x.strip() for x in args.checks.split(',') if x.strip()))
