def add(a: int, b: int) -> int:
    return a + b


def divide(a: int, b: int) -> float:
    # BUG: integer division
    return a // b
