from __future__ import annotations

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


def cosine_similarity_matrix(references: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Return [num_references, num_targets] cosine similarities."""
    refs = np.asarray(references, dtype=np.float32)
    tgts = np.asarray(targets, dtype=np.float32)
    if refs.ndim != 2 or tgts.ndim != 2:
        raise ValueError("Cosine matrix yêu cầu hai ma trận 2 chiều.")
    if refs.shape[1] != tgts.shape[1]:
        raise ValueError("Reference và target embedding phải có cùng số chiều.")
    if refs.shape[0] == 0 or tgts.shape[0] == 0:
        return np.zeros((refs.shape[0], tgts.shape[0]), dtype=np.float32)

    ref_norms = np.linalg.norm(refs, axis=1, keepdims=True)
    tgt_norms = np.linalg.norm(tgts, axis=1, keepdims=True)
    safe_refs = refs / np.maximum(ref_norms, 1e-12)
    safe_tgts = tgts / np.maximum(tgt_norms, 1e-12)
    return (safe_refs @ safe_tgts.T).astype(np.float32)


def moving_average(values: np.ndarray, kernel: int = 3) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    if kernel <= 1 or values.size < kernel:
        return values.copy()
    kernel = int(kernel)
    weights = np.ones(kernel, dtype=np.float32) / kernel
    padded = np.pad(values, (kernel // 2, kernel - 1 - kernel // 2), mode="edge")
    return np.convolve(padded, weights, mode="valid").astype(np.float32)
