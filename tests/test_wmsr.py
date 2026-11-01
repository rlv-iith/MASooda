"""Unit tests for scalar and vector W-MSR filtering."""

from __future__ import annotations

import numpy as np

from resilience.wmsr import wmsr_scalar, wmsr_vector


def test_scalar_trims_largest_value_above_own():
    assert wmsr_scalar(0.0, [1, 2, 3, 100], f=1) == np.mean([0, 1, 2, 3])


def test_scalar_trims_smallest_value_below_own():
    # The lower outlier and the largest value above own are both trimmed.
    assert wmsr_scalar(0.0, [-100, 1, 2, 3], f=1) == np.mean([0, 1, 2])


def test_scalar_with_zero_faults_is_plain_mean():
    assert wmsr_scalar(2.0, [1.0, 3.0, 4.0], f=0) == np.mean([2.0, 1.0, 3.0, 4.0])


def test_too_few_reports_use_median_fallback():
    assert wmsr_scalar(0.0, [100.0, 2.0], f=1) == np.median([0.0, 100.0, 2.0])
    result = wmsr_vector(np.array([0.0, 10.0]), [np.array([100.0, 20.0])], f=1)
    np.testing.assert_array_equal(result, np.median([[0.0, 10.0], [100.0, 20.0]], axis=0))


def test_vector_filters_each_coordinate_independently():
    own = np.array([0.0, 0.0])
    values = [np.array([1.0, -1.0]), np.array([2.0, -2.0]),
              np.array([3.0, -3.0]), np.array([100.0, -100.0])]
    result = wmsr_vector(own, values, f=1)
    np.testing.assert_allclose(result, np.array([1.5, -1.5]))
