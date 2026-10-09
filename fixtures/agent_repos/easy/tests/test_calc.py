from calc.core import add, divide


def test_add():
    assert add(2, 3) == 5


def test_divide():
    assert divide(5, 2) == 2.5
