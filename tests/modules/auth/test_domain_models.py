from uuid import uuid4

import pytest

from app.modules.auth.domain.models import Principal, PrincipalType


def test_registered_principal_requires_user() -> None:
    with pytest.raises(ValueError, match="requires a user_id"):
        Principal(principal_type=PrincipalType.REGISTERED)


def test_registered_staff_principal_may_not_have_customer() -> None:
    user_id = uuid4()

    principal = Principal(
        principal_type=PrincipalType.REGISTERED,
        user_id=user_id,
    )

    assert principal.user_id == user_id
    assert principal.customer_id is None


def test_guest_principal_requires_customer_and_forbids_user() -> None:
    with pytest.raises(ValueError, match="requires a customer_id"):
        Principal(principal_type=PrincipalType.GUEST)

    with pytest.raises(ValueError, match="cannot have a user_id"):
        Principal(
            principal_type=PrincipalType.GUEST,
            user_id=uuid4(),
            customer_id=uuid4(),
        )
