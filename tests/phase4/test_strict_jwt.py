from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient
import jwt
import pytest

from egp_api.auth import (
    JwtValidationPolicy,
    authenticate_bearer_request,
    authenticate_request,
)
from egp_api.config import get_jwt_clock_skew_seconds
from tests.support.app_factory import create_test_app
from tests.support.jwt_factory import (
    TEST_JWT_AUDIENCE,
    TEST_JWT_ISSUER,
    mint_machine_jwt,
)


JWT_SECRET = "strict-jwt-test-secret-at-least-32-bytes"
TENANT_ID = "11111111-1111-1111-1111-111111111111"
POLICY = JwtValidationPolicy(
    issuer=TEST_JWT_ISSUER,
    audience=TEST_JWT_AUDIENCE,
    clock_skew_seconds=30,
)


def _authenticate(token: str):
    return authenticate_bearer_request(
        authorization_header=f"Bearer {token}",
        jwt_secret=JWT_SECRET,
        validation_policy=POLICY,
    )


def _claims(**overrides):
    now = int(time.time())
    claims = {
        "iss": TEST_JWT_ISSUER,
        "aud": TEST_JWT_AUDIENCE,
        "exp": now + 300,
        "iat": now,
        "sub": "machine-user",
        "tenant_id": TENANT_ID,
    }
    claims.update(overrides)
    return claims


def _encode(claims: dict, *, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, JWT_SECRET, algorithm=algorithm)


def _compact_with_raw_json(header: str, payload: str) -> str:
    def segment(raw: str) -> str:
        return base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()

    signing_input = f"{segment(header)}.{segment(payload)}"
    signature = hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    return f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def test_strict_bearer_accepts_required_direct_and_registered_claims() -> None:
    token = mint_machine_jwt(secret=JWT_SECRET, tenant_id=TENANT_ID, role="analyst")

    context = _authenticate(token)

    assert context.tenant_id == TENANT_ID
    assert context.subject == "user-123"
    assert context.role == "analyst"


@pytest.mark.parametrize("claim", ("iss", "aud", "exp", "sub", "tenant_id"))
def test_strict_bearer_rejects_missing_required_claim(claim: str) -> None:
    claims = _claims()
    del claims[claim]

    with pytest.raises(Exception) as caught:
        _authenticate(_encode(claims))

    assert caught.value.status_code == 401
    assert caught.value.detail == "invalid bearer token"


@pytest.mark.parametrize(
    ("overrides", "algorithm"),
    [
        ({"iss": "wrong"}, "HS256"),
        ({"aud": "wrong"}, "HS256"),
        ({"aud": [TEST_JWT_AUDIENCE]}, "HS256"),
        ({"sub": 123}, "HS256"),
        ({"tenant_id": [TENANT_ID]}, "HS256"),
        ({"role": ["admin"]}, "HS256"),
        ({"exp": str(int(time.time()) + 300)}, "HS256"),
        ({}, "HS384"),
    ],
)
def test_strict_bearer_rejects_wrong_policy_or_claim_shape(
    overrides: dict, algorithm: str
) -> None:
    with pytest.raises(Exception) as caught:
        _authenticate(_encode(_claims(**overrides), algorithm=algorithm))

    assert caught.value.status_code == 401
    assert caught.value.detail == "invalid bearer token"


def test_clock_skew_accepts_inside_and_rejects_outside_boundary() -> None:
    now = int(time.time())
    assert _authenticate(_encode(_claims(exp=now - 20))).subject == "machine-user"

    with pytest.raises(Exception) as caught:
        _authenticate(_encode(_claims(exp=now - 40)))

    assert caught.value.detail == "invalid bearer token"


def test_duplicate_registered_or_direct_json_members_are_rejected() -> None:
    now = int(time.time())
    payload = (
        '{"iss":"%s","aud":"%s","exp":%d,"sub":"user",'
        '"tenant_id":"%s","tenant_id":"%s"}'
        % (TEST_JWT_ISSUER, TEST_JWT_AUDIENCE, now + 300, TENANT_ID, TENANT_ID)
    )
    token = _compact_with_raw_json('{"alg":"HS256","typ":"JWT"}', payload)

    with pytest.raises(Exception) as caught:
        _authenticate(token)

    assert caught.value.detail == "invalid bearer token"


def test_duplicate_algorithm_header_is_rejected() -> None:
    payload = json.dumps(_claims(), separators=(",", ":"))
    token = _compact_with_raw_json(
        '{"alg":"HS256","alg":"HS256","typ":"JWT"}', payload
    )

    with pytest.raises(Exception) as caught:
        _authenticate(token)

    assert caught.value.detail == "invalid bearer token"


