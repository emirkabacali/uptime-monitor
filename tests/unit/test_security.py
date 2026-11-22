from datetime import timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    hashed = hash_password("s3cret-password")

    assert hashed != "s3cret-password"
    assert verify_password("s3cret-password", hashed)
    assert not verify_password("wrong-password", hashed)


def test_same_password_gets_different_hashes() -> None:
    # A random salt per hash: equal passwords do not produce equal hashes.
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_against_invalid_hash_is_false() -> None:
    assert not verify_password("anything", "!")
    assert not verify_password("anything", None)


def test_token_roundtrip() -> None:
    assert decode_token(create_access_token(42)) == 42


def test_expired_token_is_rejected() -> None:
    token = create_access_token(42, expires_delta=timedelta(seconds=-1))

    with pytest.raises(InvalidTokenError):
        decode_token(token)


def test_token_with_wrong_signature_is_rejected() -> None:
    token = jwt.encode({"sub": "42", "exp": 9999999999, "type": "access"}, "x" * 40, "HS256")

    with pytest.raises(InvalidTokenError):
        decode_token(token)


def test_unsigned_token_is_rejected() -> None:
    token = jwt.encode({"sub": "42", "exp": 9999999999, "type": "access"}, None, algorithm="none")

    with pytest.raises(InvalidTokenError):
        decode_token(token)


def test_token_with_wrong_type_is_rejected() -> None:
    secret = get_settings().jwt_secret.get_secret_value()
    token = jwt.encode({"sub": "42", "exp": 9999999999, "type": "refresh"}, secret, "HS256")

    with pytest.raises(InvalidTokenError):
        decode_token(token)
