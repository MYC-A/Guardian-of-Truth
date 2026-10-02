"""Cross-process channel circuit breaker (assignment section 5).

State is keyed by endpoint + credential-slot + model and stored in the
phase budget sqlite (shared by jobs and the service process). Keys and
raw error bodies are never persisted; the credential slot is a truncated
sha256 fingerprint of the key material, the model and endpoint are public
names.

Rules (assignment 5.4-5.8):
- 402 / quota exhaustion, 401 / 403 access: channel OPEN_PERMANENT until
  configuration/quota changes or an explicit probe succeeds.
- 429: channel closes for a cooldown (Retry-After when provided, else
  60/120/240 s by cycle). After the cooldown exactly ONE caller is
  atomically admitted as a live probe claim (state PROBING); concurrent
  callers are vetoed with PROBE_IN_FLIGHT until the admitted request
  finishes (success clears the channel, another 429 re-arms the cooldown
  with the inherited cycle count, 5xx/timeout releases the claim) or the
  claim window lapses. Three consecutive 429 cycles open the channel
  permanently.
- 5xx/timeout: no breaker; the caller may do at most one technical retry.
- Probes are short real chat requests (max output ~32 tokens) marked with
  caller='channel-probe'; they are counted in attempts and cost, may pass
  an OPEN_PERMANENT channel, and a successful probe clears the channel.
"""
from __future__ import annotations
import json
import sqlite3
import time

PROBE_CALLER = 'channel-probe'

# A claimed probe holds exclusive admission slightly longer than the client
# transport timeout (240 s), so an in-flight claimed request can never
# overlap a freshly admitted second claim; a crashed claimant self-heals
# when the window lapses.
PROBE_WINDOW_SECONDS = 300.0


def _now():
    return time.time()


