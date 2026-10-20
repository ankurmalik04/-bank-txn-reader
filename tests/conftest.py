"""Full canonical projections shared by the conformance suites."""

import pytest

from bankparser.serialization import to_primitive


@pytest.fixture
def canonical_core():
    def project(result):
        transactions = []
        for transaction in result.transactions:
            item = to_primitive(transaction)
            item.pop("raw")
            transactions.append(item)
        return {
            "account": to_primitive(result.account),
            "statement": to_primitive(result.statement),
            "transactions": transactions,
            "validation_status": result.validation.status,
            "validation_checks": [
                {
                    key: getattr(check, key)
                    for key in ("code", "status", "expected", "actual")
                }
                for check in result.validation.checks
            ],
            "warning_codes": sorted(warning.code for warning in result.warnings),
        }

    return project
