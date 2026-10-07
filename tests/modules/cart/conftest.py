import asyncio

import pytest

from tests.modules.cart.fakes import CartSetup, cart_setup


@pytest.fixture
def setup() -> CartSetup:
    return asyncio.run(cart_setup())
