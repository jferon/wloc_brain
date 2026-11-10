# WLOC Brain

Flask MVP for account/order/device management and Web-to-device WLOC coordinate saving.

## Boundary

The server stores user data and sends the `gs-loc.apple.com/wloc-settings/save` request from the browser. A user's iPhone must already have a compatible proxy client, WLOC module, MITM enabled, and a trusted certificate. The server cannot install or trust an iOS certificate, and server-side coordinate storage does not prove that iOS adopted the location.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export WLOC_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
flask --app app run --debug
```

Open http://127.0.0.1:5000, register, create a demo order, create a device, and open the one-time setup URL from the dashboard message.

## Current MVP limitations

- Orders are demo-created and immediately active; no payment provider is connected.
- The one-time setup URL is shown only in the redirect session flow and should be replaced with a proper encrypted/one-time delivery mechanism before production.
- CSRF protection, rate limiting, email verification, password reset, migrations, admin controls, production HTTPS, and payment webhooks are not implemented yet.
- The device-side save request only works when the page is opened on the phone and traffic is intercepted by the configured WLOC module.


## Android MVP

选择 `Android 模拟位置` 后，安装页会保存坐标并尝试复制 `纬度,经度`。Android 系统位置仍需用户在开发者选项中选择模拟位置信息应用并手动应用坐标；当前版本没有 Android Companion App，也不会自动修改系统 GPS。
