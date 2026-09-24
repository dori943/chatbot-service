from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.dependencies import get_token_id
from app.core.errors import APIError, api_error_handler
from app.services import auth
from app.utils import security


@pytest.fixture
def client(database):
    app = FastAPI()
    app.add_exception_handler(APIError, api_error_handler)

    @app.get("/protected")
    def protected(user_id: str = Depends(get_token_id)):
        return {"id": user_id}

    with TestClient(app) as client:
        yield client


def test_existing_login_token(client, auth_headers):
    response = client.get("/protected", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"id": "alice"}


@pytest.mark.parametrize("kind", ["missing", "malformed", "expired", "forged", "no-exp", "no-id", "deleted", "numeric-id", "empty-id", "long-id"])
def test_rejects_invalid_identity(client, kind):
    claims = {"id": "alice", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    key = security.KEY
    if kind == "expired":
        claims["exp"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    elif kind == "forged":
        key = "different-test-signing-key-at-least-32-bytes"
    elif kind == "no-exp":
        del claims["exp"]
    elif kind == "no-id":
        del claims["id"]
    elif kind == "deleted":
        claims["id"] = "missing-user"
    elif kind == "numeric-id":
        claims["id"] = 123
    elif kind == "empty-id":
        claims["id"] = ""
    elif kind == "long-id":
        claims["id"] = "a" * 51
    token = "broken" if kind == "malformed" else jwt.encode(claims, key, algorithm="HS256")
    headers = {} if kind == "missing" else {"Authorization": f"Bearer {token}"}
    response = client.get("/protected", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_unconfigured_auth_service(client, monkeypatch, auth_headers):
    monkeypatch.setattr(security, "KEY", None)
    response = client.get("/protected", headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["error_code"] == "AUTH_UNAVAILABLE"


def test_database_failure_is_not_an_invalid_login(client, monkeypatch, auth_headers):
    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("test database unavailable")

    monkeypatch.setattr(auth, "check_user", unavailable)
    response = client.get("/protected", headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["error_code"] == "DB_UNAVAILABLE"


def test_invalid_token_does_not_query_user(client, monkeypatch):
    def unexpected_query(*args, **kwargs):
        pytest.fail("Invalid tokens must be rejected before querying the user")

    monkeypatch.setattr(auth, "check_user", unexpected_query)
    response = client.get("/protected", headers={"Authorization": "Bearer broken"})
    assert response.status_code == 401
