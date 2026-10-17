from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from html import escape
from typing import Iterable

import numpy as np

from .audio import GradioAudio, prepare_gradio_audio
from .config import (
    HOP_SECONDS,
    MAX_MERGE_GAP_SECONDS,
    MIN_MATCH_DURATION_SECONDS,
    MIN_WINDOW_RMS,
    SAMPLE_RATE,
    SMOOTHING_KERNEL,
    WINDOW_SECONDS,
)
from .embedding import SpeakerEmbedder
from .localization import MatchSegment, WindowScore, merge_matches, score_references
from .media import extract_audio_from_video
from .profiles import DEFAULT_PROFILE_KEY, InferenceProfile, get_inference_profile
from .visualization import (
    build_multi_speaker_timeline_figure,
    build_similarity_detail_figure,
    build_speaker_lanes_figure,
)


@dataclass(frozen=True)
class ReferenceVoice:
    key: str
    name: str
    samples: np.ndarray


@dataclass(frozen=True)
class SpeakerResult:
    key: str
    name: str
    scores: list[WindowScore]
    segments: list[MatchSegment]
    matched_duration: float
    coverage: float
    max_score: float | None


@dataclass(frozen=True)
class AnalysisBundle:
    target: np.ndarray
    media_kind: str
    duration: float
    results: list[SpeakerResult]
    scores_by_name: dict[str, list[WindowScore]]
    segments_by_name: dict[str, list[MatchSegment]]


@lru_cache(maxsize=4)
def get_embedder(profile_key: str = DEFAULT_PROFILE_KEY) -> SpeakerEmbedder:
    profile = get_inference_profile(profile_key)
    return SpeakerEmbedder(profile.model_path, num_threads=profile.num_threads)


def _resolve_profile_threshold(
    profile_key: str,
    threshold: float | None,
) -> tuple[InferenceProfile, float]:
    profile = get_inference_profile(profile_key)
    resolved_threshold = profile.default_threshold if threshold is None else float(threshold)
    return profile, resolved_threshold


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    remain = seconds - minutes * 60
    if minutes:
        return f"{minutes:02d}:{remain:04.1f}"
    return f"{remain:.1f}s"


def _validate_references(references: Iterable[tuple[str, GradioAudio]]) -> list[ReferenceVoice]:
    prepared: list[ReferenceVoice] = []
    seen_names: set[str] = set()
    for idx, (name, audio) in enumerate(references, start=1):
        label = (name or "").strip()
        if not label and audio is None:
            continue
        if not label:
            raise ValueError(f"Mẫu tham chiếu #{idx} đã có audio nhưng chưa có tên.")
        if audio is None:
            raise ValueError(f"Người nói '{label}' chưa có mẫu giọng tham chiếu.")

        normalized = label.casefold()
        if normalized in seen_names:
            raise ValueError(f"Tên người nói bị trùng: '{label}'. Hãy đặt tên khác nhau để đọc timeline rõ ràng.")
        seen_names.add(normalized)

        samples = prepare_gradio_audio(audio)
        if samples.size < int(1.0 * SAMPLE_RATE):
            raise ValueError(
                f"Mẫu giọng của '{label}' nên có ít nhất 1 giây tiếng nói; khuyến nghị 3–5 giây rõ tiếng."
            )
        prepared.append(ReferenceVoice(key=f"spk_{len(prepared) + 1:02d}", name=label, samples=samples))

    if not prepared:
        raise ValueError("Cần ít nhất một người nói tham chiếu có tên và mẫu giọng.")
    return prepared


def _prepare_target(target_audio: GradioAudio, target_video) -> tuple[np.ndarray, str]:
    if target_audio is not None and target_video is not None:
        raise ValueError("Chỉ chọn một target: audio hoặc video, không dùng đồng thời cả hai.")
    if target_video is not None:
        target = extract_audio_from_video(target_video, SAMPLE_RATE)
        media_kind = "video"
    elif target_audio is not None:
        target = prepare_gradio_audio(target_audio)
        media_kind = "audio"
    else:
        raise ValueError("Chưa có audio hoặc video cần phân tích.")

    if target.size < int(1.0 * SAMPLE_RATE):
        raise ValueError("Media cần phân tích quá ngắn.")
    return target, media_kind


