from fastapi.testclient import TestClient


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_register_and_login(client: TestClient):
    resp = client.post("/auth/register", json={
        "email": "testuser@example.com",
        "password": "TestPass123",
        "role": "user",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "testuser@example.com"
    assert data["role"] == "user"

    resp2 = client.post("/auth/login", json={
        "email": "testuser@example.com",
        "password": "TestPass123",
    })
    assert resp2.status_code == 200
    token_data = resp2.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"


def test_register_duplicate_email(client: TestClient):
    client.post("/auth/register", json={
        "email": "dup@example.com",
        "password": "pass",
        "role": "user",
    })
    resp = client.post("/auth/register", json={
        "email": "dup@example.com",
        "password": "pass",
        "role": "user",
    })
    assert resp.status_code == 409


def test_upload_requires_auth(client: TestClient):
    import io
    resp = client.post("/v1/files/upload", files={"file": ("test.pdf", io.BytesIO(b"data"), "application/pdf")})
    assert resp.status_code == 401


def test_admin_usage_requires_admin(client: TestClient):
    # Register a regular user
    client.post("/auth/register", json={"email": "regular@example.com", "password": "pass", "role": "user"})
    login = client.post("/auth/login", json={"email": "regular@example.com", "password": "pass"})
    token = login.json()["access_token"]

    resp = client.get("/v1/admin/usage", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
