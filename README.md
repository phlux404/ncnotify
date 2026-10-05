# ncnotify

Send Nextcloud push notifications from the command line. Stdlib-only Python, no dependencies.

Built so a headless server (or an agent) can ping your phone through your own Nextcloud — no Google, no Apple push infrastructure needed.

## Setup

1. In Nextcloud: **Settings → Security → Devices & sessions → Create new app password**.
2. Save the credentials (chmod 600) in `~/.config/ncnotify/config`:

```
NEXTCLOUD_URL=https://cloud.example.com
NEXTCLOUD_USER=admin
NEXTCLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx-xxxx
```

Environment variables of the same names work too and take precedence.

Optional:
```
NEXTPUSH_CHANNEL=https://cloud.example.com/index.php/apps/uppush/push/<token>
TALK_ROOM=MyRoom
```
`NEXTPUSH_CHANNEL` powers `buzz` (see below). `TALK_ROOM` overrides the
default Talk room name ("Quill").

## Usage

```bash
# Send a notification (you must authenticate as an admin user)
./ncnotify.py send alice "Backup finished" -l "Nightly backup completed in 4m12s."

# Buzz the phone directly via NextPush (see below — the primary path)
./ncnotify.py buzz "Server backup finished."

# Send a Talk message (alternative buzz path)
./ncnotify.py talk "Morning briefing is ready."
./ncnotify.py talk --room MyRoom "Hello there."

# List your pending notifications
./ncnotify.py list

# Delete one
./ncnotify.py delete 42
```

## Why buzz (NextPush)?

The Nextcloud Files Android app only does push via Google's FCM — a dead
switch on a Google-free phone. The reliable path is **NextPush**: install the
[UnifiedPush Provider](https://apps.nextcloud.com/apps/uppush) app on your
Nextcloud, log the [NextPush](https://f-droid.org/packages/org.unifiedpush.distributor.nextpush/)
Android app into it, create a notification channel, and save its endpoint as
`NEXTPUSH_CHANNEL`. `buzz` POSTs plain text to that endpoint and the phone
buzzes — your Nextcloud is the entire push infrastructure, no Google, no
Apple, no third party.

## Alternative: Talk

The **Talk** Android app (v24.0.2+) also supports UnifiedPush, so `talk`
messages are a second way to make the phone buzz with zero Google in the path.

Phone/server setup (one time):
1. Nextcloud admin settings → Notifications → enable **Allow web push**.
2. Talk Android app → Settings → enable **UnifiedPush** (appears once a
   distributor such as NextPush is installed).
3. `talk` posts into a group conversation (default name "Quill", created automatically).

## How it works

Uses the Nextcloud Notifications OCS API (`admin_notifications` endpoint). Notifications land in the user's Nextcloud notification center (web UI + apps) and push to mobile via whatever push transport the app uses (FCM, or UnifiedPush on Google-free phones).

Tailnet-aware: if `NEXTCLOUD_URL` points at a Tailscale address (`.ts.net` or `100.64.0.0/10`), requests are routed through the Tailscale tunnel proxy automatically. The first connection needs a one-time approval on the user's side.

## License

MIT — see LICENSE.
