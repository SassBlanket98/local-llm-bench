from pack.spec import DISCOUNT_RATE


def line_total(quantity: int, unit_price_cents: int) -> int:
    subtotal = quantity * unit_price_cents
    # BUG: uses wrong rate interpretation (percent vs fraction)
    return subtotal - int(subtotal * DISCOUNT_RATE * 100)
