import os
import tempfile

import pytest

from app import app


@pytest.fixture
def client():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    app.config.update(TESTING=True, DATABASE=path, SECRET_KEY="test")
    with app.app_context():
        from app import init_db
        init_db()
    with app.test_client() as client:
        yield client
    os.unlink(path)


def register(client, email="a@example.com"):
    return client.post("/register", data={"email": email, "password": "password123"}, follow_redirects=True)


def test_register_login_and_order(client):
    response = register(client)
    assert "注册成功" in response.get_data(as_text=True)
    response = client.post("/login", data={"email": "a@example.com", "password": "password123"}, follow_redirects=True)
    assert "控制台" in response.get_data(as_text=True)
    response = client.post("/orders", follow_redirects=True)
    assert "订单已创建" in response.get_data(as_text=True)


def test_user_cannot_save_for_other_device(client):
    register(client)
    client.post("/login", data={"email": "a@example.com", "password": "password123"})
    client.post("/orders")
    response = client.post("/api/locations", json={"device_id": 999, "latitude": 1, "longitude": 2})
    assert response.status_code == 403
