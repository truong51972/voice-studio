from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.colors import qualitative
from plotly.subplots import make_subplots

from .localization import MatchSegment, WindowScore


_COLORS = qualitative.Safe + qualitative.Set2


def _waveform(target: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    max_points = 5000
    stride = max(1, target.size // max_points)
    y = target[::stride]
    x = np.arange(y.size) * stride / sample_rate
    return x, y




def build_timeline_placeholder_figure() -> go.Figure:
    """Stable always-mounted placeholder for the primary speaker timeline."""
    fig = go.Figure()
    fig.add_annotation(
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        text="Timeline sẽ xuất hiện sau khi Analyze",
        showarrow=False,
        font={"size": 12, "color": "#64748b"},
    )
    fig.update_xaxes(visible=False, range=[0, 1], fixedrange=True)
    fig.update_yaxes(visible=False, range=[0, 1], fixedrange=True)
    fig.update_layout(
        height=220,
        margin={"l": 16, "r": 16, "t": 10, "b": 10},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        showlegend=False,
    )
    return fig

def build_speaker_lanes_figure(
    duration: float,
    segments_by_speaker: dict[str, list[MatchSegment]],
) -> go.Figure:
    """Primary review view: answer only the product question "who appears where?"."""
    names = list(segments_by_speaker)
    fig = go.Figure()

    for idx, name in enumerate(names):
        color = _COLORS[idx % len(_COLORS)]
        segments = segments_by_speaker.get(name, [])

        # A quiet baseline makes speakers with no detections legible too.
        fig.add_trace(
            go.Scatter(
                x=[0, duration],
                y=[idx, idx],
                mode="lines",
                line={"width": 2, "color": "#e2e8f0"},
                hoverinfo="skip",
                showlegend=False,
            )
        )

        for seg_idx, seg in enumerate(segments, start=1):
            fig.add_trace(
                go.Scatter(
                    x=[seg.start, seg.end],
                    y=[idx, idx],
                    mode="lines",
                    line={"width": 18, "color": color},
                    name=name,
                    legendgroup=name,
                    showlegend=False,
                    customdata=[
                        [seg_idx, seg.avg_score, seg.max_score, seg.start, seg.end],
                        [seg_idx, seg.avg_score, seg.max_score, seg.start, seg.end],
                    ],
                    hovertemplate=(
                        f"<b>{name}</b><br>"
                        "Đoạn %{customdata[0]}<br>"
                        "%{customdata[3]:.1f}s → %{customdata[4]:.1f}s<br>"
                        "TB %{customdata[1]:.3f} · peak %{customdata[2]:.3f}<extra></extra>"
                    ),
                )
            )

    fig.update_yaxes(
        tickmode="array",
        tickvals=list(range(len(names))),
        ticktext=names,
        range=[-0.6, max(0.6, len(names) - 0.4)],
        zeroline=False,
        showgrid=False,
        fixedrange=True,
    )
    fig.update_xaxes(
        range=[0, max(0.1, duration)],
        title_text="Thời gian (giây)",
        showgrid=True,
        gridcolor="#edf2f7",
        zeroline=False,
    )
    fig.update_layout(
        height=max(220, 100 + len(names) * 40),
        margin={"l": 105, "r": 18, "t": 14, "b": 42},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": "Arial, sans-serif", "color": "#17233b", "size": 12},
        hovermode="closest",
        showlegend=False,
    )
    return fig


def build_similarity_detail_figure(
    target: np.ndarray,
    sample_rate: int,
    scores_by_speaker: dict[str, list[WindowScore]],
    threshold: float,
) -> go.Figure:
    """Secondary/research view: waveform + similarity curves."""
    duration = target.size / sample_rate
    names = list(scores_by_speaker)
    x_wave, y_wave = _waveform(target, sample_rate)

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.12,
        row_heights=[0.34, 0.66],
        subplot_titles=("Audio track của media", "Cosine similarity theo thời gian"),
    )
    fig.add_trace(
        go.Scatter(
            x=x_wave,
            y=y_wave,
            mode="lines",
            name="Biên độ audio",
            line={"width": 1.0, "color": "#64748b"},
            hovertemplate="%{x:.1f}s<extra>Audio</extra>",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    for idx, name in enumerate(names):
        color = _COLORS[idx % len(_COLORS)]
        scores = scores_by_speaker[name]
        fig.add_trace(
            go.Scatter(
                x=[score.center for score in scores],
                y=[score.score for score in scores],
                mode="lines",
                name=name,
                legendgroup=name,
                line={"width": 2, "color": color},
                hovertemplate=f"<b>{name}</b><br>%{{x:.1f}}s · similarity %{{y:.3f}}<extra></extra>",
            ),
            row=2,
            col=1,
        )

    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="#b45309",
        annotation_text=f"Ngưỡng {threshold:.2f}",
        annotation_position="top right",
        row=2,
        col=1,
    )

    fig.update_yaxes(title_text="Biên độ", row=1, col=1, zeroline=False)
    fig.update_yaxes(range=[-0.05, 1.05], title_text="Similarity", row=2, col=1, zeroline=False)
    fig.update_xaxes(range=[0, duration], title_text="Thời gian (giây)", row=2, col=1)
    fig.update_layout(
        height=520,
        margin={"l": 74, "r": 24, "t": 62, "b": 58},
        legend={"orientation": "h", "y": -0.16, "x": 0},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        font={"family": "Arial, sans-serif", "color": "#17233b"},
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#e8eef5")
    fig.update_yaxes(showgrid=True, gridcolor="#e8eef5")
    return fig


def build_multi_speaker_timeline_figure(
    target: np.ndarray,
    sample_rate: int,
    scores_by_speaker: dict[str, list[WindowScore]],
    segments_by_speaker: dict[str, list[MatchSegment]],
    threshold: float,
) -> go.Figure:
    """Backward-compatible v0.3.x combined diagnostic view."""
    duration = target.size / sample_rate
    names = list(scores_by_speaker)
    x_wave, y_wave = _waveform(target, sample_rate)

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.09,
        row_heights=[0.28, 0.32, 0.40],
        subplot_titles=(
            "Audio track của media",
            "Vị trí speaker được phát hiện",
            "Cosine similarity theo thời gian",
        ),
    )
    fig.add_trace(
        go.Scatter(
            x=x_wave,
            y=y_wave,
            mode="lines",
            name="Biên độ audio",
            line={"width": 1.0, "color": "#64748b"},
            hovertemplate="%{x:.1f}s<extra>Audio</extra>",
        ),
        row=1,
        col=1,
    )

    for idx, name in enumerate(names):
        color = _COLORS[idx % len(_COLORS)]
        segments = segments_by_speaker.get(name, [])
        for seg_idx, seg in enumerate(segments, start=1):
            fig.add_trace(
                go.Scatter(
                    x=[seg.start, seg.end],
                    y=[idx, idx],
                    mode="lines",
                    line={"width": 14, "color": color},
                    name=name,
                    legendgroup=name,
                    showlegend=False,
                    customdata=[[seg_idx, seg.avg_score, seg.max_score], [seg_idx, seg.avg_score, seg.max_score]],
                    hovertemplate=(
                        f"<b>{name}</b><br>"
                        "Vùng %{customdata[0]}<br>"
                        "%{x:.1f}s<br>"
                        "TB %{customdata[1]:.3f} · peak %{customdata[2]:.3f}<extra></extra>"
                    ),
                ),
                row=2,
                col=1,
            )

        scores = scores_by_speaker[name]
        fig.add_trace(
            go.Scatter(
                x=[score.center for score in scores],
                y=[score.score for score in scores],
                mode="lines",
                name=name,
                legendgroup=name,
                line={"width": 2, "color": color},
                hovertemplate=f"<b>{name}</b><br>%{{x:.1f}}s · similarity %{{y:.3f}}<extra></extra>",
            ),
            row=3,
            col=1,
        )

    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="#b45309",
        annotation_text=f"Ngưỡng {threshold:.2f}",
        annotation_position="top right",
        row=3,
        col=1,
    )

    fig.update_yaxes(title_text="Biên độ", row=1, col=1, zeroline=False)
    fig.update_yaxes(
        tickmode="array",
        tickvals=list(range(len(names))),
        ticktext=names,
        range=[-0.65, max(0.65, len(names) - 0.35)],
        title_text="Speaker",
        row=2,
        col=1,
        zeroline=False,
    )
    fig.update_yaxes(range=[-0.05, 1.05], title_text="Similarity", row=3, col=1, zeroline=False)
    fig.update_xaxes(range=[0, duration], title_text="Thời gian (giây)", row=3, col=1)
    fig.update_layout(
        height=max(720, 660 + len(names) * 24),
        margin={"l": 90, "r": 30, "t": 82, "b": 60},
        legend={"orientation": "h", "y": -0.12, "x": 0},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        font={"family": "Arial, sans-serif", "color": "#17233b"},
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#e8eef5")
    fig.update_yaxes(showgrid=True, gridcolor="#e8eef5")
    return fig


def build_timeline_figure(
    target: np.ndarray,
    sample_rate: int,
    scores: list[WindowScore],
    segments: list[MatchSegment],
    threshold: float,
    *,
    speaker_label: str = "Người nói tham chiếu",
) -> go.Figure:
    """Backward-compatible single-speaker wrapper."""
    return build_multi_speaker_timeline_figure(
        target,
        sample_rate,
        {speaker_label: scores},
        {speaker_label: segments},
        threshold,
    )
