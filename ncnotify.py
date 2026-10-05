#!/usr/bin/env python3
"""ncnotify - send Nextcloud notifications via the OCS Notifications API.

Lets an admin push notifications to any Nextcloud user from the command
line. Useful for headless servers and agents that want to reach a phone
without going through Google/Apple push infrastructure.

Python 3, standard library only - no dependencies.

Auth: a Nextcloud admin username + app password (Settings -> Security ->
Devices & sessions -> Create new app password). Supplied via environment
variables or ~/.config/ncnotify/config (chmod 600):

    NEXTCLOUD_URL=https://cloud.example.com
    NEXTCLOUD_USER=admin
    NEXTCLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx-xxxx

The app password is only ever sent to your own Nextcloud server,
never printed or logged.
"""
import argparse
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

CONFIG_FILE = os.path.expanduser("~/.config/ncnotify/config")


def load_config():
    cfg = {}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    except OSError:
        pass
    return cfg


_CFG = load_config()


def setting(name, default=""):
    return os.environ.get(name, "").strip() or _CFG.get(name, default).strip()


def base_url():
    url = setting("NEXTCLOUD_URL").rstrip("/")
    if not url:
        sys.stderr.write(
            "error: NEXTCLOUD_URL not set.\n"
            "Set it via env var or in ~/.config/ncnotify/config (chmod 600).\n"
        )
        sys.exit(2)
    return url


def auth_header():
    user = setting("NEXTCLOUD_USER")
    pw = setting("NEXTCLOUD_APP_PASSWORD")
    if not user or not pw:
        sys.stderr.write(
            "error: NEXTCLOUD_USER / NEXTCLOUD_APP_PASSWORD not set.\n"
            "Create an app password in Nextcloud: Settings -> Security ->\n"
            "Devices & sessions -> Create new app password.\n"
        )
        sys.exit(2)
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return f"Basic {token}"


def tunnel_proxy():
    """Proxy URL for reaching the user's Tailscale network.

    Ordinary networking from this VM does not reach the tailnet; requests
    go through the runtime proxy with the port switched to 3130.
    """
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not https_proxy:
        return None
    base = https_proxy.rsplit(":", 1)[0]
    return f"{base}:3130"


def is_tailnet_host(host):
    host = (host or "").lower().rstrip(".")
    if host.endswith(".ts.net"):
        return True
    parts = host.split(".")
    if len(parts) == 4 and parts[0] == "100":
        try:
            second = int(parts[1])
            if 64 <= second <= 127 and all(p.isdigit() for p in parts):
                return True
        except ValueError:
            pass
    return False


def build_opener(url):
    """Opener that routes tailnet hosts through the Tailscale tunnel proxy."""
    host = urllib.parse.urlparse(url).hostname or ""
    if is_tailnet_host(host):
        proxy = tunnel_proxy()
        if not proxy:
            sys.stderr.write("error: tailnet host but no HTTPS_PROXY set; "
                             "cannot reach the Tailscale network.\n")
            sys.exit(2)
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def api(method, path, data=None, timeout=120):
    body = None
    headers = {
        "OCS-APIREQUEST": "true",
        "Accept": "application/json",
        "Authorization": auth_header(),
    }
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(base_url() + path, data=body,
                                 headers=headers, method=method)
    opener = build_opener(base_url() + path)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:2000]
        sys.stderr.write(f"error: Nextcloud API {e.code} {e.reason}\n{detail}\n")
        sys.exit(1)
    except urllib.error.URLError as e:
        sys.stderr.write(f"error: network: {e.reason}\n")
        sys.exit(1)
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.stderr.write(f"error: non-JSON response:\n{raw[:2000]}\n")
        sys.exit(1)
    ocs = payload.get("ocs", {})
    meta = ocs.get("meta", {})
    if meta.get("status") != "ok":
        sys.stderr.write(f"error: OCS {meta.get('statuscode')}: "
                         f"{meta.get('message')}\n")
        sys.exit(1)
    return ocs.get("data", {})


