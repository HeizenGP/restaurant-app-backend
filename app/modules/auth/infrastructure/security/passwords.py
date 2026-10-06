from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from pwdlib.hashers.argon2 import Argon2Hasher

from app.modules.auth.application.types import PasswordVerificationResult


class PwdlibArgon2PasswordHasher:
    """Argon2 password adapter with parameters supplied at composition time."""

    __slots__ = ("_password_hash",)

    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost: int = 65536,
        parallelism: int = 4,
        hash_len: int = 32,
        salt_len: int = 16,
    ) -> None:
        argon2 = Argon2Hasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=hash_len,
            salt_len=salt_len,
        )
        self._password_hash = PasswordHash((argon2,))

    def hash_password(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return self._password_hash.verify(password, password_hash)
        except (PwdlibError, ValueError):
            return False

    def verify_and_rehash(
        self, password: str, password_hash: str
    ) -> PasswordVerificationResult:
        try:
            is_valid, updated_hash = self._password_hash.verify_and_update(
                password, password_hash
            )
        except (PwdlibError, ValueError):
            return PasswordVerificationResult(is_valid=False)

        return PasswordVerificationResult(
            is_valid=is_valid,
            updated_hash=updated_hash if is_valid else None,
        )
