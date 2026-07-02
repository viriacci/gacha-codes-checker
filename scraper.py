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
            if not cells:
                continue
 
            if len(cells) >= 2:
                code_cell, reward_cell = cells[0], cells[1]
            else:
                # niektore gry (np. WuWa) maja tabele z JEDNA kolumna,
                # gdzie kod i nagrody siedza w tej samej komorce
                code_cell = reward_cell = cells[0]
 
            # kod siedzi w atrybucie value inputa do kopiowania, nie w linku
            code_input = code_cell.find("input", class_="a-clipboard__textInput")
            if not code_input or not code_input.get("value"):
                continue
 
            code = code_input["value"].strip()
 
            # usuwamy widget kopiowania z komorki nagrod, zeby nie wlaczyl sie
            # do tekstu nagrod gdy code_cell i reward_cell to ta sama komorka
            reward_soup = BeautifulSoup(str(reward_cell), "html.parser")
            clipboard_widget = reward_soup.find("div", class_="a-clipboard__container")
            if clipboard_widget:
                clipboard_widget.decompose()
 
            reward_text = reward_soup.get_text(separator=" ", strip=True)
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
 
        # DEBUG: pokazujemy co realnie przyszlo w odpowiedzi, zeby wykryc blokade bota
        print(f"  [DEBUG] status={resp.status_code} dlugosc={len(resp.text)} znakow")
        print(f"  [DEBUG] pierwsze 300 znakow: {resp.text[:300]!r}")
        print(f"  [DEBUG] liczba tabel na stronie: {len(BeautifulSoup(resp.text, 'html.parser').find_all('table'))}")
 
        active_codes = extract_active_codes(resp.text)
        print(f"  [DEBUG] znaleziono {len(active_codes)} aktywnych kodow")
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
 
