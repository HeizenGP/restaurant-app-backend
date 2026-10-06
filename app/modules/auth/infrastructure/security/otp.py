import hashlib
import hmac
import secrets


class HmacOtpCodeService:
    """Generate numeric OTPs and protect them with a server-side pepper."""

    __slots__ = ("_digits", "_pepper", "_upper_bound")

    def __init__(self, *, pepper: str | bytes, digits: int = 6) -> None:
        if not 4 <= digits <= 10:
            raise ValueError("OTP digits must be between 4 and 10")

        encoded_pepper = pepper.encode("utf-8") if isinstance(pepper, str) else pepper
        if not encoded_pepper:
            raise ValueError("OTP pepper cannot be empty")

        self._digits = digits
        self._pepper = encoded_pepper
        self._upper_bound = 10**digits

    @property
    def digits(self) -> int:
        return self._digits

    def generate_code(self) -> str:
        value = secrets.randbelow(self._upper_bound)
        return f"{value:0{self._digits}d}"

    def hash_code(self, code: str) -> str:
        if not self._has_valid_format(code):
            raise ValueError("OTP code has an invalid format")
        return self._digest(code)

    def verify_code(self, code: str, code_hash: str) -> bool:
        candidate_hash = self._digest(code)
        hashes_match = hmac.compare_digest(candidate_hash, code_hash)
        return self._has_valid_format(code) and hashes_match

    def _digest(self, code: str) -> str:
        return hmac.new(
            self._pepper,
            code.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

    def _has_valid_format(self, code: str) -> bool:
        return len(code) == self._digits and code.isascii() and code.isdecimal()
