import asyncio
import sys
import threading
from pathlib import Path
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))
from dispatch import BoundedDispatcher, RequestTimedOut


@pytest.mark.asyncio
async def test_timed_out_worker_retains_capacity_until_real_completion():
    queue = BoundedDispatcher(workers=1, max_waiting=0, queue_timeout_s=.1)
    running, release = threading.Event(), threading.Event()

    def blocked(_):
        running.set()
        release.wait(1)
        return "finished"

    try:
        with pytest.raises(RequestTimedOut):
            await queue.run(blocked, {}, timeout_s=.05)
        assert running.is_set()
        assert queue.pending == 1
        with pytest.raises(HTTPException) as err:
            await queue.run(lambda _: "new", {}, timeout_s=.1)
        assert err.value.status_code == 429
    finally:
        release.set()
        for _ in range(100):
            if queue.pending == 0:
                break
            await asyncio.sleep(.005)
    assert queue.pending == 0
    assert await queue.run(lambda _: "recovered", {}, timeout_s=.2) == "recovered"


@pytest.mark.asyncio
async def test_backend_timeout_is_not_misreported_as_running_worker():
    queue = BoundedDispatcher(workers=1, max_waiting=0)

    def failed(_):
        raise TimeoutError("backend stopped")

    with pytest.raises(TimeoutError) as err:
        await queue.run(failed, {}, timeout_s=1)
    assert not isinstance(err.value, RequestTimedOut)
    assert queue.pending == 0
    assert await queue.run(lambda _: "recovered", {}, timeout_s=.2) == "recovered"


@pytest.mark.asyncio
async def test_queue_deadline_has_no_worker_leak():
    queue = BoundedDispatcher(workers=1, max_waiting=1, queue_timeout_s=.03)
    release = threading.Event()
    first = asyncio.create_task(queue.run(lambda _: release.wait(1), {}, timeout_s=.5))
    await asyncio.sleep(.01)
    try:
        with pytest.raises(HTTPException) as err:
            await queue.run(lambda _: "never started", {}, timeout_s=.2)
        assert err.value.status_code == 429
        assert queue.pending == 1
    finally:
        release.set()
        await first
    assert queue.pending == 0
