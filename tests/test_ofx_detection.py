from pathlib import Path

from bankparser.detection import detect_format, looks_like_ofx


def test_detects_ofx_from_contents() -> None:
    data = Path("corpus/ofx/basic_valid.ofx").read_bytes()
    assert looks_like_ofx(data)
    assert detect_format(data) == "ofx"


def test_detects_qfx_as_ofx_wire_format() -> None:
    data = Path("corpus/ofx/basic_valid.qfx").read_bytes()
    assert looks_like_ofx(data)
    assert detect_format(data) == "ofx"


def test_does_not_trust_ofx_header_without_statement_structure() -> None:
    assert not looks_like_ofx(b"OFXHEADER:100\n<OFX></OFX>\n")
