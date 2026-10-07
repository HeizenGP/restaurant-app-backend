"""Fail closed until an actual provider and its verification contract are selected."""

from collections.abc import Mapping

from app.modules.payments.application.dtos import (
    GatewayAttemptRequest,
    GatewayAttemptResult,
    VerifiedPaymentEvent,
)
from app.modules.payments.application.errors import PaymentProviderUnavailableError


class UnconfiguredOnlinePaymentGateway:
    @property
    def provider_code(self) -> str:
        raise PaymentProviderUnavailableError()

    async def create_payment_attempt(
        self, request: GatewayAttemptRequest
    ) -> GatewayAttemptResult:
        raise PaymentProviderUnavailableError()

    async def verify_and_parse_webhook(
        self, provider_code: str, raw_body: bytes, headers: Mapping[str, str]
    ) -> VerifiedPaymentEvent:
        raise PaymentProviderUnavailableError()
