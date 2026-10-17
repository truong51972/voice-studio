from pathlib import Path
import sys

SAMPLE_RATE = 16_000
WINDOW_SECONDS = 2.5
HOP_SECONDS = 0.5
DEFAULT_THRESHOLD = 0.60
MIN_WINDOW_RMS = 0.005
SMOOTHING_KERNEL = 3
MAX_MERGE_GAP_SECONDS = 0.75
MIN_MATCH_DURATION_SECONDS = 1.0

# PyInstaller exposes bundled data through sys._MEIPASS.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODEL_DIR = PROJECT_ROOT / "models"
SPEAKER_MODEL = MODEL_DIR / "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
