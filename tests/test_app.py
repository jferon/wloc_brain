import os
import tempfile
import re

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


def test_setup_page_and_device_token_save(client):
    register(client)
    client.post("/login", data={"email": "a@example.com", "password": "password123"})
    client.post("/orders")
    response = client.post("/devices", data={"order_id": 1, "name": "Test iPhone", "client_type": "shadowrocket"}, follow_redirects=True)
    assert "安装链接" in response.get_data(as_text=True)
    setup_url = re.search(r'value="([^" ]+/setup/[^" ]+)"', response.get_data(as_text=True)).group(1)
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(setup_url)
    device_id = int(parsed.path.rsplit("/", 1)[-1])
    token = parse_qs(parsed.query)["token"][0]
    page = client.get(parsed.path + "?token=" + token)
    assert page.status_code == 200
    assert "储存到设备" in page.get_data(as_text=True)
    saved = client.post(f"/api/device/{device_id}/locations", json={
        "latitude": 31.2304,
        "longitude": 121.4737,
        "name": "测试点",
    }, headers={"X-WLOC-Device-Token": token})
    assert saved.status_code == 200
    assert saved.json["ok"] is True
    denied = client.post(f"/api/device/{device_id}/locations", json={
        "latitude": 31.2304, "longitude": 121.4737,
    }, headers={"X-WLOC-Device-Token": "wrong"})
    assert denied.status_code == 401
