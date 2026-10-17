"""Reproducible local STT evaluation; no guessed accuracy or GPU metrics."""
from __future__ import annotations

import json
import platform
import re
import sys
import time
import unicodedata
from pathlib import Path


def edit_distance(reference: list | str, hypothesis: list | str) -> int:
    """Levenshtein edit distance with O(min(n,m)) memory."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    prev = list(range(len(hypothesis) + 1))
    for i, expected in enumerate(reference, 1):
        row = [i]
        for j, actual in enumerate(hypothesis, 1):
            row.append(min(
                row[-1] + 1, prev[j] + 1,
                prev[j - 1] + int(expected != actual),
            ))
        prev = row
    return prev[-1]


def normalize(text: str) -> str:
    """Unicode NFC + casefold + punctuation removal; retain Vietnamese tones."""
    text = unicodedata.normalize("NFC", text).casefold()
    return re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE).strip()


def error_counts(reference: str, hypothesis: str) -> dict:
    ground = normalize(reference)
    predicted = normalize(hypothesis)
    gt_words, hyp_words = ground.split(), predicted.split()
    gt_chars = list("".join(ground.split()))
    hyp_chars = list("".join(predicted.split()))
    return {
        "word_errors": edit_distance(gt_words, hyp_words),
        "word_count": len(gt_words),
        "char_errors": edit_distance(gt_chars, hyp_chars),
        "char_count": len(gt_chars),
    }


def aggregate(counts: list[dict]) -> dict:
    totals = {
        key: sum(x[key] for x in counts)
        for key in ("word_errors", "word_count", "char_errors", "char_count")
    }
    return {
        **totals,
        "wer": totals["word_errors"] / totals["word_count"] if totals["word_count"] else None,
        "cer": totals["char_errors"] / totals["char_count"] if totals["char_count"] else None,
    }


def evaluate_fixture(fixture: list[dict], outputs: dict[str, dict]) -> dict:
    rows = []
    for example in fixture:
        name = example["source"]
        result = outputs[name]
        predicted = " ".join(row["text"] for row in result["segments"])
        counts = error_counts(example["reference"], predicted)
        rows.append({"source": name, **counts})
    return {"aggregate": aggregate(rows), "samples": rows}


def run_benchmark(samples: list[dict], *, model_id: str, language: str = "vi", vad: bool = True) -> dict:
    """Opt-in real-model smoke run with wall time/RTF and measured process RSS.

    GPU usage is returned as unavailable unless a dedicated provider probe is
    integrated; process RSS only reports Python + native max resident pages.
    """
    from .stt import STTOptions, transcribe
    from .model_registry import get_model, preflight
    options = STTOptions(model_id=model_id, language=language, vad=vad)
    blockers = preflight(get_model(model_id), device="cpu")
    if blockers:
        raise RuntimeError("; ".join(blockers))
    rows, counts = [], []
    try:
        import resource
    except ImportError:
        resource = None
    for sample in samples:
        begin = time.perf_counter()
        result = transcribe(sample["source"], options)
        elapsed = time.perf_counter() - begin
        predicted = " ".join(s["text"] for s in result["segments"])
        count = error_counts(sample["reference"], predicted)
        counts.append(count)
        duration = result["duration"]
        memory_bytes = None
        if resource is not None:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Linux ru_maxrss is KiB; macOS reports bytes.
            memory_bytes = int(usage if sys.platform == "darwin" else usage * 1024)
        rows.append({
            "source": sample["source"], **count,
            "duration_seconds": duration,
            "elapsed_seconds": elapsed,
            "real_time_factor": elapsed / duration if duration else None,
            "peak_process_rss_bytes": memory_bytes,
            "peak_gpu_vram_bytes": None,
            "result": result,
        })
    return {
        "model_id": model_id, "language": language, "vad": vad,
        "hardware": {
            "platform": platform.platform(), "cpu": platform.processor(),
            "python": platform.python_version(),
        },
        "aggregate": aggregate(counts), "samples": rows,
        "notes": (
            "WER is whitespace-token based (Vietnamese syllables, not lexical segmentation); "
            "CER preserves Vietnamese diacritics; process memory is maximum RSS; "
            "VRAM not measured. RTF includes model loading time."
        ),
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Voice Studio Vietnamese STT evaluation")
    parser.add_argument("--fixtures", type=Path, required=True,
                        help="Consented JSON array with source and reference text")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="whisper-small")
    parser.add_argument("--language", choices=["auto", "vi", "en"], default="vi")
    args = parser.parse_args()
    examples = json.loads(args.fixtures.read_text(encoding="utf-8"))
    if not isinstance(examples, list) or not examples:
        parser.error("Fixtures must contain at least one example")
    results = run_benchmark(examples, model_id=args.model, language=args.language)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}; aggregate WER={results['aggregate']['wer']}, CER={results['aggregate']['cer']}")


if __name__ == "__main__":
    main()
