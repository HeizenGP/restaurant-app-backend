from dataclasses import dataclass, field
from typing import Literal

from app.modules.auth.domain.models import OtpPurpose

DebugEnvironment = Literal["development", "test"]


@dataclass(frozen=True, slots=True)
class OtpDelivery:
    phone: str = field(repr=False)
    purpose: OtpPurpose
    code: str = field(repr=False)


class InMemoryOtpSender:
    """Capture OTPs for development/tests without using logs or a real provider."""

    __slots__ = ("_deliveries", "_environment")

    def __init__(self, *, environment: DebugEnvironment) -> None:
        if environment not in {"development", "test"}:
            raise ValueError(
                "The in-memory OTP sender is only available in development or test"
            )
        self._environment = environment
        self._deliveries: list[OtpDelivery] = []

    @property
    def deliveries(self) -> tuple[OtpDelivery, ...]:
        return tuple(self._deliveries)

    async def send_otp(self, *, phone: str, purpose: OtpPurpose, code: str) -> None:
        self._deliveries.append(OtpDelivery(phone=phone, purpose=purpose, code=code))

    def clear(self) -> None:
        self._deliveries.clear()
