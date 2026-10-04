"""Native order is a code property independent of the model's verdict."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
sys.path.insert(0, str(ROOT / 'experiments/research_v3/diagnostics'))
from build_suite import build
from pilot import make_graph
from source_guard import future_native_sources


def test_later_current_call_and_result_are_rejected_for_first_target():
    rows, _ = build()
    g = make_graph(next(r for r in rows if r['id'] == 'custody.chronology'))
    assert len(future_native_sources(g, ['t1', 't2'])) == 2
    assert future_native_sources(g, ['t0']) == []


def test_history_result_and_prose_claim_have_no_invented_future_marker():
    rows, _ = build()
    g = make_graph(next(r for r in rows if r['id'] == 'custody.allowed'))
    assert future_native_sources(g, ['h2', 'h3', 't0', 'p0']) == []
    g = make_graph(next(r for r in rows if r['id'] == 'publishing.false_success_claim'))
    assert future_native_sources(g, ['h2', 'h3', 't0']) == []