class ChannelBreaker:
    def __init__(self, sqlite_path):
        self.path = str(sqlite_path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS breaker_state ('
                       'key TEXT PRIMARY KEY, state TEXT, reason TEXT, until REAL,'
                       'cycles INTEGER DEFAULT 0, updated REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS breaker_events ('
                       'id INTEGER PRIMARY KEY, key TEXT, event TEXT, detail TEXT, ts REAL)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    @staticmethod
    def key_for(endpoint, slot, model):
        return f'{endpoint}|{slot}|{model}'

    def _row(self, key):
        with self.connect() as db:
            return db.execute('SELECT state,reason,until,cycles FROM breaker_state WHERE key=?',
                              (key,)).fetchone()

    def guard(self, key, *, is_probe=False):
        """None when the call may proceed, else (state, reason, until).

        After a 429 cooldown expires, exactly ONE caller is atomically
        admitted as the live probe (state PROBING, user fix 2026-10-02 #2):
        concurrent callers are vetoed with PROBE_IN_FLIGHT until the admitted
        request finishes (success clears, a repeated 429 re-arms the cooldown
        with the inherited cycle count, 5xx/timeout releases the claim) or
        the claim window lapses (stale claim becomes re-claimable).
        """
        row = self._row(key)
        if row is None:
            return None
        state, reason, until, _cycles = row
        now = _now()
        if state == 'OPEN_PERMANENT':
            return None if is_probe else (state, reason, None)
        if state in ('OPEN_COOLDOWN', 'PROBING'):
            if now < until:
                # Active cooldown, or an admitted probe still in flight.
                return (state, 'PROBE_IN_FLIGHT' if state == 'PROBING' else reason, until)
            if self._claim_probe(key):
                return None  # this caller won the atomic single admission
            fresh = self._row(key)
            if fresh is None:
                return None  # channel cleared meanwhile (e.g. success)
            if fresh[0] == 'OPEN_PERMANENT':
                return None if is_probe else (fresh[0], fresh[1], None)
            return (fresh[0], 'PROBE_IN_FLIGHT', fresh[2])
        return None

    def _claim_probe(self, key, window=PROBE_WINDOW_SECONDS):
        """Atomic single admission of one post-cooldown probe request.

        BEGIN IMMEDIATE re-checks the state under the write lock, so of N
        concurrent callers exactly one transitions the channel into PROBING;
        the others lose the race and are vetoed by guard(). Without this,
        several requests are admitted simultaneously after the cooldown
        expires and the first 429 repeats as a burst (the reported repro).
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,until FROM breaker_state WHERE key=?', (key,)).fetchone()
            now = _now()
            if row is None or row[0] not in ('OPEN_COOLDOWN', 'PROBING') or now < float(row[1]):
                db.rollback()
                return False
            db.execute('UPDATE breaker_state SET state=?, until=?, updated=? WHERE key=?',
                       ('PROBING', now + window, now, key))
            self._event(db, key, 'probe_claimed', f'window={window:.0f}s')
            db.commit()
            return True

    def record_failure(self, key, classification, retry_after=None):
        """Update breaker state from a classified transport failure."""
        cycles = 0
        row = self._row(key)
        # Cycle count is inherited from an in-flight PROBING claim too: the
        # claimant's 429 is the NEXT consecutive cooldown cycle, never a reset.
        if row and row[0] in ('OPEN_COOLDOWN', 'PROBING'):
            cycles = row[3] or 0
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if classification in ('402_QUOTA', '401_403_ACCESS'):
                db.execute('INSERT INTO breaker_state(key,state,reason,until,cycles,updated) '
                           'VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET '
                           'state=excluded.state, reason=excluded.reason, until=excluded.until, '
                           'cycles=excluded.cycles, updated=excluded.updated',
                           (key, 'OPEN_PERMANENT', classification, None, 0, _now()))
                self._event(db, key, 'open_permanent', classification)
            elif classification == '429_RATE_LIMIT':
                cycles += 1
                if cycles >= 3:
                    db.execute('INSERT INTO breaker_state(key,state,reason,until,cycles,updated) '
                               'VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET '
                               'state=excluded.state, reason=excluded.reason, until=excluded.until, '
                               'cycles=excluded.cycles, updated=excluded.updated',
                               (key, 'OPEN_PERMANENT', '429_REPEATED', None, cycles, _now()))
                    self._event(db, key, 'open_permanent', '429_repeated')
                else:
                    wait = float(retry_after) if retry_after else min(60 * (2 ** (cycles - 1)), 240)
                    db.execute('INSERT INTO breaker_state(key,state,reason,until,cycles,updated) '
                               'VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET '
                               'state=excluded.state, reason=excluded.reason, until=excluded.until, '
                               'cycles=excluded.cycles, updated=excluded.updated',
                               (key, 'OPEN_COOLDOWN', '429_RATE_LIMIT', _now() + wait, cycles, _now()))
                    self._event(db, key, 'open_cooldown', f'wait={wait:.0f}s retry_after={retry_after}')
            else:
                # 5xx/timeout/other: no channel block; event only. A PROBING
                # claim is released so a transiently failed probe does not
                # pin the channel for the whole claim window.
                db.execute("DELETE FROM breaker_state WHERE key=? AND state='PROBING'", (key,))
                self._event(db, key, 'transient_failure', classification)
            db.commit()

    def record_success(self, key):
        """A live success (probe or normal call) fully clears the channel."""
        with self.connect() as db:
            db.execute('DELETE FROM breaker_state WHERE key=?', (key,))
            self._event(db, key, 'cleared_by_success', '')
            db.commit()

    def clear(self, key, why):
        """Manual/config-change reset only; always journaled."""
        with self.connect() as db:
            db.execute('DELETE FROM breaker_state WHERE key=?', (key,))
            self._event(db, key, 'manual_clear', why)
            db.commit()

    def _event(self, db, key, event, detail):
        db.execute('INSERT INTO breaker_events(key,event,detail,ts) VALUES(?,?,?,?)',
                   (key, event, str(detail)[:200], _now()))

    def snapshot(self):
        with self.connect() as db:
            states = db.execute('SELECT key,state,reason,until,cycles FROM breaker_state').fetchall()
            events = db.execute('SELECT COUNT(*) FROM breaker_events').fetchone()[0]
        return {'channels': [dict(zip(('key', 'state', 'reason', 'until', 'cycles'), r)) for r in states],
                'events_total': events}


def classify_transport(status_code, error_text=''):
    """Faithful per-status classification; statuses stay separately visible."""
    text = (error_text or '').lower()
    if status_code == 402:
        return '402_QUOTA'
    if status_code in (401, 403):
        return '401_403_ACCESS'
    if status_code == 429:
        return '429_RATE_LIMIT'
    if isinstance(status_code, int) and 500 <= status_code < 600:
        return '5XX'
    if status_code is None and ('timeout' in text or 'timed out' in text):
        return 'TIMEOUT'
    return 'OTHER'


def safe_retry_after(exc):
    """Extract a numeric Retry-After (header value only; never headers body)."""
    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', None)
    if not headers:
        return None
    try:
        value = headers.get('retry-after')
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def probe(model, caller=PROBE_CALLER):
    """One short REAL chat request through the budgeted transport path.

    max output ~32 tokens, no cache; counted in attempts and cost. The
    budget layer lets probe-marked calls pass an OPEN_PERMANENT channel.
    """
    import llm
    return llm.chat(model, [{'role': 'user', 'content': 'say ok'}],
                    max_tokens=32, temperature=0.0, use_cache=False,
                    transport_retries=0, caller=caller)
