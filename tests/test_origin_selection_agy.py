import copy
import struct
import pytest
from sps.origin_data import numeric_pair

SHEET = {
    'columns': [
        {'sheet_raw': 0, 'data': [None, 1.0000000000000002, -0.0, None]},
        {'sheet_raw': 0, 'data': [None, 3.0, 4.0, None, None]},
    ]
}


def test_numeric_pair_default_range_rejects_unequal_capacities():
    sheet = copy.deepcopy(SHEET)
    with pytest.raises(ValueError):
        numeric_pair(sheet, 0, 1)
    with pytest.raises(ValueError):
        numeric_pair(sheet, 0, 1, None)


def test_numeric_pair_explicit_range_immutability_and_missing():
    sheet = copy.deepcopy(SHEET)
    original = copy.deepcopy(sheet)
    x, y = numeric_pair(sheet, 0, 1, [1, 3])
    assert x == [1.0000000000000002, -0.0]
    assert y == [3.0, 4.0]
    assert struct.pack('>d', x[0]) == struct.pack('>d', 1.0000000000000002)
    assert struct.pack('>d', x[1]) == struct.pack('>d', -0.0)
    assert struct.pack('>d', x[1]) != struct.pack('>d', 0.0)
    assert sheet == original
    with pytest.raises(ValueError):
        numeric_pair(sheet, 0, 1, [0, 3])


@pytest.mark.parametrize(
    'invalid_range', [[True, 3], [1.0, 3], [2, 2], [-1, 2], [1, 6]]
)
def test_numeric_pair_invalid_ranges(invalid_range):
    sheet = copy.deepcopy(SHEET)
    with pytest.raises(ValueError):
        numeric_pair(sheet, 0, 1, invalid_range)
