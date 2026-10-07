from app.modules.notifications.application.errors import PushProviderUnavailableError
from app.modules.notifications.domain.models import provider_code


class UnconfiguredPushGateway:
    provider_code = "unconfigured"

    async def send(self, message):
        raise PushProviderUnavailableError()


class ConfiguredPushGatewayRegistry:
    """Only deployment-supplied adapters can register provider support."""

    def __init__(self, gateways=()):
        self.gateways = {}
        for gateway in gateways:
            code = provider_code(gateway.provider_code)
            if code in self.gateways or isinstance(gateway, UnconfiguredPushGateway):
                raise ValueError("Invalid push gateway registry configuration")
            self.gateways[code] = gateway

    def provider_codes(self):
        return tuple(sorted(self.gateways))

    def resolve(self, provider):
        gateway = self.gateways.get(provider)
        if gateway is None or isinstance(gateway, UnconfiguredPushGateway):
            raise PushProviderUnavailableError()
        return gateway
