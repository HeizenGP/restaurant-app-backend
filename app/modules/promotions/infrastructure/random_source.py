import secrets


class SecretsRandomSource:
    def draw(self) -> int:
        return secrets.randbelow(10000)
