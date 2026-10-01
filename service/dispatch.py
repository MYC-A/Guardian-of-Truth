"""Bounded admission and deadlines; running threads retain capacity on timeout."""
import asyncio
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool


class RequestTimedOut(TimeoutError):
    pass


class BoundedDispatcher:
    def __init__(self, workers=1, max_waiting=4, queue_timeout_s=60):
        if workers < 1 or max_waiting < 0 or queue_timeout_s <= 0:
            raise ValueError("invalid dispatcher capacity")
        self.workers = workers
        self.max_waiting = max_waiting
        self.queue_timeout_s = queue_timeout_s
        self.pending = 0
        self.semaphore = asyncio.Semaphore(workers)

    async def run(self, function, payload, timeout_s):
        if timeout_s <= 0:
            raise ValueError("invalid request timeout")
        if self.pending >= self.workers + self.max_waiting:
            raise HTTPException(429, "Guardian admission queue is full")
        self.pending += 1
        try:
            await asyncio.wait_for(self.semaphore.acquire(), self.queue_timeout_s)
        except BaseException as exc:
            self.pending -= 1
            if isinstance(exc, TimeoutError):
                raise HTTPException(429, "Guardian queue wait timed out") from None
            raise
        task = asyncio.create_task(run_in_threadpool(function, payload))

        def release_when_finished(done):
            self.pending -= 1
            self.semaphore.release()
            if not done.cancelled():
                done.exception()  # retrieve exception even after caller deadline

        task.add_done_callback(release_when_finished)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout_s)
        except TimeoutError:
            if task.done():
                # A backend's TimeoutError is not our request deadline.
                return task.result()
            # Threads cannot be killed safely. Shield the worker, retain its
            # slot, and allow admission again only after it actually exits.
            raise RequestTimedOut("Guardian request deadline exceeded") from None
