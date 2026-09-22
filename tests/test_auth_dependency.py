from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user_id
from app.core.errors import APIError, api_error_handler
from app.utils import security


@pytest.fixture
def client(database):
    app = FastAPI()
    app.add_exception_handler(APIError, api_error_handler)

    @app.get("/protected")
    def protected(user_id: str = Depends(get_current_user_id)):
        return {"id": user_id}

    with TestClient(app) as client:
        yield client


def test_existing_login_token(client, auth_headers):
    response = client.get("/protected", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"id": "alice"}


@pytest.mark.parametrize("kind", ["missing", "malformed", "expired", "forged", "no-exp", "no-id", "deleted", "numeric-id"])
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
    token = "broken" if kind == "malformed" else jwt.encode(claims, key, algorithm="HS256")
    headers = {} if kind == "missing" else {"Authorization": f"Bearer {token}"}
    response = client.get("/protected", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_unconfigured_auth_service(client, monkeypatch, auth_headers):
    monkeypatch.setattr(security, "KEY", None)
    assert client.get("/protected", headers=auth_headers).status_code == 503
