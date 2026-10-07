from app.modules.receipts.application.errors import FiscalProviderUnavailable


class UnconfiguredFiscalDocumentGateway:
    provider_code = None

    async def issue(self, request):
        raise FiscalProviderUnavailable()

    async def lookup(self, request):
        raise FiscalProviderUnavailable()
