from dataclasses import dataclass

from app.modules.cancellations.domain.models import (
    CancellationRequest,
    OrderCancellation,
)
from app.modules.payments.domain.refunds import Refund


@dataclass(frozen=True, kw_only=True, slots=True)
class RequestCreation:
    request: CancellationRequest
    created: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class CancellationOutcome:
    cancellation: OrderCancellation
    refund: Refund | None
