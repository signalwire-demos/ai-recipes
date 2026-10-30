| Config | Model | Voice | Calls | Turns | Mouth-to-ear p50 / p95 (ms) | Turn detection p50 / p95 (ms) | Tools / other p50 / p95 (ms) | Model p50 / p95 (ms) | Utterance assembly p50 / p95 (ms) | Audio (TTS) p50 / p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| mini-rime | gpt-4.1-mini | rime.spore | 1 | 2 (1 untimed) | 1250 / 1340 | 400 / 410 | 60 / 100 | 560 / 610 | 80 / 90 | 130 / 150 |
| nano-rime | gpt-4.1-nano | rime.spore | 2 | 4 (2 untimed) | 950 / 1120 | 400 / 450 | 30 / 70 | 300 / 350 | 70 / 80 | 140 / 170 |

Known issues:
- nano-rime: gpt-4.1-nano fails on some platform nodes: the REST call log shows calling_error model_not_found ('The model gpt-4.1-nano-2025-04-14 has been deprecated') on every assistant turn, then no tool call and no post-prompt. Seen on 4 of 7 live calls on 2026-10-30, with both rime.spore and gcloud voices; gpt-4.1-mini never failed. A failed call shows up as 'k of N' in Calls.
