"""
Sprawdza strony Game8 pod kątem nowych kodów do gier i wysyła ping na Discorda.
Uruchamiane cyklicznie przez GitHub Actions (patrz .github/workflows/check_codes.yml).
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import GAMES, STATE_FILE

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CodeCheckerBot/1.0)"}


def load_state():
    if Path(STATE_FILE).exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def extract_active_codes(html: str):
    """
    Zwraca listę (kod, nagrody_tekst) tylko z sekcji AKTYWNYCH kodów.
    Ucina parsowanie przy pierwszym nagłówku zawierającym 'Expired'.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for table in soup.find_all("table"):
        # sprawdź czy ta tabela jest już za nagłówkiem "Expired" - jeśli tak, pomiń
        prev_heading = table.find_previous(["h2", "h3"])
        if prev_heading and "expired" in prev_heading.get_text(strip=True).lower():
            continue

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            code_cell, reward_cell = cells[0], cells[1]

            # szukamy linku z parametrem ?code=
            code_link = code_cell.find("a", href=re.compile(r"[?&]code="))
            if not code_link:
                continue

            match = re.search(r"[?&]code=([A-Za-z0-9]+)", code_link["href"])
            if not match:
                continue

            code = match.group(1)

            # tekst nagród: bierzemy wszystkie linki + tekst przy nich (np. "Mora x10,000")
            reward_text = reward_cell.get_text(separator=" ", strip=True)
            reward_text = re.sub(r"\s+", " ", reward_text).strip()

            results.append((code, reward_text))

    return results


def send_discord_ping(game_key: str, game: dict, code: str, rewards: str):
    role_mention = f"<@&{game['role_id']}>"
    content = f"{role_mention} Nowy kod do **{game['name']}**!"

    fields = [
        {"name": "Kod", "value": f"```{code}```", "inline": False},
        {"name": "Nagrody", "value": rewards[:1000] or "brak danych", "inline": False},
    ]

    if game.get("redeem_base"):
        fields.append({
            "name": "Link",
            "value": f"[Odbierz tutaj]({game['redeem_base']}{code})",
            "inline": False,
        })

    payload = {
        "content": content,
        "embeds": [{
            "title": f"{game['name']} — Nowy kod",
            "color": game["color"],
            "fields": fields,
        }],
    }

    resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    if resp.status_code >= 300:
        print(f"[WARN] Discord webhook zwrocil {resp.status_code}: {resp.text}", file=sys.stderr)
    time.sleep(1)  # unikamy rate-limitu webhooka przy kilku kodach naraz


def main():
    if not WEBHOOK_URL:
        print("Brak DISCORD_WEBHOOK_URL w zmiennych srodowiskowych.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    new_codes_found = False

    for game_key, game in GAMES.items():
        print(f"Sprawdzam {game['name']}...")
        try:
            resp = requests.get(game["url"], headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[ERROR] Nie udalo sie pobrac {game['url']}: {e}", file=sys.stderr)
            continue

        active_codes = extract_active_codes(resp.text)
        seen = set(state.get(game_key, []))

        for code, rewards in active_codes:
            if code not in seen:
                print(f"  Nowy kod: {code}")
                send_discord_ping(game_key, game, code, rewards)
                seen.add(code)
                new_codes_found = True

        state[game_key] = sorted(seen)
        time.sleep(2)  # nie bombardujemy game8.co requestami pod rzad

    if new_codes_found:
        save_state(state)
        print("Zapisano nowy stan.")
    else:
        print("Brak nowych kodow.")


if __name__ == "__main__":
    main()
