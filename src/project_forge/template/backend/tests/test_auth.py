from app.auth.security import (
    generate_token,
    hash_password,
    hash_token,
    token_matches,
    verify_password,
)


def test_opaque_tokens_are_hashed_and_constant_time_checked() -> None:
    token = generate_token()
    digest = hash_token(token)
    assert token not in digest
    assert token_matches(token, digest)
    assert not token_matches(token + "x", digest)


def test_argon2_password_round_trip() -> None:
    digest = hash_password("correct horse battery staple")
    assert verify_password(digest, "correct horse battery staple")
    assert not verify_password(digest, "wrong password")
