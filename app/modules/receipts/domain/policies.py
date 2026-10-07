import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal

RECIPIENT_FIELDS = {
    "recipient_document_type",
    "recipient_document_number",
    "recipient_name",
    "recipient_address",
}


def fiscal_request(values: dict) -> tuple[dict, str]:
    if set(values) - (RECIPIENT_FIELDS | {"document_type"}) or values.get(
        "document_type"
    ) not in {"BOLETA", "FACTURA"}:
        raise ValueError("Invalid fiscal request")
    normalized = {"document_type": values["document_type"]}
    for key in RECIPIENT_FIELDS:
        value = values.get(key)
        maximum = (
            1000
            if key == "recipient_address"
            else 180
            if key == "recipient_name"
            else 32
            if key == "recipient_document_number"
            else 16
        )
        if value is not None:
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value.strip()) > maximum
                or any(ord(c) < 32 for c in value)
            ):
                raise ValueError("Invalid recipient data")
            value = value.strip()
        normalized[key] = value
    if normalized["document_type"] == "FACTURA":
        if (
            normalized["recipient_document_type"] != "RUC"
            or not re.fullmatch(
                r"[0-9]{11}", normalized["recipient_document_number"] or ""
            )
            or not normalized["recipient_name"]
            or not normalized["recipient_address"]
        ):
            raise ValueError("Factura requires structural RUC, name and address")
    fingerprint = hashlib.sha256(
        json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    return normalized, fingerprint


def paid_order(order) -> bool:
    return (
        order.status != "CANCELLED"
        and order.payment_status == "PAID"
        and order.ledger_status == "PAID"
        and isinstance(order.paid_amount, Decimal)
        and order.paid_amount.is_finite()
        and order.paid_amount == order.total
        and Decimal("0.00") <= order.paid_amount <= Decimal("9999999999.99")
    )


def aware_time(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )
