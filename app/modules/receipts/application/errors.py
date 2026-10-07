from app.shared.application.exceptions import DependencyUnavailableError


class FiscalProviderUnavailable(DependencyUnavailableError):
    code = "FISCAL_PROVIDER_UNAVAILABLE"

    def __init__(self):
        super().__init__(
            "Fiscal provider is unavailable; no document has been simulated"
        )
