def test_register_user(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "register@example.com", "password": "securepassword"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "register@example.com"
    assert "id" in data
    assert data["is_active"] is True


def test_register_duplicate_user(client):
    email = "dup@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"}
    )
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "A user with this email already exists."


def test_login_for_access_token(client):
    email = "login@example.com"
    password = "password123"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": password}
    )
    
    response = client.post(
        "/api/auth/token",
        data={"username": email, "password": password}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_credentials(client):
    response = client.post(
        "/api/auth/token",
        data={"username": "wrong@example.com", "password": "wrongpassword"}
    )
    assert response.status_code == 401
    assert "detail" in response.json()


def test_get_me(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"
