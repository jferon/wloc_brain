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
    page_text = page.get_data(as_text=True)
    assert "储存到设备" in page_text
    assert "搜索地名" in page_text
    assert "卫星影像" in page_text
    assert "收藏的位置" in page_text
    assert "粘贴地图链接" in page_text
    assert "浅色地图" not in page_text
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


def test_map_tile_rejects_invalid_coordinates(client):
    response = client.get("/map-tiles/20/0/0.png")
    assert response.status_code == 400


def test_geocode_rejects_empty_query(client):
    response = client.get("/api/geocode?q=")
    assert response.status_code == 400


def test_android_setup_has_mock_location_instructions(client):
    register(client)
    client.post("/login", data={"email": "a@example.com", "password": "password123"})
    client.post("/orders")
    response = client.post("/devices", data={"order_id": 1, "name": "Android", "client_type": "android_mock"}, follow_redirects=True)
    import re
    setup_url = re.search(r'value="([^" ]+/setup/[^" ]+)"', response.get_data(as_text=True)).group(1)
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(setup_url)
    page = client.get(parsed.path + "?token=" + parse_qs(parsed.query)["token"][0])
    text = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Android 模拟位置" in text
    assert "保存并复制坐标" in text


def test_branding_is_shan_xian_la(client):
    page = client.get("/")
    text = page.get_data(as_text=True)
    assert "闪现啦" in text
    assert "/static/logo.svg" in text


def test_module_route_rejects_invalid_token(client):
    response = client.get("/device/1/module?token=wrong")
    assert response.status_code == 404


def test_restore_shortcut_rejects_invalid_token(client):
    response = client.get("/device/1/restore?token=wrong")
    assert response.status_code == 404


def test_module_guide_hides_upstream_url(client):
    register(client)
    client.post("/login", data={"email": "a@example.com", "password": "password123"})
    client.post("/orders")
    response = client.post("/devices", data={"order_id": 1, "name": "Guide", "client_type": "shadowrocket"}, follow_redirects=True)
    import re
    setup_url = re.search(r'value="([^" ]+/setup/[^" ]+)"', response.get_data(as_text=True)).group(1)
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(setup_url)
    token = parse_qs(parsed.query)["token"][0]
    guide = client.get(f"/device/1/module-guide?token={token}")
    text = guide.get_data(as_text=True)
    assert guide.status_code == 200
    assert "安装闪现啦模块" in text
    assert "证书信任设置" in text
    assert "完全信任" in text
    assert "raw.githubusercontent.com" not in text
