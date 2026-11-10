import os
import secrets
import sqlite3
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = os.environ.get("WLOC_DATABASE", str(BASE_DIR / "wloc.db"))
SECRET_KEY = os.environ.get("WLOC_SECRET_KEY", "dev-only-change-me")

app = Flask(__name__)
app.config.update(SECRET_KEY=SECRET_KEY, DATABASE=DATABASE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'active',
  expires_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  client_type TEXT NOT NULL DEFAULT 'shadowrocket',
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '',
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  accuracy REAL NOT NULL DEFAULT 25,
  created_at TEXT NOT NULL
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def load_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("Initialized database.")


@app.get("/api/parse")
def parse_map_input():
    import re
    raw = request.args.get("u", "").strip()
    if not raw or len(raw) > 2000:
        return {"error": "输入无效"}, 422
    patterns = [r"(?:coordinate|ll|q|center|location|@)=?(-?\d{1,3}\.\d+)\s*[,，]\s*(-?\d{1,3}\.\d+)", r"(-?\d{1,2}\.\d{3,})\s*[,，]\s*(-?\d{1,3}\.\d{3,})"]
    for pattern in patterns:
        match = re.search(pattern, raw, re.I)
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return {"lat": round(lat, 6), "lon": round(lon, 6), "name": ""}
    return {"error": "未找到合法坐标"}, 422


@app.get("/api/geocode")
def geocode():
    query = request.args.get("q", "").strip()
    if not query or len(query) > 120:
        return {"ok": False, "error": "搜索内容无效"}, 400
    target = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&accept-language=zh-CN&q=" + urllib.parse.quote(query)
    req = urllib.request.Request(target, headers={"User-Agent": "WLOC-Brain/0.1 geocoder"})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            body = response.read(512 * 1024 + 1)
            if len(body) > 512 * 1024:
                return {"ok": False, "error": "搜索结果过大"}, 502
            output = app.response_class(body, status=200, mimetype="application/json")
            output.headers["Cache-Control"] = "public, max-age=300"
            return output
    except (urllib.error.URLError, TimeoutError):
        return {"ok": False, "error": "地名搜索服务暂时不可用"}, 502


@app.get("/map-tiles/<int:z>/<int:x>/<int:y>.png")
def map_tile(z, x, y):
    """Proxy OSM tiles through the same Flask origin for restricted mobile networks."""
    if z < 0 or z > 19 or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
        return {"ok": False, "error": "invalid tile"}, 400
    target = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    request = urllib.request.Request(target, headers={"User-Agent": "WLOC-Brain/0.1 map tile proxy"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read(512 * 1024 + 1)
            if len(body) > 512 * 1024:
                return {"ok": False, "error": "tile too large"}, 502
            output = app.response_class(body, status=200, mimetype="image/png")
            output.headers["Cache-Control"] = "public, max-age=86400"
            return output
    except (urllib.error.URLError, TimeoutError):
        return {"ok": False, "error": "map tile upstream unavailable"}, 502


@app.route("/")
def index():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or "@" not in email:
            flash("请输入有效邮箱。", "error")
        elif len(password) < 8:
            flash("密码至少需要 8 位。", "error")
        else:
            try:
                db = get_db()
                db.execute("INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                           (email, generate_password_hash(password), now()))
                db.commit()
                flash("注册成功，请登录。", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("该邮箱已注册。", "error")
    return render_template("auth.html", mode="register")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("邮箱或密码错误。", "error")
    return render_template("auth.html", mode="login")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    orders = db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (g.user["id"],)).fetchall()
    devices = db.execute("""
      SELECT d.*, o.status AS order_status, o.expires_at
      FROM devices d JOIN orders o ON o.id = d.order_id
      WHERE d.user_id = ? ORDER BY d.id DESC
    """, (g.user["id"],)).fetchall()
    setup_url = session.pop("new_setup_url", None)
    return render_template("dashboard.html", orders=orders, devices=devices, setup_url=setup_url)


@app.post("/orders")
@login_required
def create_order():
    db = get_db()
    db.execute("INSERT INTO orders(user_id, status, created_at) VALUES (?, 'active', ?)", (g.user["id"], now()))
    db.commit()
    flash("订单已创建（演示环境直接标记为 active）。", "success")
    return redirect(url_for("dashboard"))


@app.post("/devices")
@login_required
def create_device():
    order_id = request.form.get("order_id", type=int)
    name = request.form.get("name", "我的 iPhone").strip() or "我的 iPhone"
    client_type = request.form.get("client_type", "shadowrocket")
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ? AND user_id = ? AND status = 'active'", (order_id, g.user["id"])).fetchone()
    if not order:
        flash("请选择有效订单。", "error")
        return redirect(url_for("dashboard"))
    raw_token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO devices(user_id, order_id, name, client_type, token_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
               (g.user["id"], order_id, name, client_type, generate_password_hash(raw_token), now()))
    db.commit()
    # The raw token is returned only in the creation response flow.
    device_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    session["new_setup_url"] = url_for("setup", device_id=device_id, token=raw_token, _external=True)
    flash("设备配置已生成。请复制安装链接。", "success")
    return redirect(url_for("dashboard"))


MODULE_SOURCES = {
    "shadowrocket": "https://raw.githubusercontent.com/xepes0/wloc/refs/heads/main/modules/wloc.module",
    "surge": "https://raw.githubusercontent.com/xepes0/wloc/refs/heads/main/modules/wloc.sgmodule",
}


RESTORE_SHORTCUT_URL = "https://www.icloud.com/shortcuts/f42632d406504f24a2cd163af4fe012f"


@app.get("/device/<int:device_id>/restore")
def restore_shortcut(device_id):
    token = request.args.get("token", "")
    device = get_db().execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not device or not token or not check_password_hash(device["token_hash"], token):
        return {"ok": False, "error": "恢复链接无效"}, 404
    return redirect(RESTORE_SHORTCUT_URL)


@app.get("/device/<int:device_id>/module-guide")
def module_guide(device_id):
    token = request.args.get("token", "")
    device = get_db().execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not device or not token or not check_password_hash(device["token_hash"], token):
        return render_template("error.html", message="模块安装链接无效或已过期。"), 404
    module_url = url_for("device_module", device_id=device_id, token=token, _external=True)
    return render_template("module_guide.html", device=device, module_url=module_url)


@app.get("/device/<int:device_id>/module")
def device_module(device_id):
    token = request.args.get("token", "")
    device = get_db().execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    source = MODULE_SOURCES.get(device["client_type"] if device else "")
    if not device or not source or not token or not check_password_hash(device["token_hash"], token):
        return {"ok": False, "error": "模块链接无效"}, 404
    try:
        upstream = urllib.request.Request(source, headers={"User-Agent": "WLOC-Brain/0.1 module proxy"})
        with urllib.request.urlopen(upstream, timeout=8) as response:
            body = response.read(512 * 1024 + 1)
        if len(body) > 512 * 1024:
            return {"ok": False, "error": "模块文件过大"}, 502
    except (urllib.error.URLError, TimeoutError):
        return {"ok": False, "error": "模块服务暂时不可用"}, 502
    output = app.response_class(body, status=200, mimetype="text/plain")
    output.headers["Content-Disposition"] = "inline; filename=shanxianla-wloc.module"
    output.headers["Cache-Control"] = "no-store"
    return output


@app.route("/setup/<int:device_id>")
def setup(device_id):
    token = request.args.get("token", "")
    device = get_db().execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not device or not token or not check_password_hash(device["token_hash"], token):
        return render_template("error.html", message="安装链接无效或已过期。"), 404
    return render_template("setup.html", device=device, token=token, save_host="https://gs-loc.apple.com/wloc-settings/save")


def parse_location_payload(payload):
    def number(name, cast):
        value = payload.get(name)
        try:
            return cast(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
    lat = number("latitude", float)
    lon = number("longitude", float)
    accuracy = number("accuracy", float) or 25
    name = (payload.get("name") or "").strip()[:80]
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon, accuracy, name


def record_location(device, location):
    lat, lon, accuracy, name = location
    db = get_db()
    db.execute("INSERT INTO locations(user_id, device_id, name, latitude, longitude, accuracy, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (device["user_id"], device["id"], name, lat, lon, accuracy, now()))
    db.execute("UPDATE devices SET last_seen_at = ? WHERE id = ?", (now(), device["id"]))
    db.commit()
    return {"ok": True, "message": "服务器已保存坐标；请继续点击储存到设备完成手机端写入。"}


@app.post("/api/locations")
@login_required
def save_location():
    payload = request.get_json(silent=True) or request.form
    try:
        device_id = int(payload.get("device_id"))
    except (TypeError, ValueError):
        device_id = None
    location = parse_location_payload(payload)
    if device_id is None or location is None:
        return {"ok": False, "error": "坐标或设备参数无效"}, 400
    device = get_db().execute("SELECT * FROM devices WHERE id = ? AND user_id = ?", (device_id, g.user["id"])).fetchone()
    if not device:
        return {"ok": False, "error": "设备不属于当前用户"}, 403
    return record_location(device, location)


@app.post("/api/device/<int:device_id>/locations")
def save_device_location(device_id):
    payload = request.get_json(silent=True) or request.form
    token = request.headers.get("X-WLOC-Device-Token") or payload.get("token") or ""
    device = get_db().execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not device or not token or not check_password_hash(device["token_hash"], token):
        return {"ok": False, "error": "设备 Token 无效"}, 401
    location = parse_location_payload(payload)
    if location is None:
        return {"ok": False, "error": "坐标或设备参数无效"}, 400
    return record_location(device, location)


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
