def data_range(values: list[float]) -> float:
    if not values:
        return 0.0
    # BUG: off-by-one on max
    return max(values) - min(values) - 1
