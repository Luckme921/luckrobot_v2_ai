"""Request-local diagnostics; never log prompts or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import time
import uuid

trace_id = ContextVar("trace_id", default="")
turn_started = ContextVar("turn_started", default=None)
progress = ContextVar("progress", default=None)

def begin_turn():
    trace_id.set(uuid.uuid4().hex)
    turn_started.set(time.monotonic())

def record(stage, seconds, **fields):
    event = {"type": "timing", "trace_id": trace_id.get(), "stage": stage,
             "seconds": round(seconds, 4), **fields}
    print("[TIMING] " + json.dumps(event, ensure_ascii=False), flush=True)
    callback = progress.get()
    if callback is not None:
        callback(event)

@contextmanager
def measure(stage):
    started = time.monotonic()
    status = "ok"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        record(stage, time.monotonic() - started, status=status)

def announce(action):
    callback = progress.get()
    if callback is not None:
        callback({"type": "tool_start", "action": action,
                  "trace_id": trace_id.get()})
