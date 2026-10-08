import asyncio

import pytest

from app.modules.auth.application.exceptions import TokenInvalidError
from app.modules.auth.infrastructure.security.passwords import (
    PwdlibArgon2PasswordHasher,
)
from app.modules.payments.application.errors import PaymentProviderUnavailableError
from app.modules.payments.presentation.dependencies import get_payment_gateway
from app.modules.payments.presentation.refund_dependencies import get_refund_gateway
from app.modules.receipts.presentation.router import get_fiscal_gateway
from app.shared.domain.time import utc_now
from tests.modules.auth.test_tokens import build_service, registered_principal


@pytest.mark.parametrize(
    "producer",
    [
        {"issuer": "foreign"},
        {"audience": "foreign"},
        {"secret": "foreign-test-signing-key-123456789XYZ"},
    ],
)
def test_jwt_signature_issuer_and_audience_fail_closed(producer):
    # This test runs near the end of the full suite: do not reuse import-time NOW.
    token = build_service(clock_time=utc_now(), **producer).create_access_token(
        registered_principal()
    )
    with pytest.raises(TokenInvalidError):
        build_service().decode_access_token(token)


def test_argon2_hash_cannot_be_used_as_plain_password():
    hasher = PwdlibArgon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    password = "TEST-secret-password-without-real-account"
    hashed = hasher.hash_password(password)
    assert hashed.startswith("$argon2id$") and password not in hashed
    assert hasher.verify_password(password, hashed)
    assert not hasher.verify_password(hashed, hashed)


def test_production_di_has_no_fake_payment_refund_fiscal_provider():
    assert type(get_payment_gateway()).__name__ == "UnconfiguredOnlinePaymentGateway"
    assert type(get_refund_gateway()).__name__ == "UnconfiguredOnlineRefundGateway"
    assert type(get_fiscal_gateway()).__name__ == "UnconfiguredFiscalDocumentGateway"
    with pytest.raises(PaymentProviderUnavailableError):
        _ = get_payment_gateway().provider_code
    with pytest.raises(PaymentProviderUnavailableError):
        asyncio.run(
            get_payment_gateway().verify_and_parse_webhook("test", b'{"paid":true}', {})
        )


@pytest.mark.parametrize("target", ["webhooks", "refund-webhooks"])
def test_unverified_webhooks_never_become_success(client, target):
    response = client.post(
        f"/api/v1/payments/{target}/unconfigured",
        json={"status": "PAID", "amount": "0.01"},
    )
    assert response.status_code == 503
