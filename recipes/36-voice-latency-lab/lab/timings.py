"""Turn timings from one post-prompt payload.

Source: the post-prompt payload the platform POSTs after each call (the SDK's
`PostPrompt` TypedDict in signalwire.core.post_prompt_generated). Assistant entries in
`raw_call_log` (falling back to `call_log`) carry:

  stamps_us.*            microsecond wall-clock stamps: last_word_end, status_pushed,
                         request_detect, first_token, first_utterance, first_audio
  eos_to_push_latency    last_word_end -> status_pushed      (turn detection)
  latency                request_detect -> first_token       (model)
  utterance_latency      request_detect -> first_utterance   (minus latency = assembly)
  audio_latency          request_detect -> first_audio       (minus utterance = TTS)

The gap status_pushed -> request_detect is the time before the LLM request that produced
the first audio: tool calls and earlier model passes. It is reported as tools_other_ms, so
turn detection + tools/other + model + assembly + TTS adds up to mouth-to-ear. (Checked on
live calls: first_audio - last_word_end equals the platform's acoustic_latency to within 1 ms.)

Method, per signalwire.com/docs/platform/ai/analytics ("Measure responsiveness"):
mouth-to-ear = first_audio - last_word_end. One value per caller turn: entries that share a
last_word_end anchor (a filler, a tool call and the final reply) count once, using the
earliest first_audio. A turn without both stamps is omitted, never estimated.
"""

SEGMENTS = ("mouth_to_ear_ms", "turn_detection_ms", "tools_other_ms", "model_ms", "assembly_ms", "tts_ms")


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _us_ms(value):
    v = _num(value)
    return v / 1000 if v is not None else None


def _diff(a, b):
    return round(a - b, 1) if a is not None and b is not None else None


def entry_timing(entry: dict) -> dict | None:
    stamps = entry.get("stamps_us") or {}
    last_word, first_audio = _num(stamps.get("last_word_end")), _num(stamps.get("first_audio"))
    if last_word is None or first_audio is None or first_audio < last_word:
        return None
    model, utter, audio = (_num(entry.get(k)) for k in ("latency", "utterance_latency", "audio_latency"))
    return {
        "anchor": int(last_word),
        "first_audio": int(first_audio),
        "mouth_to_ear_ms": round((first_audio - last_word) / 1000, 1),
        "turn_detection_ms": _num(entry.get("eos_to_push_latency")),
        "tools_other_ms": _diff(*(_us_ms(stamps.get(k)) for k in ("request_detect", "status_pushed"))),
        "model_ms": model,
        "assembly_ms": _diff(utter, model),
        "tts_ms": _diff(audio, utter),
    }


def parse_turns(payload: dict) -> tuple[list[dict], int]:
    """Return (turns, omitted): one dict per caller turn, ordered by anchor."""
    log = payload.get("raw_call_log") or payload.get("call_log") or []
    by_anchor, omitted = {}, 0
    for entry in log:
        if not isinstance(entry, dict) or entry.get("role") != "assistant":
            continue
        timing = entry_timing(entry)
        if timing is None:
            omitted += 1
            continue
        best = by_anchor.get(timing["anchor"])
        if best is None or timing["first_audio"] < best["first_audio"]:
            by_anchor[timing["anchor"]] = timing
    return [by_anchor[k] for k in sorted(by_anchor)], omitted


def config_of(payload: dict) -> str | None:
    return (payload.get("global_data") or {}).get("lab_config")
