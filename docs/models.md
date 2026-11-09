# Model client

Status: built for Phase 3 item 1. No agent uses it yet.

`services/models/` is the only place the platform talks to a model.

- **Local only (SEC-2.1).** `LocalClient` accepts `localhost`, loopback and private IP addresses and
  refuses everything else at construction. It makes no DNS lookup and ignores proxy environment
  variables. Set `MODEL_ENDPOINT` and `MODEL_NAME` (see `.env.example`). Any OpenAI-compatible
  server works (Ollama, llama.cpp server, LM Studio).
- **Untrusted text (SEC-2.2).** Legacy text goes in `Request.untrusted` and is placed in
  `<<<UNTRUSTED label>>>` blocks after a fixed guard sentence. `<<<` inside legacy text is
  defanged so it cannot close its block. The request has no tools or functions and
  temperature 0. Delimiting lowers injection risk but does not remove it; the verifier (V-1..V-10)
  is the real defence because it checks every claim against the snapshot.
- **Timeout (OPS-1.1).** 120 s, read from `rules_constants.yaml`. Any failure raises `ModelError`;
  retries belong to the job runner, not the client.
- **Logging (NFR-6).** `logged_complete` writes a `model_calls` row: model, prompt hash, token
  counts, latency, run ID. Never prompt or reply text.
- **CI (SEC-2.3).** `FakeClient` returns canned replies. `RecordingClient` wraps a live local
  client and saves replies keyed by prompt hash; `RecordedClient` replays them and raises
  `MissingRecording` if the prompt changed. CI never uses `LocalClient` against a real model.

## Benchmark

`scripts/model_benchmark.py` is standalone (standard library only, no platform imports), so it
runs on plain Windows. It sends three small Business Rule-style tasks to a local server and
writes `model-benchmark.json`: median and max latency, tokens per second, timeouts, valid JSON,
whether cited lines exist, whether the model said "unknown" when the code cannot tell, and
whether it obeyed an instruction hidden in the code. The file holds numbers only.

It is a smoke test, not an accuracy measure. Accuracy on real rules comes from the Phase 3 eval
against the answer key. Pass thresholds for choosing a model are not set; the first results
decide them (open decision for the operator).
