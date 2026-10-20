from bankparser.detection import detect_format, looks_like_csv


def test_detects_bank_statement_csv_from_headers() -> None:
    data = b"Booking Date,Description,Amount,Currency\n2026-10-01,Salary,1000.00,GBP\n"
    assert looks_like_csv(data)
    assert detect_format(data) == "csv"


def test_detects_semicolon_csv_with_split_amount_columns() -> None:
    data = (
        "Date opération;Libellé;Débit;Crédit;Devise\n"
        "2026-10-01;Coffee;4.50;;EUR\n"
    ).encode()
    assert looks_like_csv(data)
    assert detect_format(data) == "csv"


def test_rejects_generic_non_financial_csv() -> None:
    assert not looks_like_csv(b"product,category\nChair,Furniture\n")
    assert not looks_like_csv(b"foo,amount\nbar,10\n")
