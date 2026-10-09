from stats.mean import mean
from stats.median import median
from stats.range import data_range


def test_mean():
    assert mean([1, 2, 3]) == 2.0


def test_median_odd():
    assert median([1, 3, 9]) == 3


def test_median_even():
    assert median([1, 2, 3, 4]) == 2.5


def test_range():
    assert data_range([2, 5, 9]) == 7
