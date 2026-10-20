from pathlib import Path

import pytest

from bankparser.detection import detect_format, looks_like_mt940
from bankparser.detection.ofx import looks_like_ofx
from bankparser.errors import UnsupportedFormatError

FIXTURE = Path("corpus/mt940/basic_valid.mt940")


def test_detects_mt940_from_contents() -> None:
    data = FIXTURE.read_bytes()
    assert looks_like_mt940(data)
    assert detect_format(data) == "mt940"


def test_detects_structural_mt940_with_missing_balance() -> None:
    assert (
        detect_format(Path("corpus/mt940/missing_opening_balance.mt940").read_bytes())
        == "mt940"
    )
    assert (
        detect_format(Path("corpus/mt940/missing_closing_balance.mt940").read_bytes())
        == "mt940"
    )


def test_does_not_trust_random_colon_tags() -> None:
    with pytest.raises(UnsupportedFormatError):
        detect_format(b":61:not enough evidence\n")


def test_invalid_utf16_ofx_is_not_detected() -> None:
    assert not looks_like_ofx(b"\xff\xfe\x00")
