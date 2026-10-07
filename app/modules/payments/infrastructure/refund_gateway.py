from app.modules.payments.application.refund_errors import (
    RefundProviderUnavailableError,
)


class UnconfiguredOnlineRefundGateway:
    @property
    def provider_code(self):
        raise RefundProviderUnavailableError()

    async def refund(self, request):
        raise RefundProviderUnavailableError()

    async def verify_and_parse_webhook(self, provider_code, raw_body, headers):
        raise RefundProviderUnavailableError()
