"""Numeric validation shared by public configuration and snapshot boundaries."""

import math


def is_finite_number(value: object) -> bool:
    """Reject booleans, NaN/infinity and integers too large for runtime clocks."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
