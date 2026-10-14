from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        computed = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(computed, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_problem(password: str) -> str | None:
    if not 8 <= len(password) <= 1024:
        return "Use entre 8 e 1.024 caracteres na nova senha."
    if password.lower() in {"12345678", "123456789", "123456789012", "engageflow123", "abcdefghijkl", "password", "abcdefgh"}:
        return "Escolha uma senha diferente de sequências ou do nome da agência."
    return None
