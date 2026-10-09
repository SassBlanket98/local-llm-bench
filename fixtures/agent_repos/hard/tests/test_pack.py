from pack.discount import line_total
from pack.tax import add_tax


def test_line_total():
    assert line_total(2, 500) == 900


def test_tax_rounds():
    assert add_tax(100, 0.075) == 108