@pytest.mark.parametrize(
    "token",
    (
        "not-a-jwt",
        "abc.def.ghi",
        _compact_with_raw_json('"HS256"', "{}"),
        _compact_with_raw_json('{"alg":"HS256"}', "[]"),
    ),
)
def test_malformed_or_non_object_jose_values_are_rejected(token: str) -> None:
    with pytest.raises(Exception) as caught:
        _authenticate(token)

    assert caught.value.detail == "invalid bearer token"


@pytest.mark.parametrize("segment_index", (0, 1, 2))
@pytest.mark.parametrize("character", ("=", "+", "/"))
def test_noncanonical_compact_segment_alphabet_is_rejected(
    segment_index: int, character: str
) -> None:
    token = mint_machine_jwt(secret=JWT_SECRET, tenant_id=TENANT_ID)
    segments = token.split(".")
    segments[segment_index] += character
    malformed = ".".join(segments)

    with pytest.raises(Exception) as caught:
        _authenticate(malformed)

    assert caught.value.detail == "invalid bearer token"


def test_tampered_well_formed_signature_is_rejected() -> None:
    token = mint_machine_jwt(secret=JWT_SECRET, tenant_id=TENANT_ID)
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"

    with pytest.raises(Exception) as caught:
        _authenticate(tampered)

    assert caught.value.detail == "invalid bearer token"


def test_unsigned_none_algorithm_is_rejected() -> None:
    token = jwt.encode(_claims(), key="", algorithm="none")

    with pytest.raises(Exception) as caught:
        _authenticate(token)

    assert caught.value.detail == "invalid bearer token"


@pytest.mark.parametrize("claim", ("iat", "nbf"))
def test_optional_temporal_claims_are_strict_integers(claim: str) -> None:
    with pytest.raises(Exception) as caught:
        _authenticate(_encode(_claims(**{claim: str(int(time.time()))})))

    assert caught.value.detail == "invalid bearer token"


@pytest.mark.parametrize("claim", ("iat", "nbf"))
def test_future_temporal_claims_obey_clock_skew(claim: str) -> None:
    now = int(time.time())
    assert _authenticate(_encode(_claims(**{claim: now + 20}))).subject == "machine-user"

    with pytest.raises(Exception) as caught:
        _authenticate(_encode(_claims(**{claim: now + 40})))

    assert caught.value.detail == "invalid bearer token"


@pytest.mark.parametrize(
    "kwargs",
    (
        {"issuer": "", "audience": TEST_JWT_AUDIENCE, "clock_skew_seconds": 30},
        {"issuer": TEST_JWT_ISSUER, "audience": " audience ", "clock_skew_seconds": 30},
        {"issuer": TEST_JWT_ISSUER, "audience": TEST_JWT_AUDIENCE, "clock_skew_seconds": True},
        {"issuer": TEST_JWT_ISSUER, "audience": TEST_JWT_AUDIENCE, "clock_skew_seconds": 121},
    ),
)
def test_policy_object_enforces_security_invariants(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        JwtValidationPolicy(**kwargs)


def test_invalid_bearer_does_not_fall_back_to_session() -> None:
    session_calls: list[str] = []

    with pytest.raises(Exception) as caught:
        authenticate_request(
            authorization_header="Bearer invalid",
            session_token="valid-session",
            jwt_secret=JWT_SECRET,
            jwt_validation_policy=POLICY,
            session_authenticator=lambda token: session_calls.append(token),
        )

    assert caught.value.status_code == 401
    assert session_calls == []


@pytest.mark.parametrize("value", (-1, 121, "bad", True))
def test_clock_skew_configuration_is_bounded(value) -> None:
    with pytest.raises(RuntimeError, match="EGP_JWT_CLOCK_SKEW_SECONDS"):
        get_jwt_clock_skew_seconds(value)


def test_duplicate_authorization_headers_fail_closed(tmp_path) -> None:
    app = create_test_app(
        artifact_root=tmp_path,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'strict.sqlite3'}",
        auth_required=True,
        jwt_secret=JWT_SECRET,
        background_runtime_mode="external",
    )
    token = mint_machine_jwt(secret=JWT_SECRET, tenant_id=TENANT_ID)

    response = TestClient(app).get(
        "/v1/me",
        headers=[("Authorization", f"Bearer {token}"), ("Authorization", f"Bearer {token}")],
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid bearer token"}
