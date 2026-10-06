from app.modules.auth.infrastructure.security.passwords import (
    PwdlibArgon2PasswordHasher,
)


def build_hasher(*, time_cost: int = 2) -> PwdlibArgon2PasswordHasher:
    return PwdlibArgon2PasswordHasher(
        time_cost=time_cost,
        memory_cost=1024,
        parallelism=1,
        hash_len=32,
        salt_len=16,
    )


def test_hash_and_verify_password_with_argon2() -> None:
    hasher = build_hasher()

    password_hash = hasher.hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2id$")
    assert hasher.verify_password("correct horse battery staple", password_hash)
    assert not hasher.verify_password("incorrect", password_hash)


def test_invalid_hash_is_rejected_without_leaking_adapter_error() -> None:
    hasher = build_hasher()

    assert not hasher.verify_password("password", "not-a-valid-hash")
    result = hasher.verify_and_rehash("password", "not-a-valid-hash")

    assert not result.is_valid
    assert result.updated_hash is None


def test_verify_and_rehash_upgrades_obsolete_argon2_parameters() -> None:
    old_hasher = build_hasher(time_cost=1)
    current_hasher = build_hasher(time_cost=2)
    old_hash = old_hasher.hash_password("password")

    result = current_hasher.verify_and_rehash("password", old_hash)

    assert result.is_valid
    assert result.needs_rehash
    assert result.updated_hash is not None
    assert current_hasher.verify_password("password", result.updated_hash)
