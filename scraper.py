"""
Sprawdza kody do gier (API dla Genshin/ZZZ/HSR, scraping Game8 dla WuWa/NTE)
i wysyła ping na Discorda przy nowych kodach.
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
 
from config import GAMES, CODES_API_URL, STATE_FILE
 
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
}
 
 
def load_state():
    if Path(STATE_FILE).exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
 
 
def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
 
 
def fetch_codes_from_api(game_key: str, game: dict):
    """Pobiera kody dla gier obslugiwanych przez db.hashblen.com/codes (bez scrapowania)."""
    try:
        resp = requests.get(CODES_API_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[ERROR] API {CODES_API_URL} nie odpowiedzialo poprawnie: {e}", file=sys.stderr)
        return []
 
    entries = data.get(game["api_key"], [])
    return [(entry["code"], entry.get("description", "") or "brak opisu") for entry in entries]
 
 
def extract_active_codes_from_html(html: str):
    """
    Zwraca liste (kod, nagrody_tekst) z tabel Game8, tylko sekcja AKTYWNYCH kodow.
    Obsluguje zarowno tabele 2-kolumnowe (kod | nagrody) jak i 1-kolumnowe (WuWa).
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
 
    for table in soup.find_all("table"):
        prev_heading = table.find_previous(["h2", "h3"])
        if prev_heading and "expired" in prev_heading.get_text(strip=True).lower():
            continue
 
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue
 
            if len(cells) >= 2:
                code_cell, reward_cell = cells[0], cells[1]
            else:
                code_cell = reward_cell = cells[0]
 
            code_input = code_cell.find("input", class_="a-clipboard__textInput")
            if not code_input or not code_input.get("value"):
                continue
 
            code = code_input["value"].strip()
 
            reward_soup = BeautifulSoup(str(reward_cell), "html.parser")
            clipboard_widget = reward_soup.find("div", class_="a-clipboard__container")
            if clipboard_widget:
                clipboard_widget.decompose()
 
            reward_text = reward_soup.get_text(separator=" ", strip=True)
            reward_text = re.sub(r"\s+", " ", reward_text).strip()
 
            results.append((code, reward_text))
 
    return results
 
 
def fetch_codes_from_scrape(game_key: str, game: dict):
    """
    Best-effort scraping Game8 dla gier bez wlasnego API (WuWa, NTE).
    Jesli strona zwroci AWS WAF challenge (status 202, brak tabel), zwraca pusta liste
    i loguje ostrzezenie zamiast wywalac caly run.
    """
    try:
        resp = requests.get(game["url"], headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        print(f"  [WARN] Nie udalo sie polaczyc z {game['url']}: {e}", file=sys.stderr)
        return []
 
    if "awsWafCookie" in resp.text or "awswaf" in resp.text.lower():
        print(f"  [WARN] Game8 zwrocilo wyzwanie AWS WAF dla {game['name']} - pomijam ten run.")
        return []
 
    if resp.status_code != 200:
        print(f"  [WARN] Game8 zwrocilo status {resp.status_code} dla {game['name']} - pomijam.")
        return []
 
    return extract_active_codes_from_html(resp.text)
 
 
def send_discord_ping(game: dict, code: str, rewards: str):
    role_mention = f"<@&{game['role_id']}>"
    content = f"{role_mention} Nowy kod do **{game['name']}**!"
 
    fields = [
        {"name": "Kod", "value": f"```{code}```", "inline": False},
        {"name": "Nagrody", "value": (rewards or "brak danych")[:1000], "inline": False},
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
    time.sleep(1)
 
 
def main():
    if not WEBHOOK_URL:
        print("Brak DISCORD_WEBHOOK_URL w zmiennych srodowiskowych.", file=sys.stderr)
        sys.exit(1)
 
    state = load_state()
    any_new = False
 
    for game_key, game in GAMES.items():
        print(f"Sprawdzam {game['name']} (zrodlo: {game['source']})...")
 
        if game["source"] == "api":
            codes = fetch_codes_from_api(game_key, game)
        else:
            codes = fetch_codes_from_scrape(game_key, game)
 
        print(f"  Znaleziono {len(codes)} aktywnych kodow.")
 
        seen = set(state.get(game_key, []))
        for code, rewards in codes:
            if code not in seen:
                print(f"  Nowy kod: {code}")
                send_discord_ping(game, code, rewards)
                seen.add(code)
                any_new = True
 
        state[game_key] = sorted(seen)
        time.sleep(1)
 
    # zawsze zapisujemy stan, nawet jesli nic nowego - zeby plik zawsze istnial w repo
    save_state(state)
    print("Zapisano stan." if any_new else "Brak nowych kodow.")
 
 
if __name__ == "__main__":
    main()
