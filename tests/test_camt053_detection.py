from pathlib import Path

from bankparser.detection import detect_format, looks_like_camt053

FIXTURE = Path("corpus/camt053/basic_valid.camt053.xml")


def test_detects_camt053_from_contents() -> None:
    data = FIXTURE.read_bytes()
    assert looks_like_camt053(data)
    assert detect_format(data) == "camt053"
