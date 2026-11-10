import os
import secrets
import sqlite3
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
    # The raw token is only shown once through the setup URL in this response flow.
    device_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    session["new_setup_url"] = url_for("setup", device_id=device_id, token=raw_token, _external=True)
    flash("设备配置已生成。请复制一次性安装链接。", "success")
    return redirect(url_for("dashboard"))


@app.route("/setup/<int:device_id>")
def setup(device_id):
    token = request.args.get("token", "")
    device = get_db().execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not device or not token or not check_password_hash(device["token_hash"], token):
        return render_template("error.html", message="安装链接无效或已过期。"), 404
    return render_template("setup.html", device=device, save_host="https://gs-loc.apple.com/wloc-settings/save")


@app.post("/api/locations")
@login_required
def save_location():
    payload = request.get_json(silent=True) or request.form
    def number(name, cast):
        value = payload.get(name)
        try:
            return cast(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
    device_id = number("device_id", int)
    lat = number("latitude", float)
    lon = number("longitude", float)
    name = (payload.get("name") or "").strip()
    accuracy = number("accuracy", float) or 25
    if device_id is None or lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {"ok": False, "error": "坐标或设备参数无效"}, 400
    db = get_db()
    device = db.execute("SELECT * FROM devices WHERE id = ? AND user_id = ?", (device_id, g.user["id"])).fetchone()
    if not device:
        return {"ok": False, "error": "设备不属于当前用户"}, 403
    db.execute("INSERT INTO locations(user_id, device_id, name, latitude, longitude, accuracy, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (g.user["id"], device_id, name, lat, lon, accuracy, now()))
    db.execute("UPDATE devices SET last_seen_at = ? WHERE id = ?", (now(), device_id))
    db.commit()
    return {"ok": True, "message": "服务器已保存坐标；请继续点击储存到设备完成手机端写入。"}


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
