"""SDK monitoring reports payload without exposing its private report fields."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def module():
    path = Path(__file__).resolve().parents[1] / 'scripts/download_qwen_weights.py'
    spec = importlib.util.spec_from_file_location('weights_monitor_test', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_progress_keeps_original_callback_and_only_records_numeric_counts(monkeypatch):
    sdk = module()
    original_calls, saved = [], []
    class Reporter:
        def update_progress(self, report, items=None):
            original_calls.append((report, items))
            return 'original-result'
    original = Reporter.update_progress
    clock = [100]
    monkeypatch.setattr(sdk.time, 'monotonic', lambda: clock[0])
    restore = sdk.monitor_xet_progress(Reporter, lambda state, **fields: saved.append((state, fields)))
    report = SimpleNamespace(total_transfer_bytes_completed=1024, total_bytes_completed=0,
                             total_transfer_bytes_completion_rate=256.5,
                             private_signed_url='MUST_NOT_BE_LOGGED', access_token='MUST_NOT_BE_LOGGED')
    instance = Reporter()
    try:
        assert instance.update_progress(report, {'item': 1}) == 'original-result'
        clock[0] += 1
        instance.update_progress(report)
        assert len(saved) == 1
        clock[0] += 10
        report.total_bytes_completed = 512
        instance.update_progress(report)
        assert len(saved) == 2 and saved[-1][1]['reconstructed_bytes'] == 512
        assert saved[0] == ('DOWNLOADING_PUBLIC_MODEL', dict(
            received_bytes=1024, reconstructed_bytes=0, transfer_bytes_per_second=256.5))
        assert len(original_calls) == 3
    finally:
        restore()
    assert Reporter.update_progress is original


def test_monitoring_disk_failure_does_not_cancel_transfer_callback():
    sdk = module()
    class Reporter:
        def update_progress(self, report):
            return 42
    def disk_failure(*args, **kwargs):
        raise OSError('monitoring disk is unavailable')
    restore = sdk.monitor_xet_progress(Reporter, disk_failure)
    try:
        assert Reporter().update_progress(SimpleNamespace(total_bytes_completed=1)) == 42
    finally:
        restore()
