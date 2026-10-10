"""Pure decision and budget logic of the cascade (no I/O, injectable clock).

Policy:
  * every row gets a triage probability p (None = unreadable triage);
  * rows are escalated to the full B2 pipeline in priority order (p descending,
    unreadable first) while the remaining wall budget admits another row;
  * an escalated row with a valid B2 label keeps it (B2 has precision 1.0 on
    valid46); optional OR rule flips B2=0 to 1 only when p >= or_threshold;
  * a row that was not escalated (or whose B2 failed) gets 1 iff p >= direct_threshold.

With an unlimited budget, skip_below=None and or_threshold=None the output is
exactly the B2 output: the cascade can only lose rows to the deadline, never
change an escalated B2 decision by default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import threading
import time


@dataclass
class Policy:
    direct_threshold: float = 0.5
    or_threshold: float | None = None
    skip_below: float | None = None  # never escalate rows with p below this


def priority(scores, policy):
    """Row ids in escalation order; unreadable triage first, then p descending."""
    def key(item):
        identifier, p = item
        return (0 if p is None else 1, -(p if p is not None else 1.0), identifier)
    order = [i for i, p in sorted(scores.items(), key=key)]
    if policy.skip_below is not None:
        order = [i for i in order if scores[i] is None or scores[i] >= policy.skip_below]
    return order


def final_label(p, b2, policy):
    """b2: 0/1 from a completed B2 row, None when not escalated or failed."""
    if b2 in (0, 1):
        if b2 == 0 and policy.or_threshold is not None and p is not None and p >= policy.or_threshold:
            return 1, 'B2_OR_TRIAGE'
        return b2, 'B2'
    if p is None:
        return 0, 'DEFAULT_ZERO'
    return int(p >= policy.direct_threshold), 'TRIAGE'


@dataclass
class Estimator:
    """Conservative per-row B2 wall estimate: max(prior-weighted mean, observed p90)."""
    prior_seconds: float = 300.0
    prior_weight: int = 2
    observed: list = field(default_factory=list)

    def add(self, seconds):
        self.observed.append(float(seconds))

    def estimate(self):
        values = sorted(self.observed)
        mean = (self.prior_seconds * self.prior_weight + sum(values)) / (self.prior_weight + len(values))
        if len(values) >= 3:
            p90 = values[min(len(values) - 1, math.ceil(0.9 * len(values)) - 1)]
            return max(mean, p90)
        return mean


class Dispatcher:
    """Admit escalations while now + estimate <= deadline - reserve.

    run_row(identifier) -> 0/1/None executes B2 for one row. Executed in
    `workers` threads. Rows still running at the hard deadline are abandoned and
    reported as None; the caller must not wait for them.
    """
    def __init__(self, run_row, workers, deadline, reserve=60.0, estimator=None, clock=time.monotonic,
                 poll=0.5):
        self.run_row, self.workers = run_row, workers
        self.deadline, self.reserve = deadline, reserve
        self.estimator = estimator or Estimator()
        self.clock, self.poll = clock, poll
        self.results, self.started, self.durations = {}, {}, {}
        self.skipped_budget = []
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)

    def _worker(self, identifier):
        begin = self.clock()
        try:
            value = self.run_row(identifier)
            value = value if value in (0, 1) else None
        except Exception:
            value = None
        seconds = self.clock() - begin
        with self.cond:
            self.results[identifier] = value
            self.durations[identifier] = seconds
            self.estimator.add(seconds)
            self.cond.notify_all()

    def run(self, order):
        pending = list(order)
        running = set()
        with self.cond:
            while True:
                running = {i for i in running if i not in self.results}
                now = self.clock()
                while pending and len(running) < self.workers:
                    if now + self.estimator.estimate() > self.deadline - self.reserve:
                        self.skipped_budget.extend(pending)
                        pending = []
                        break
                    identifier = pending.pop(0)
                    self.started[identifier] = now
                    running.add(identifier)
                    threading.Thread(target=self._worker, args=(identifier,), daemon=True).start()
                if not running and not pending:
                    break
                if self.clock() >= self.deadline - self.reserve / 2:
                    break  # hard stop: abandon in-flight rows
                self.cond.wait(timeout=self.poll)
            abandoned = sorted(i for i in running if i not in self.results)
        return dict(results=dict(self.results), abandoned=abandoned, skipped_budget=list(self.skipped_budget),
                    durations=dict(self.durations), estimate_final=self.estimator.estimate())
