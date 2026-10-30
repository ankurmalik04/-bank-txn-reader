# CAMT V02 schema regression fixtures

`valid_batch.camt053.xml` is independently synthetic test data. It uses the
CAMT.053.001.02 element order, simple `Sts`, and `TxDtls/AmtDtls/TxAmt/Amt`.
Tests also validate its `CntrValAmt` variants against the complete, unmodified
V02 XSD before parsing and checking reconciliation. No network is used by tests.

`camt.053.001.02.xsd` is the published SWIFT-generated ISO 20022
BankToCustomerStatementV02 schema (2009-01-08), downloaded on 2026-10-30 from:
https://raw.githubusercontent.com/genkgo/camt/master/assets/camt.053.001.02.xsd

Official catalogue: https://www.iso20022.org/catalogue-messages/iso-20022-messages-archive
Official download: https://www.iso20022.org/message/12706/download
(the official download returned HTTP 403 during retrieval).
SHA-256: `05ec472590dda5e433fd646e9cf3849fa1ba01c033052aaca3089cec6862692d`.

The `extension_batch` helper in `test_camt_financial_guards.py` deliberately
retains direct `TxDtls/Amt` and optional `TxDtls/CdtDbtInd` extension coverage.
Those inputs and malformed-input guard tests do not claim XSD conformance.
