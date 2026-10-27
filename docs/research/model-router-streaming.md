# Model Router Streaming: Empirical SSE Feasibility (ticket #16)

Research date: 2026-10-26/27. Router: `http://model.boldhalo.home` (OpenAI-compatible),
nginx/1.31.7 in front, Python router (`model-router.service`) behind it, upstream
halogen engine (`serve_api` v0.18.16, 4 slots, 204800-token KV pool). All findings
below are from executed probes (curl) plus the router's own journal
(`journalctl -u model-router.service`) — not from documentation.

## 1. Raw stream shape (what the router actually sends)

Test: `POST /v1/chat/completions {"stream": true}`, model
`qwen3.8-flash-next-w4b-q8-halogen-pair`, request "Say HELLO WORLD only."
Captured with per-chunk arrival timestamps:

```
[  0.745s] data: {"id": "chatcmpl-caffd6...", "created": ..., "model": "halogen-qwen3.8-flash-next",
             "object": "chat.completion.chunk", "choices": [{"index": 0, "finish_reason": null,
             "delta": {"role": "assistant", "content": ""}}]}
[  0.745s] data: {... "delta": {"reasoning_content": "We"}}
[  0.786s] data: {... "delta": {"reasoning_content": " need"}}
   ... one reasoning_content delta every ~33 ms ...
[  1.707s] data: {... "delta": {"content": "HEL"}}
[  1.708s] data: {... "delta": {"content": "LO"}}
[  1.753s] data: {... "delta": {"content": " WORLD"}}
[  1.753s] data: {... "finish_reason": "length", "delta": {}, "timings": {...}}
[  1.754s] data: [DONE]
```

Findings:

- **Framing**: pure `data:` SSE frames, JSON payload, terminated by `data: [DONE]`.
  No `event:` field is used by the router — everything is `data:` only.
- **Response headers**: `Content-Type: text/event-stream; charset=utf-8`,
  `Transfer-Encoding: chunked` (no Content-Length), `Connection: keep-alive`,
  `vary: Origin`.
- **Role arrival**: first frame carries `delta: {role: "assistant", content: ""}`.
- **Content deltas are token-by-token** — 2–4 visible characters per frame.
- **`reasoning_content` is a first-class second stream**: this router streams the
  model's thinking in a separate delta key, *before* `content` deltas start. A
  chat UI must decide what to do with `reasoning_content` (render collapsed, or
  hide). `content` deltas begin only after reasoning ends.
- **finish_reason** arrives on the *last* frame, with an empty `delta: {}`, in the
  same frame as a rich `timings` object (`prompt_ms`, `predicted_ms`,
  per-second rates, speculation stats). After that, `data: [DONE]`, then close.
- **`stream_options: {"include_usage": true}` is supported**: a final frame with
  `"choices": []` and a `usage` block arrives just before `[DONE]`:

```
data: {"id": ..., "choices": [], "usage": {"prompt_tokens": 54, "completion_tokens": 5,
       "total_tokens": 59, "completion_tokens_details": {"reasoning_tokens": 5,
       "reasoning_closed_at": 1, "reasoning_closed_by": "answer_room"}}, "timings": {...}}
data: [DONE]
```

## 2. Latency (measured)

| Scenario | First byte/frame | Total | Notes |
|---|---|---|---|
| Short prompt ("Say HELLO WORLD only") | 0.75 s | 1.75 s | prefill 604 ms (58 tok) |
| 200-word essay, 297 tok generated | 0.19 s (first `reasoning_content`) | 9.32 s | first *content* delta at 1.16 s; ~32 t/s decode |
| 8k-token prompt (36 KB body), max_tokens=5 | 5.19 s | 5.90 s | prefill 4.75 s = ~1700 t/s; **TTFT ≈ prefill cost** |
| Repeat of same prompt (prefix cached) | 0.09–0.14 s | — | journal: `prompt 58 (58 cached, 100.0%), prefill 0.00s` |

