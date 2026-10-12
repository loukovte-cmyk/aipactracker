"""
Roblox player count tracker -> Discord webhook.

- Polls a Roblox game's live player count every POLL_SECONDS.
- Keeps one "live status" message in the channel updated (optional).
- Pings @everyone once when the count reaches THRESHOLD.
- Won't ping again until the count drops to RESET_BELOW or lower,
  so it doesn't spam when the server hovers around 9-10.

Setup:
  pip install requests
  Set WEBHOOK_URL and PLACE_ID below (or as environment variables), then:
  python player_tracker.py
"""

import functools
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

# Make every print show up in hosting logs immediately.
print = functools.partial(print, flush=True)


def _place_id_from_env() -> int:
    # Accepts a plain number or a full game link like
    # https://www.roblox.com/games/123456789/My-Game
    raw = os.getenv("PLACE_ID", "").strip()
    m = re.search(r"games/(\d+)", raw) or re.fullmatch(r"(\d+)", raw)
    return int(m.group(1)) if m else 0


# ---------------- CONFIG ----------------
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "PASTE_YOUR_WEBHOOK_URL_HERE").strip()
PLACE_ID = _place_id_from_env()  # number in the game URL: roblox.com/games/<PLACE_ID>/...
THRESHOLD = 10          # ping @everyone when players >= this
RESET_BELOW = 8         # re-arm the ping once players drop to this or lower
POLL_SECONDS = 60       # how often to check (don't go much lower than 30)
STATUS_MESSAGE = True   # keep an auto-updating player count message in the channel
STATE_FILE = "tracker_state.txt"  # remembers the status message ID between restarts
# ----------------------------------------

session = requests.Session()
session.headers["User-Agent"] = "roblox-player-tracker/1.0"


# Tiny keep-awake web page. Only starts when a PORT is set, which Render
# does for Web Services (the free plan). Background Workers skip it.
class Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def start_web_if_needed() -> None:
    port = os.getenv("PORT")
    if port:
        server = HTTPServer(("0.0.0.0", int(port)), Ping)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"Keep-awake page listening on port {port}")


def get_universe_id(place_id: int) -> int:
    r = session.get(f"https://apis.roblox.com/universes/v1/places/{place_id}/universe", timeout=15)
    r.raise_for_status()
    return r.json()["universeId"]


def get_game_stats(universe_id: int) -> tuple[str, int]:
    r = session.get(f"https://games.roblox.com/v1/games?universeIds={universe_id}", timeout=15)
    r.raise_for_status()
    game = r.json()["data"][0]
    return game["name"], game["playing"]


def webhook_post(payload: dict) -> dict | None:
    r = session.post(WEBHOOK_URL + "?wait=true", json=payload, timeout=15)
    if r.status_code == 429:
        time.sleep(r.json().get("retry_after", 5))
        return None
    r.raise_for_status()
    return r.json()


def webhook_edit(message_id: str, payload: dict) -> bool:
    r = session.patch(f"{WEBHOOK_URL}/messages/{message_id}", json=payload, timeout=15)
    if r.status_code == 404:  # message was deleted
        return False
    if r.status_code == 429:
        time.sleep(r.json().get("retry_after", 5))
        return True
    r.raise_for_status()
    return True


def status_embed(name: str, players: int) -> dict:
    hit = players >= THRESHOLD
    return {
        "embeds": [{
            "title": name,
            "url": f"https://www.roblox.com/games/{PLACE_ID}",
            "description": f"**Players online:** {players}\n**Ping threshold:** {THRESHOLD}",
            "color": 0x2ECC71 if hit else 0x95A5A6,
            "footer": {"text": f"Updates every {POLL_SECONDS}s"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
        "allowed_mentions": {"parse": []},
    }


def load_message_id() -> str | None:
    try:
        with open(STATE_FILE) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def save_message_id(message_id: str) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(message_id)


def main() -> None:
    start_web_if_needed()

    problems = []
    if not re.match(r"https://(ptb\.|canary\.)?discord(app)?\.com/api/webhooks/\d+/\S+$", WEBHOOK_URL):
        problems.append(
            "WEBHOOK_URL is missing or isn't a Discord webhook link "
            "(it should start with https://discord.com/api/webhooks/)."
        )
    if PLACE_ID == 0:
        problems.append(
            f"PLACE_ID is missing or unreadable (got {os.getenv('PLACE_ID')!r}). "
            "Use the number from your game link: roblox.com/games/<number>/..."
        )
    if problems:
        for p in problems:
            print("CONFIG ERROR:", p)
        print("Fix these in your host's environment variables, then redeploy.")
        raise SystemExit(1)

    # Look up the game, retrying instead of crashing if Roblox is slow or busy.
    while True:
        try:
            universe_id = get_universe_id(PLACE_ID)
            break
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (400, 404):
                print(f"CONFIG ERROR: Roblox says place {PLACE_ID} doesn't exist. Check PLACE_ID.")
                raise SystemExit(1)
            print(f"Couldn't reach Roblox yet ({e}). Retrying in 30s...")
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"Couldn't reach Roblox yet ({e}). Retrying in 30s...")
        time.sleep(30)

    print(f"Tracking place {PLACE_ID} (universe {universe_id})")

    status_id = load_message_id()
    armed = True  # True = allowed to ping next time we hit the threshold

    while True:
        try:
            name, players = get_game_stats(universe_id)
            print(f"[{datetime.now():%H:%M:%S}] {name}: {players} players")

            # Live status message
            if STATUS_MESSAGE:
                payload = status_embed(name, players)
                if not status_id or not webhook_edit(status_id, payload):
                    msg = webhook_post(payload)
                    if msg:
                        status_id = msg["id"]
                        save_message_id(status_id)

            # @everyone ping
            if armed and players >= THRESHOLD:
                webhook_post({
                    "content": (
                        f"@everyone **{name}** just hit **{players} players**! "
                        f"Get in: https://www.roblox.com/games/{PLACE_ID}"
                    ),
                    "allowed_mentions": {"parse": ["everyone"]},
                })
                armed = False
                print("  -> pinged @everyone")
            elif not armed and players <= RESET_BELOW:
                armed = True
                print("  -> re-armed")

        except requests.RequestException as e:
            print(f"Request failed: {e}")
        except (KeyError, IndexError) as e:
            print(f"Unexpected response from Roblox: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
