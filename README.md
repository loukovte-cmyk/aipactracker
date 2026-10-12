# Roblox Player Tracker

Watches a Roblox game's live player count and posts to Discord through a webhook:

- keeps one status message in the channel updated with the current count
- pings `@everyone` when the count reaches 10
- re-arms the ping once the count drops to 8 or below

## Deploy on Render

1. On render.com, choose **New → Background Worker** (paid) or **New → Web Service** (free plan) and select this repo.
2. Runtime: **Python 3**
3. Build command: `pip install -r requirements.txt`
4. Start command: `python player_tracker.py`
5. Under **Environment**, add:
   - `WEBHOOK_URL` – your Discord webhook URL (keep this secret, never commit it)
   - `PLACE_ID` – the number in your game's URL: `roblox.com/games/<PLACE_ID>/...`

**Free Web Service only:** free services sleep after about 15 minutes without visits. Point a free uptime monitor (e.g. UptimeRobot) at your service's `onrender.com` URL every 5 minutes to keep it awake. The script serves a small "ok" page for this automatically.

## Run locally

```
pip install -r requirements.txt
WEBHOOK_URL=... PLACE_ID=... python player_tracker.py
```

## Settings

Change these at the top of `player_tracker.py`:

| Setting | Default | Meaning |
|---|---|---|
| `THRESHOLD` | 10 | Ping `@everyone` at this many players |
| `RESET_BELOW` | 8 | Allow another ping after dropping to this |
| `POLL_SECONDS` | 60 | How often to check |
| `STATUS_MESSAGE` | True | Keep a live player-count message updated |