def _compute_analysis(
    references: Iterable[tuple[str, GradioAudio]],
    target_audio: GradioAudio,
    target_video,
    threshold: float,
    *,
    profile_key: str = DEFAULT_PROFILE_KEY,
) -> AnalysisBundle:
    prepared_refs = _validate_references(references)
    target, media_kind = _prepare_target(target_audio, target_video)

    ref_samples = {ref.key: ref.samples for ref in prepared_refs}
    scores_by_key = score_references(
        ref_samples,
        target,
        get_embedder(profile_key),
        sample_rate=SAMPLE_RATE,
        window_seconds=WINDOW_SECONDS,
        hop_seconds=HOP_SECONDS,
        min_rms=MIN_WINDOW_RMS,
        smoothing_kernel=SMOOTHING_KERNEL,
    )

    duration = target.size / SAMPLE_RATE
    results: list[SpeakerResult] = []
    segments_by_name: dict[str, list[MatchSegment]] = {}
    scores_by_name: dict[str, list[WindowScore]] = {}

    for ref in prepared_refs:
        scores = scores_by_key[ref.key]
        segments = merge_matches(
            scores,
            float(threshold),
            max_gap_seconds=MAX_MERGE_GAP_SECONDS,
            min_duration_seconds=MIN_MATCH_DURATION_SECONDS,
        )
        matched_duration = sum(max(0.0, seg.end - seg.start) for seg in segments)
        coverage = 100.0 * matched_duration / duration if duration > 0 else 0.0
        max_score = max((seg.max_score for seg in segments), default=None)
        result = SpeakerResult(
            key=ref.key,
            name=ref.name,
            scores=scores,
            segments=segments,
            matched_duration=matched_duration,
            coverage=coverage,
            max_score=max_score,
        )
        results.append(result)
        scores_by_name[ref.name] = scores
        segments_by_name[ref.name] = segments

    return AnalysisBundle(
        target=target,
        media_kind=media_kind,
        duration=duration,
        results=results,
        scores_by_name=scores_by_name,
        segments_by_name=segments_by_name,
    )


def _build_kpis(results: list[SpeakerResult], duration: float, media_kind: str) -> str:
    detected = sum(1 for result in results if result.segments)
    total_segments = sum(len(result.segments) for result in results)
    media_label = "Video" if media_kind == "video" else "Audio"

    rows = []
    for result in results:
        peak = f"{result.max_score:.3f}" if result.max_score is not None else "—"
        status = "Có phát hiện" if result.segments else "Chưa phát hiện"
        rows.append(
            "<tr>"
            f"<td><strong>{escape(result.name)}</strong><span class='vl-speaker-status'>{status}</span></td>"
            f"<td>{len(result.segments)}</td>"
            f"<td>{_fmt_time(result.matched_duration)}</td>"
            f"<td>{result.coverage:.1f}%</td>"
            f"<td>{peak}</td>"
            "</tr>"
        )

    return f"""
    <div class="vl-result-overview">
      <span><strong>{len(results)}</strong> references</span>
      <span><strong>{detected}</strong> detected</span>
      <span><strong>{total_segments}</strong> matches</span>
      <span><strong>{_fmt_time(duration)}</strong> {media_label.lower()}</span>
    </div>
    <div class="vl-speaker-kpi-table-wrap">
      <table class="vl-speaker-kpi-table">
        <thead><tr><th>Người nói</th><th>Vùng</th><th>Thời lượng</th><th>Tỷ lệ</th><th>Peak</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """


def _build_segment_rows(results: list[SpeakerResult]) -> list[list[object]]:
    rows: list[list[object]] = []
    for result in results:
        for idx, seg in enumerate(result.segments, start=1):
            rows.append(
                [
                    result.name,
                    idx,
                    _fmt_time(seg.start),
                    _fmt_time(seg.end),
                    _fmt_time(max(0.0, seg.end - seg.start)),
                    round(seg.avg_score, 3),
                    round(seg.max_score, 3),
                ]
            )
    return rows


def _build_result_note(
    bundle: AnalysisBundle,
    scenario: str,
    threshold: float,
    profile: InferenceProfile,
) -> str:
    safe_context = escape((scenario or "Hoạt động học tập").strip())
    media_label = "video" if bundle.media_kind == "video" else "audio"
    total_segments = sum(len(result.segments) for result in bundle.results)
    detected = sum(1 for result in bundle.results if result.segments)

    if total_segments:
        headline = f"Phát hiện **{total_segments} vùng** trên **{detected}/{len(bundle.results)} reference speakers**."
    else:
        headline = "Chưa có speaker nào vượt ngưỡng hiện tại."

    return (
        f"{headline}  \n"
        f"Bối cảnh: **{safe_context}** · Target: **{media_label}** · Profile: **{profile.label}** · "
        f"Threshold: **{float(threshold):.2f}**.  \n"
        "Matching được thực hiện độc lập theo từng reference. Click một hàng segment để đưa player tới đúng timestamp."
    )