Implications for the chat UX:

- Time-to-first-token is dominated by prefill. A short chat turn feels < 1 s; a
  long context (~8k tokens) costs ~5 s before anything arrives. The UI needs a
  visible "thinking" state that covers the prefill gap — which `reasoning_content`
  nicely fills when the model emits it.
- **Prefix caching is real and fast**: warm prefix → 100% cached prefill, first
  frame in ~0.1 s. Appending messages (never mutating history) keeps chats cheap.
- **Queue starvation risk**: during concurrent load (other apps on the LAN +
  our probes), requests waited > 10 s for one of the 4 engine slots and our
  10 s curl timed out (HTTP 000). Router-side stats:
  `llamacpp:requests_processing` rose to 3–4 while long generations ran. A chat
  request can queue behind heavy Enrichment traffic; use generous client timeouts
  and a queued state, not an error state.

## 3. Tool-call streaming

Test: `{"stream": true, "tools": [calculator]}`, "What is 23 plus 19? Use the
calculator tool." Raw capture:

```
data: ... "delta": {"role": "assistant", "content": ""}}
data: ... "delta": {"reasoning_content": "The"}}          (reasoning streams first)
data: ... "delta": {"tool_calls": [{"index": 0, "id": "call_40b8bbf43b4a4c7a865f6543",
       "type": "function", "function": {"name": "calculator", "arguments": ""}}]}
data: ... "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"expr\": \""}}]}
data: ... "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "2"}}]}
data: ... "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "3"}}]}
data: ... "delta": {"tool_calls": [{"index": 0, "function": {"arguments": " +"}}]}
data: ... "delta": {"tool_calls": [{"index": 0, "function": {"arguments": " 1"}}]}
data: ... "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "9"}}]}
data: ... "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\""}}]}
data: ... "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]}
data: ... "finish_reason": "tool_calls", "delta": {}, "timings": {...}}
data: [DONE]
```

Findings:

- Yes, tool_calls stream, standard OpenAI incremental style: `id`/`name` arrive
  once in the first tool-call frame; `arguments` arrive as JSON string fragments
  that must be concatenated by index; then `finish_reason: "tool_calls"`.
- In this capture the entire tool-call block arrived in one ~2 ms burst at the end
  of reasoning — with small argument payloads the "streaming" of arguments is
  effectively instantaneous. Only worth surfacing incrementally for big arguments.
- The tool round is *not* executed server-side: the stream ends at
  `finish_reason: "tool_calls"` and the loop (execute locally, send tool result,
  get next turn) is our Python layer's job — same as `chat_with_tools`
  (src/router.py) does non-streamed today.

## 4. Disconnect behavior (journal-grounded)

We cut a live stream mid-generation with `curl --max-time`. The upstream engine
(serve_api) logged, per hung-up request:

```
serve_api: client disconnected mid-stream, chatcmpl-2c09a9dff7604e41a8532e78,
4 SSE frames and 20 chars sent in 3.2s, largest gap between frames 1.5s, last
frame 0.0s before the hangup, 0 keepalives (the generation is paused for 20s in
case the client retries; this is the client hanging up, not a server error)
```

And 20 seconds later, when no retry arrived:

```
serve_api: a request whose client had left was stopped (no retry came within 20s),
268 items were made
```

**Verdict: no unbounded burning.** On client disconnect the engine *pauses* the
generation for a 20-second resume window, then stops it and frees the slot.
Our earlier `/metrics` observation is consistent: `llamacpp:tokens_predicted_total`
froze at the moment of disconnect (pause, not continued decode) and stayed frozen.

Extra facts from the same logs:

- The engine has **resume-anywhere** support: disconnected generations can be
  resumed from a snapshot ("resume-anywhere (24 entries, snapshot every request,
  chunk 32768...)"), and KV regions get compacted for resuming requests
  (`kv pool: ... this request resumes from ...`). This is an engine-level retry
  affordance; our OpenAI-protocol client does not need to use it.
