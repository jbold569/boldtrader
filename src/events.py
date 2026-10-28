"""Global events stream (ticket #41).

A process-wide pub/sub hub plus the SSE writer for `GET /api/v1/events`.
Background code (fan-out, enrichment worker, liveness sweeps) publishes
occurrences; every open HTTP stream forwards them to its client.

The stream is notification, not a log: events are ephemeral, slow or
disconnected consumers drop frames rather than blocking publishers. All
durable state lives in the database; a reconnecting client reads current
state from the API.
"""

from __future__ import annotations

import json
import queue
import threading
import time

PING_INTERVAL_SECONDS = 15.0

_MAX_QUEUE = 1000

_subscribers: set[queue.Queue] = set()
_lock = threading.Lock()


def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=_MAX_QUEUE)
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        _subscribers.discard(q)


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)


def publish(name: str, payload: dict) -> None:
    """Fan one event out to all subscribers. Never blocks: a full queue
    (a stuck or dead consumer) drops the event for that subscriber only."""
    frame = f"event: {name}\ndata: {json.dumps(payload)}\n\n"
    with _lock:
        targets = list(_subscribers)
    for q in targets:
        try:
            q.put_nowait(frame)
        except queue.Full:
            pass


def serve(handler) -> None:
    """Stream events to an HTTP handler until the client disconnects.

    Long-lived `text/event-stream` response; frames are flushed as written.
    A `: ping` comment frame goes out every PING_INTERVAL_SECONDS so idle
    connections stay warm through proxies. The interval constant is read
    each cycle (tests shrink it via monkeypatch).
    """
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    wfile = handler.wfile

    q = subscribe()
    try:
        next_ping = time.monotonic() + PING_INTERVAL_SECONDS
        while True:
            timeout = max(next_ping - time.monotonic(), 0.05)
            try:
                frame = q.get(timeout=timeout)
            except queue.Empty:
                wfile.write(b": ping\n\n")
                wfile.flush()
                next_ping = time.monotonic() + PING_INTERVAL_SECONDS
                continue
            wfile.write(frame.encode("utf-8"))
            wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass  # client went away; nothing to report
    finally:
        unsubscribe(q)