def analyze_workspace(
    references: Iterable[tuple[str, GradioAudio]],
    target_audio: GradioAudio,
    target_video,
    threshold: float | None,
    *,
    scenario: str = "Hoạt động học tập",
    profile_key: str = DEFAULT_PROFILE_KEY,
):
    """Media-first UI contract introduced in v0.4.0."""
    profile, resolved_threshold = _resolve_profile_threshold(profile_key, threshold)
    bundle = _compute_analysis(
        references,
        target_audio,
        target_video,
        resolved_threshold,
        profile_key=profile.key,
    )
    lanes = build_speaker_lanes_figure(bundle.duration, bundle.segments_by_name)
    details = build_similarity_detail_figure(
        bundle.target,
        SAMPLE_RATE,
        bundle.scores_by_name,
        resolved_threshold,
    )
    return (
        lanes,
        details,
        _build_result_note(bundle, scenario, resolved_threshold, profile),
        _build_kpis(bundle.results, bundle.duration, bundle.media_kind),
        _build_segment_rows(bundle.results),
    )


def analyze_many(
    references: Iterable[tuple[str, GradioAudio]],
    target_audio: GradioAudio,
    target_video,
    threshold: float | None,
    *,
    scenario: str = "Hoạt động học tập",
    include_segment_rows: bool = False,
    profile_key: str = DEFAULT_PROFILE_KEY,
):
    profile, resolved_threshold = _resolve_profile_threshold(profile_key, threshold)
    bundle = _compute_analysis(
        references,
        target_audio,
        target_video,
        resolved_threshold,
        profile_key=profile.key,
    )

    figure = build_multi_speaker_timeline_figure(
        bundle.target,
        SAMPLE_RATE,
        bundle.scores_by_name,
        bundle.segments_by_name,
        resolved_threshold,
    )
    kpis = _build_kpis(bundle.results, bundle.duration, bundle.media_kind)

    safe_context = escape((scenario or "Hoạt động học tập").strip())
    media_label = "video" if bundle.media_kind == "video" else "audio"
    lines = [
        "### Kết quả định vị nhiều người nói",
        f"Bối cảnh: **{safe_context}** · Target: **{media_label}** · Profile: **{profile.label}** · "
        f"Threshold: **{resolved_threshold:.2f}**",
        "",
        "Mỗi người nói được đối sánh **độc lập** với cùng một tập target-window embeddings. "
        "Một khoảng thời gian có thể xuất hiện ở nhiều speaker nếu nhiều score cùng vượt threshold; đây không phải full speaker diarization.",
        "",
        "| Người nói | Vùng | Khoảng thời gian | Similarity TB | Cao nhất |",
        "|---|---:|---|---:|---:|",
    ]

    any_segment = False
    for result in bundle.results:
        if not result.segments:
            lines.append(f"| **{escape(result.name)}** | — | Không phát hiện | — | — |")
            continue
        for idx, seg in enumerate(result.segments, start=1):
            any_segment = True
            lines.append(
                f"| **{escape(result.name)}** | {idx} | {_fmt_time(seg.start)} → {_fmt_time(seg.end)} | "
                f"{seg.avg_score:.3f} | {seg.max_score:.3f} |"
            )

    if not any_segment:
        lines.extend(
            [
                "",
                "Chưa có speaker nào vượt ngưỡng hiện tại. Có thể thử mẫu tham chiếu rõ hơn hoặc giảm threshold trong phần thiết lập nâng cao.",
            ]
        )

    lines.extend(
        [
            "",
            "> **Lưu ý:** kết quả là tín hiệu đối sánh giọng nói để hỗ trợ tìm đoạn cần xem lại; không phải xác nhận danh tính tuyệt đối và không dùng thời lượng nói như điểm chất lượng/đóng góp.",
        ]
    )
    outputs = (figure, "\n".join(lines), kpis)
    if include_segment_rows:
        return (*outputs, _build_segment_rows(bundle.results))
    return outputs


def analyze(
    reference_audio: GradioAudio,
    target_audio: GradioAudio,
    threshold: float,
    *,
    speaker_label: str = "Người nói tham chiếu",
    scenario: str = "Hoạt động học tập",
    profile_key: str = DEFAULT_PROFILE_KEY,
):
    """Backward-compatible v0.2.x API."""
    return analyze_many(
        [(speaker_label, reference_audio)],
        target_audio,
        None,
        threshold,
        scenario=scenario,
        profile_key=profile_key,
    )