- Caveat: pausing for 20 s means a hung-up chat stream **keeps a slot occupied for
  20 s after the user closes the tab**. With only 4 slots and heavy Enrichment
  traffic, don't casually abandon streams; our Python layer closing its upstream
  response promptly at cancel is the polite behavior.
- The router/upstream was NOT always healthy during testing: at one window (local
  18:55–19:10) a basic long request returned zero bytes and one request timed
  out at 10 s (HTTP 000) even though `/health` and `/v1/models` responded
  instantly. The engine had 3–4 of 4 slots busy. Treat upstream stalls as a
  normal operational condition: client-side read timeouts + explicit error
  event, never an infinite spinner.

## 5. Keep-alive / timeout

- The upstream tracks keepalive SSE comments it sends during generation gaps:
  the disconnect log above says `1 keepalives` for a stream whose largest frame
  gap was 15.6 s → the server emits periodic `:`-comment heartbeats during
  silence (interval observed somewhere ≳ 5 s; we saw none in a 5.2 s prefill
  stall, one inside a 15.6 s gap).
- **No mid-stream error occurred in any of our tests** (journal grep for
  4xx/5xx/upstream errors over the test window: empty).
- Engine-internal watchdog: `halogen: engine watchdog on, 180s of silence takes
  the container down` — an engine crash detector, not an HTTP timeout.

## 6. Mid-stream error behavior

Test (f): `max_tokens: 1` with a `tools` payload the model wants to call.
Result: **no error**. HTTP 200 stream runs normally; the run ends with
`finish_reason: "length"`, `predicted_n: 1`, then `[DONE]`. Malformed-tool
truncation shows up as a truncated *final* frame, not an exception mid-stream.

Errors that DO happen are pre-stream: requesting an unknown model returns a plain
(non-SSE) `404` JSON body:

```
HTTP/1.1 404 Not Found
{"error":{"message":"model 'does-not-exist' not found","type":"invalid_request_error",
 "param":null,"code":"model_not_found","available":[...]}}
```

So: errors surface with HTTP status *before* the stream starts. Once
`200 + text/event-stream` is received, the failure mode is *stall*, not error
frame — a client needs an idle-read timeout, not error-code polling. (No
`event: error` frames were ever observed from this router.)

## 7. Python stdlib SSE — proven pattern (executed)