def cmd_send(args):
    data = {"shortMessage": args.short_message[:255]}
    if args.long_message:
        data["longMessage"] = args.long_message[:4000]
    path = ("/ocs/v2.php/apps/notifications/api/v2/admin_notifications/"
            + urllib.parse.quote(args.user, safe=""))
    result = api("POST", path, data)
    if isinstance(result, list):
        notif_id = result[0].get("notification_id") if result else None
    elif isinstance(result, dict):
        notif_id = result.get("id") or result.get("notification_id")
    else:
        notif_id = None
    print(json.dumps({"sent": True, "user": args.user,
                      "notification_id": notif_id}, indent=2))


def cmd_list(args):
    data = api("GET", "/ocs/v2.php/apps/notifications/api/v2/notifications")
    items = data if isinstance(data, list) else []
    out = [{
        "id": n.get("notification_id"),
        "app": n.get("app"),
        "user": n.get("user"),
        "subject": n.get("subject"),
        "message": n.get("message"),
        "datetime": n.get("datetime"),
    } for n in items]
    print(json.dumps(out, indent=2))


def cmd_delete(args):
    api("DELETE", "/ocs/v2.php/apps/notifications/api/v2/notifications/"
        + urllib.parse.quote(str(args.id), safe=""))
    print(json.dumps({"deleted": True, "id": args.id}, indent=2))


TALK_ROOM_NAME = "Quill"


def talk_room_name(args):
    return (getattr(args, "room", "") or setting("TALK_ROOM")
            or TALK_ROOM_NAME)


def talk_rooms():
    data = api("GET", "/ocs/v2.php/apps/spreed/api/v4/room")
    return data if isinstance(data, list) else []


def talk_ensure_room(args):
    name = talk_room_name(args)
    for room in talk_rooms():
        if room.get("name") == name:
            return room["token"]
    room = api("POST", "/ocs/v2.php/apps/spreed/api/v4/room",
               {"roomType": 2, "roomName": name})
    return room["token"]


def cmd_talk(args):
    token = talk_ensure_room(args)
    # NOTE: Talk's chat API is v1 even though rooms are v4
    api("POST", "/ocs/v2.php/apps/spreed/api/v1/chat/"
        + urllib.parse.quote(token, safe=""),
        {"message": args.message})
    print(json.dumps({"sent": True, "room": talk_room_name(args)}, indent=2))


def cmd_buzz(args):
    """POST a plain-text message to a NextPush notification channel.

    The channel endpoint is a secret URL (token in the path); it lives in
    the config as NEXTPUSH_CHANNEL and is never printed.
    """
    endpoint = setting("NEXTPUSH_CHANNEL")
    if not endpoint:
        sys.stderr.write("error: NEXTPUSH_CHANNEL not set.\n"
                         "Create a notification channel in the NextPush app, "
                         "long-press it for the endpoint URL, and save it in "
                         "~/.config/ncnotify/config\n")
        sys.exit(2)
    req = urllib.request.Request(endpoint,
                                 data=args.message.encode("utf-8"),
                                 method="POST")
    opener = build_opener(endpoint)
    try:
        with opener.open(req, timeout=120) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"error: NextPush channel {e.code} {e.reason}\n")
        sys.exit(1)
    except urllib.error.URLError as e:
        sys.stderr.write(f"error: network: {e.reason}\n")
        sys.exit(1)
    print(json.dumps({"sent": True, "via": "nextpush"}, indent=2))


def main():
    ap = argparse.ArgumentParser(
        description="Send Nextcloud push notifications from the command line.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("send", help="send a notification to a user")
    p.add_argument("user", help="Nextcloud user id to notify")
    p.add_argument("short_message", help="short message (max 255 chars)")
    p.add_argument("-l", "--long-message", default="",
                   help="longer message (max 4000 chars)")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("list", help="list your pending notifications")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("delete", help="delete a notification by id")
    p.add_argument("id", help="notification id (from list)")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("talk", help="send a Talk message (pushes via "
                                    "UnifiedPush once enabled in the Talk app)")
    p.add_argument("message", help="message text")
    p.add_argument("--room", default="",
                   help="Talk room name (default: TALK_ROOM or 'Quill')")
    p.set_defaults(func=cmd_talk)

    p = sub.add_parser("buzz", help="buzz the phone directly via a NextPush "
                                    "notification channel (no Google, no client app needed)")
    p.add_argument("message", help="message text")
    p.set_defaults(func=cmd_buzz)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
