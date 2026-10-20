from datetime import date
from decimal import Decimal

from bankparser.models import (
    Account,
    ParseResult,
    SourceMetadata,
    Statement,
    Transaction,
    ValidationResult,
)
from bankparser.serialization import to_primitive


def test_decimal_and_date_serialize_as_strings() -> None:
    result = ParseResult(
        schema_version="1.0",
        source=SourceMetadata("mt940", "test", "1", "0.1.0"),
        account=Account(currency="GBP"),
        statement=Statement(opening_balance=Decimal("10.00")),
        transactions=(
            Transaction(
                booking_date=date(2026, 10, 1),
                value_date=date(2026, 10, 1),
                amount=Decimal("-2.50"),
                currency="GBP",
            ),
        ),
        validation=ValidationResult(status="passed"),
    )
    primitive = to_primitive(result)
    assert primitive["statement"]["opening_balance"] == "10.00"
    assert primitive["transactions"][0]["booking_date"] == "2026-10-01"
    assert primitive["transactions"][0]["amount"] == "-2.50"
