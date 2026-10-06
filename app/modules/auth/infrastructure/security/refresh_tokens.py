from app.modules.auth.infrastructure.security.tokens import hash_refresh_token


class Sha256RefreshTokenHasher:
    def hash_token(self, token: str) -> str:
        return hash_refresh_token(token)
