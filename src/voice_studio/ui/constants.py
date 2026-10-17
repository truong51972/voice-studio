from __future__ import annotations

"""Product-level editor defaults; no widget imports."""

from ..profiles import INFERENCE_PROFILES

SCENARIOS = [
    "Họp / hội thảo",
    "Phỏng vấn / thảo luận",
    "Podcast / bản ghi âm",
    "Khác",
]

PROFILE_CHOICES = [(profile.label, profile.key) for profile in INFERENCE_PROFILES.values()]
DEFAULT_REFERENCE_SPEAKERS = 1
MAX_REFERENCE_SPEAKERS = 3
SEGMENT_HEADERS = ["Người nói", "Bắt đầu", "Kết thúc", "Peak"]
