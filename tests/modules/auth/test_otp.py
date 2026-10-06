import asyncio
import hashlib
import hmac
import logging

import pytest

from app.modules.auth.domain.models import OtpPurpose
from app.modules.auth.infrastructure.security.otp import HmacOtpCodeService
from app.modules.auth.infrastructure.security.otp_sender import InMemoryOtpSender


def test_otp_generation_uses_secure_randbelow_and_zero_padding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = HmacOtpCodeService(pepper="test-pepper", digits=6)
    calls: list[int] = []

    def fake_randbelow(upper_bound: int) -> int:
        calls.append(upper_bound)
        return 42

    monkeypatch.setattr("secrets.randbelow", fake_randbelow)

    assert service.generate_code() == "000042"
    assert calls == [1_000_000]


def test_otp_hash_uses_hmac_sha256_and_verifies_safely() -> None:
    service = HmacOtpCodeService(pepper="private-pepper", digits=6)
    expected = hmac.new(
        b"private-pepper",
        b"123456",
        digestmod=hashlib.sha256,
    ).hexdigest()

    code_hash = service.hash_code("123456")

    assert code_hash == expected
    assert service.verify_code("123456", code_hash)
    assert not service.verify_code("654321", code_hash)
    assert not service.verify_code("12345", code_hash)


def test_otp_rejects_invalid_configuration_and_hash_input() -> None:
    with pytest.raises(ValueError, match="pepper"):
        HmacOtpCodeService(pepper="")
    with pytest.raises(ValueError, match="digits"):
        HmacOtpCodeService(pepper="pepper", digits=3)

    service = HmacOtpCodeService(pepper="pepper")
    with pytest.raises(ValueError, match="format"):
        service.hash_code("abcdef")


def test_in_memory_sender_captures_only_in_development_or_test(
    caplog: pytest.LogCaptureFixture,
) -> None:
    code = "123456"
    with caplog.at_level(logging.DEBUG):
        sender = InMemoryOtpSender(environment="test")
        asyncio.run(
            sender.send_otp(
                phone="+51912345678",
                purpose=OtpPurpose.REGISTER,
                code=code,
            )
        )

    assert len(sender.deliveries) == 1
    assert sender.deliveries[0].code == code
    assert code not in caplog.text
    assert code not in repr(sender.deliveries[0])

    with pytest.raises(ValueError, match="only available"):
        InMemoryOtpSender(environment="production")  # type: ignore[arg-type]
