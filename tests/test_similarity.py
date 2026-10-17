import numpy as np

from voice_studio.similarity import cosine_similarity, moving_average


def test_cosine_identity():
    x = np.array([1.0, 2.0, 3.0])
    assert cosine_similarity(x, x) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert cosine_similarity(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(0.0)


def test_moving_average_preserves_length():
    values = np.array([0.0, 1.0, 0.0, 1.0, 0.0])
    assert moving_average(values, 3).shape == values.shape


import pytest
