"""Separate loopback modular research service; existing app/config unchanged."""
import os
from pathlib import Path
import sys
from functools import partial
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/searh_23/modular_steps_20261002'))
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from modular_runtime import CONFIGS, check
from dispatch import BoundedDispatcher, RequestTimedOut

app = FastAPI(title='Guardian modular experimental service')
dispatcher = BoundedDispatcher(workers=1, max_waiting=4, queue_timeout_s=20)
DEFAULT = os.environ.get('GUARDIAN_MODULAR_CONFIG', 'modular-structural-v1')


class Case(BaseModel):
    case_id: str = 'unnamed'
    prompt: str
    response: str
    config_id: str | None = None


class Batch(BaseModel):
    cases: list[Case] = Field(min_length=1, max_length=4)
    config_id: str | None = None


@app.get('/health')
def health():
    return {'status': 'alive', 'pid': os.getpid(), 'config_id': DEFAULT, 'existing_R0_default_changed': False}


@app.get('/ready')
def ready():
    from modular_common import Budget
    budget = Budget().snapshot()
    return {'ready': True, 'local_source_modules': True, 'inference_probe_performed': False,
            'provider_availability': 'UNPROBED', 'pilot_budget': {k: budget[k] for k in ('actual_api_attempts', 'logical_tokens', 'pending_reservations')}}


@app.get('/v1/configs')
def configs():
    return {'default': DEFAULT, 'configs': CONFIGS, 'quality_winner_selected': False}


async def execute(case, config=None):
    selected = case.config_id or config or DEFAULT
    if selected not in CONFIGS:
        raise HTTPException(404, 'unknown modular config')
    try:
        return await dispatcher.run(partial(check, config=selected), case.model_dump(), timeout_s=240)
    except RequestTimedOut:
        from modular_common import source_sha
        return {'case_id': case.case_id, 'config_id': selected, 'trace_id': str(uuid.uuid4()),
                'source_sha256': source_sha(case.model_dump()), 'decision': 'UNKNOWN',
                'coverage': {'source_complete': True, 'semantic_check_complete': False},
                'degraded': True, 'unknown_reasons': ['deadline_worker_slot_retained'], 'cost': {'status': 'PENDING_WORKER'}}


@app.post('/v1/check')
async def check_one(case: Case):
    return await execute(case)


@app.post('/v1/check/batch')
async def check_batch(batch: Batch):
    results = [await execute(case, batch.config_id) for case in batch.cases]
    return {'n': len(results), 'results': results}
