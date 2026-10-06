"""SQLModel persistence mappings for customers and their addresses."""

from app.modules.customers.infrastructure.persistence.models import (
    CustomerAddressModel,
    CustomerModel,
    OtpChallengeModel,
)

__all__ = ["CustomerAddressModel", "CustomerModel", "OtpChallengeModel"]
