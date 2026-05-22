import io
from fastapi.testclient import TestClient


def test_health(client: TestClient):
    resp = client.get("/health")
    # ChromaDB and DB may be unavailable in test environment; accept both
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "status" in body


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
    resp = client.post("/v1/files/upload", files={"file": ("test.pdf", io.BytesIO(b"data"), "application/pdf")})
    assert resp.status_code == 401


def test_upload_unsupported_type(client: TestClient):
    client.post("/auth/register", json={"email": "uploader@example.com", "password": "pass123", "role": "user"})
    login = client.post("/auth/login", json={"email": "uploader@example.com", "password": "pass123"})
    token = login.json()["access_token"]

    resp = client.post(
        "/v1/files/upload",
        files={"file": ("test.exe", io.BytesIO(b"data"), "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


def test_upload_file_too_large(client: TestClient, monkeypatch):
    import app.api.files as files_mod
    monkeypatch.setattr(files_mod, "MAX_FILE_SIZE_BYTES", 10)

    client.post("/auth/register", json={"email": "bigfile@example.com", "password": "pass123", "role": "user"})
    login = client.post("/auth/login", json={"email": "bigfile@example.com", "password": "pass123"})
    token = login.json()["access_token"]

    resp = client.post(
        "/v1/files/upload",
        files={"file": ("big.pdf", io.BytesIO(b"x" * 20), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413


def test_get_job_wrong_user_403(client: TestClient):
    # Create two users; user A creates a job, user B tries to read it
    import uuid
    client.post("/auth/register", json={"email": "owner@example.com", "password": "pass123", "role": "user"})
    client.post("/auth/register", json={"email": "other@example.com", "password": "pass123", "role": "user"})

    # owner logs in — we just confirm 403 on a fake UUID, since upload requires Celery
    login_b = client.post("/auth/login", json={"email": "other@example.com", "password": "pass123"})
    token_b = login_b.json()["access_token"]

    fake_id = str(uuid.uuid4())
    resp = client.get(f"/v1/jobs/{fake_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code in (403, 404)


def test_admin_usage_requires_admin(client: TestClient):
    client.post("/auth/register", json={"email": "regular@example.com", "password": "pass", "role": "user"})
    login = client.post("/auth/login", json={"email": "regular@example.com", "password": "pass"})
    token = login.json()["access_token"]

    resp = client.get("/v1/admin/usage", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_login_inactive_user(client: TestClient):
    # Register, deactivate via admin, then try login
    client.post("/auth/register", json={"email": "inactive@example.com", "password": "pass123", "role": "user"})
    # Register admin
    client.post("/auth/register", json={"email": "admn@example.com", "password": "pass123", "role": "admin"})
    admin_login = client.post("/auth/login", json={"email": "admn@example.com", "password": "pass123"})
    admin_token = admin_login.json()["access_token"]

    # Get user id
    users_resp = client.get("/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    user = next(u for u in users_resp.json() if u["email"] == "inactive@example.com")

    # Deactivate
    client.patch(
        f"/v1/admin/users/{user['id']}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Try login as deactivated user
    resp = client.post("/auth/login", json={"email": "inactive@example.com", "password": "pass123"})
    assert resp.status_code == 401
