def add_tax(cents: int, rate: float) -> int:
    # BUG: truncates instead of rounding
    return cents + int(cents * rate)