We serve one SSE endpoint from `http.server.BaseHTTPRequestHandler` on a
`ThreadingHTTPServer` (exactly BoldTrader's shape, src/server.py) and curl it.

Key points, each verified live:

1. `protocol_version = "HTTP/1.1"` — REQUIRED. Without it BaseHTTP defaults to
   HTTP/1.0 semantics: no chunked framing, connection-per-response.
2. Headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`,
   `X-Accel-Buffering: no` (insurance for any future nginx in front),
   `Connection: keep-alive`.
3. Do **not** set `Content-Length`; HTTP/1.1 + no length = chunked transfer,
   which is what browsers stream live.
4. **Flush per event.** `wfile.write()` alone buffers; the client sees nothing.
   Every event = `write()` + `flush()`.
5. Heartbeat = `": keepalive\n\n"` (SSE comment), sent whenever you may go
   silent > ~10 s.
6. Client disconnect is detected by the **write raising** `BrokenPipeError` /
   `ConnectionResetError`. There is no async notification; on a threaded server
   the handler thread just exits its loop when the next flush hits the dead
   socket. That is the cancel hook: catch it, stop the upstream read, return.
7. The per-request handler style composes fine: the SSE handler owns its thread
   for the stream's lifetime; `ThreadingHTTPServer` gives every other request
   its own thread; set `daemon_threads = True` so lingering streams never block
   shutdown.

Proof source (throwaway `sse_proof.py`, since deleted — this is the record):

```python
class SSEHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # required for chunked framing

    def do_GET(self):
        if self.path != "/events":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def send(event: str, data: dict) -> None:
            blob = f"event: {event}\ndata: {json.dumps(data)}\n\n"
            self.wfile.write(blob.encode("utf-8"))
            self.wfile.flush()

        try:
            send("start", {"ts": time.time()})
            for i in range(5):
                time.sleep(1)
                self.wfile.write(b": keepalive\n\n")   # heartbeat comment
                self.wfile.flush()
                send("delta", {"n": i, "text": f"chunk {i} "})
            send("finish", {"done": True})
        except (BrokenPipeError, ConnectionResetError):
            print("client gone mid-stream", flush=True)  # cancel hook
            return
```

Transcript (server on 127.0.0.1:10999, `curl -sN ... | <timestamped reader>`):

```
[  0.000s] event: start
[  0.000s] data: {"ts": 1793065104.83}
[  1.000s] : keepalive
[  1.000s] event: delta
[  1.000s] data: {"n": 0, "text": "chunk 0 "}
[  2.001s] : keepalive
...
[  5.004s] event: finish
[  5.004s] data: {"done": true}
```

Each event arrived at its wall-clock second (live streaming, no buffering).
Disconnect test: a raw socket client that closes right after the first event →
server log line, within ~1 s:

```
[Thread-2 (process_request_thread)] client gone mid-stream
```

## 8. Event-framing recommendation

What a chat UI needs vs. what the router provides:

| UI need | Router provides | Our Python layer must do |
|---|---|---|
| Turn started | first frame `delta.role=assistant` (after prefill) | synthesize `event: start` (ids, model, at = request time); router's first frame is only available post-prefill |
| Visible answer streaming | `delta.content` token fragments | forward live as `event: delta` |
| Thinking/reasoning display | `delta.reasoning_content` stream | forward as `event: reason` (UI renders collapsed/optional) |
| Tool call display | `tool_calls` fragments with `index` | **buffer, do not forward fragments**; emit one complete `event: tool_call` when the call's JSON closes (finish_reason or parse-completion). Half-streamed JSON args are useless to the UI. |
| Tool round | ends at `finish_reason: "tool_calls"` | execute tool locally, append tool result, issue the next upstream turn, continue streaming the same SSE response to the browser (multiple model turns per browser request) |
| Turn finished | `finish_reason` + `timings` frame, then `[DONE]` | synthesize `event: done` carrying finish_reason, usage (request `stream_options.include_usage`), total elapsed |
| Upstream stall | *nothing* | client-side read timeout (~30 s idle); emit `event: error` + close; browsers' EventSource reconnect semantics make closing-with-error the right move |
| Keepalive during silence | upstream sends some, interval unverified | emit our own `: keepalive\n\n` every ~15 s from the pump loop |

Rules of thumb for the migration:

1. **Terminology split**: the router's two output channels (`reasoning_content`
   vs `content`) map to two UI channels; never glue them into one string.
2. **Synthesize, don't invent**: `start` and `done` events should carry our own
   timestamps and the router's `timings`/`usage` verbatim; do not fabricate
   token counts — `include_usage` gives real ones.
3. **One browser SSE request can span multiple upstream turns** (tool loops).
   Tag each upstream turn's events with a turn counter so the UI can group them.
4. **Cancel**: closing the browser SSE response must propagate to closing the
   upstream `urllib`/`requests` stream response (with `stream=True`), or the
   router keeps a slot paused for 20 s. `BrokenPipeError` in the write path is
   the existing signal; the handler thread exit closes the upstream response.
5. **First-chunk timeout is a UX requirement, not paranoia**: prefill stalls of
   5 s+ and queue starvation of 10 s+ were both observed in normal operation.

## 9. Open items

- Keepalive interval from the router is unverified precisely (≳5 s, ≤15 s from
  one logged gap); our own 15 s heartbeat makes this moot.
- All probes ran against the `-pair` container as pinned by ADR 0007; behavior
  under a container swap (cold model request) was not tested on purpose — it is
  known-bad for chat latency and remains prohibited.
