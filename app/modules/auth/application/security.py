from typing import Protocol


class RefreshTokenHasher(Protocol):
    def hash_token(self, token: str) -> str:
        """Return a deterministic lookup digest for a high-entropy token."""
        ...
