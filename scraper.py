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


def get_with_retry(url: str, headers: dict = None, timeout: int = 20, attempts: int = 3):
    """
    GET z ponowieniami przy chwilowym bledzie sieci (timeout, zerwane polaczenie).
    Nie ponawia przy odpowiedzi HTTP z tresci (np. 202 WAF) - to nie jest blad sieci,
    tylko celowa odpowiedz serwera, ktora i tak obsluzy kod wolajacy.
    """
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return requests.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            last_exc = e
            if attempt < attempts:
                wait = 3 * attempt
                print(f"  [WARN] Proba {attempt}/{attempts} nie powiodla sie ({e}), ponawiam za {wait}s...")
                time.sleep(wait)
    raise last_exc


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
        resp = get_with_retry(CODES_API_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[ERROR] API {CODES_API_URL} nie odpowiedzialo poprawnie: {e}", file=sys.stderr)
        return None

    entries = data.get(game["api_key"], [])
    results = []
    for entry in entries:
        desc = (entry.get("description") or "").strip()
        # API czasem zwraca pusty string albo placeholder "..." zamiast realnego opisu
        if not desc or desc == "...":
            reward_text = None
        else:
            # opis to jeden zlepiony ciag bez przecinkow/nowych linii, np.
            # "Mora x10000 Adventurer's Experience x10 Fine Enhancement Ore x5"
            # dzielimy w miejscach: cyfra + spacja + wielka litera = granica nowej pozycji
            items = re.split(r"(?<=\d)\s+(?=[A-Z])", desc)
            reward_text = "\n".join(f"• {item.strip()}" for item in items if item.strip())
        results.append((entry["code"], reward_text, None))
    return results


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

            # data wygasniecia - siedzi w span.a-red obok inputa (dostepne tylko przy scrapingu)
            expiry_span = code_cell.find("span", class_="a-red")
            expiry = expiry_span.get_text(strip=True) if expiry_span else None

            # nagrody jako lista wypunktowana - kazdy div.align to jedna nagroda
            reward_soup = BeautifulSoup(str(reward_cell), "html.parser")
            clipboard_widget = reward_soup.find("div", class_="a-clipboard__container")
            if clipboard_widget:
                clipboard_widget.decompose()

            reward_items = []
            align_divs = reward_soup.find_all("div", class_="align")
            if align_divs:
                for div in align_divs:
                    text = re.sub(r"\s+", " ", div.get_text(separator=" ", strip=True)).strip()
                    text = text.lstrip("・").strip()
                    if text:
                        reward_items.append(f"• {text}")
            else:
                flat_text = re.sub(r"\s+", " ", reward_soup.get_text(separator=" ", strip=True)).strip()
                if flat_text:
                    reward_items.append(f"• {flat_text}")

            reward_text = "\n".join(reward_items)

            results.append((code, reward_text, expiry))

    return results


def extract_active_codes_from_mobalytics(html: str):
    """
    Mobalytics ma prostsza struktura tabeli niz Game8: zwykly tekst w komorce
    kodu (bez inputa do kopiowania), nagrody jako lista <li>.
    Nie ma tu wyraznego rozdzielenia sekcji aktywne/wygasle w tej samej tabeli -
    Mobalytics zwykle trzyma je w osobnych tabelach pod naglowkiem "Expired".
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for table in soup.find_all("table"):
        prev_heading = table.find_previous(["h2", "h3"])
        if prev_heading and "expired" in prev_heading.get_text(strip=True).lower():
            continue

        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue  # to prawdopodobnie wiersz naglowka (th, nie td)

            code = cells[0].get_text(strip=True)
            if not code or code.lower() == "code":
                continue

            reward_items = [li.get_text(strip=True) for li in cells[1].find_all("li")]
            if reward_items:
                reward_text = "\n".join(f"• {item}" for item in reward_items if item)
            else:
                flat = cells[1].get_text(strip=True)
                reward_text = f"• {flat}" if flat else ""

            results.append((code, reward_text, None))  # Mobalytics nie pokazuje daty wygasniecia

    return results


def fetch_codes_from_scrape(game_key: str, game: dict):
    """
    Best-effort scraping dla gier bez wlasnego API (WuWa, NTE).
    Probuje kolejno: glowne zrodlo (Game8), a jesli zawiedzie (WAF/blad polaczenia)
    - zrodla fallback (np. Mobalytics) zdefiniowane w config.py pod "fallback_sources".
    Zwraca liste (moze byc pusta) z pierwszego zrodla, ktore FAKTYCZNIE odpowiedzialo,
    albo None jesli WSZYSTKIE zrodla zawiodly (uzywane do alertu o awarii).
    """
    result = _try_scrape_source(game["url"], game["name"], extract_active_codes_from_html)
    if result is not None:
        return result

    for source in game.get("fallback_sources", []):
        print(f"  [INFO] Glowne zrodlo zawiodlo, probuje fallback: {source['url']}")
        parser = extract_active_codes_from_mobalytics if source["parser"] == "mobalytics" else extract_active_codes_from_html
        result = _try_scrape_source(source["url"], game["name"], parser)
        if result is not None:
            return result

    return None  # wszystkie zrodla zawiodly


def _try_scrape_source(url: str, game_name: str, parser_fn):
    """
    Pobiera jedno zrodlo z retry i parsuje.
    Zwraca None przy WAF/bledzie polaczenia (total failure tego zrodla),
    liste (moze byc pusta) przy poprawnej odpowiedzi HTTP 200.
    """
    try:
        resp = get_with_retry(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        print(f"  [WARN] Nie udalo sie polaczyc z {url}: {e}", file=sys.stderr)
        return None

    if "awsWafCookie" in resp.text or "awswaf" in resp.text.lower():
        print(f"  [WARN] {url} zwrocilo wyzwanie AWS WAF dla {game_name}.")
        return None

    if resp.status_code != 200:
        print(f"  [WARN] {url} zwrocilo status {resp.status_code} dla {game_name}.")
        return None

    return parser_fn(resp.text)


def build_reward_lookup(game: dict):
    """
    Pobiera strone Game8 danej gry RAZ i zwraca slownik {kod: (nagrody, wygasniecie)}.
    Uzywane jako fallback, gdy API nie ma opisu nagrod dla nowego kodu.
    Zwraca pusty slownik przy WAF/bledzie - wywolujacy kod ma wtedy po prostu brak wzbogacenia.
    """
    if not game.get("url"):
        return {}

    scraped = fetch_codes_from_scrape("_lookup", game)
    if scraped is None:
        return {}
    return {code.upper(): (rewards, expiry) for code, rewards, expiry in scraped}


EMOJI = {
    "genshin": "💎",
    "zzz": "⚡",
    "hsr": "🚀",
    "wuwa": "🌊",
    "nte": "🌌",
}


def send_discord_ping(game_key: str, game: dict, code: str, rewards: str, expiry: str | None):
    role_mention = f"<@&{game['role_id']}>"
    emoji = EMOJI.get(game_key, "🎮")
    content = f"{role_mention} {emoji} Nowy kod do **{game['name']}**!"

    fields = [
        {"name": "Kod", "value": f"```{code}```", "inline": False},
    ]

    if rewards:
        fields.append({"name": "Nagrody", "value": rewards[:1000], "inline": False})

    if expiry:
        fields.append({"name": "Wygasa", "value": expiry, "inline": True})

    if game.get("redeem_base"):
        fields.append({
            "name": "Link",
            "value": f"[Odbierz tutaj]({game['redeem_base']}{code})",
            "inline": False,
        })

    embed = {
        "title": f"{emoji} {game['name']} — Nowy kod",
        "color": game["color"],
        "fields": fields,
        "footer": {"text": game["name"]},
    }

    if game.get("icon_url"):
        embed["thumbnail"] = {"url": game["icon_url"]}

    payload = {
        "content": content,
        "embeds": [embed],
    }

    resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    if resp.status_code >= 300:
        print(f"[WARN] Discord webhook zwrocil {resp.status_code}: {resp.text}", file=sys.stderr)
    time.sleep(1)


FAILURE_ALERT_THRESHOLD = 4  # 4 kolejne nieudane proby = ok. 24h przy sprawdzaniu co 6h
ALERT_ROLE_ID = "1520941252147941556"


def send_status_alert(game: dict, failures: int):
    role_mention = f"<@&{ALERT_ROLE_ID}>"
    payload = {
        "content": (
            f"{role_mention} ⚠️ Nie mogę sprawdzić kodów do **{game['name']}** od {failures} kolejnych prób "
            f"(ok. {failures * 6}h). Źródło może być trwale zablokowane - sprawdź logi Actions."
        )
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=15)
    except requests.RequestException as e:
        print(f"[WARN] Nie udalo sie wyslac alertu o awarii: {e}", file=sys.stderr)


def main():
    if not WEBHOOK_URL:
        print("Brak DISCORD_WEBHOOK_URL w zmiennych srodowiskowych.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    failures = state.get("_failures", {})
    any_new = False

    for game_key, game in GAMES.items():
        print(f"Sprawdzam {game['name']} (zrodlo: {game['source']})...")

        if game["source"] == "api":
            codes = fetch_codes_from_api(game_key, game)
        else:
            codes = fetch_codes_from_scrape(game_key, game)

        if codes is None:
            # calkowita awaria tego zrodla w tym runie - liczymy do alertu, nie przerywamy calego runu
            count = failures.get(game_key, 0) + 1
            failures[game_key] = count
            print(f"  [WARN] Zrodlo dla {game['name']} calkowicie niedostepne ({count}. raz z rzedu).")
            if count == FAILURE_ALERT_THRESHOLD:
                send_status_alert(game, count)
            state[game_key] = sorted(state.get(game_key, []))
            continue

        failures[game_key] = 0  # sukces - resetujemy licznik awarii
        print(f"  Znaleziono {len(codes)} aktywnych kodow.")

        # dedup bez rozrozniania wielkosci liter - porownujemy znormalizowane (upper),
        # ale wysylamy/wyswietlamy oryginalny zapis kodu
        seen_normalized = set(state.get(game_key, []))
        new_codes = [
            (code, rewards, expiry) for code, rewards, expiry in codes
            if code.upper() not in seen_normalized
        ]

        # jesli sa nowe kody bez nagrod (API czesto ma puste opisy), dociagamy z Game8
        # RAZ dla calej gry, nie osobno dla kazdego kodu
        if game["source"] == "api" and any(not rewards for _, rewards, _ in new_codes):
            print(f"  Brakuje nagrod dla czesci nowych kodow - probuje dociagnac z Game8...")
            lookup = build_reward_lookup(game)
            enriched = []
            for code, rewards, expiry in new_codes:
                if not rewards and code.upper() in lookup:
                    fallback_rewards, fallback_expiry = lookup[code.upper()]
                    rewards = fallback_rewards or rewards
                    expiry = expiry or fallback_expiry
                    print(f"    Dociagnieto nagrody dla {code} z Game8.")
                enriched.append((code, rewards, expiry))
            new_codes = enriched

        for code, rewards, expiry in new_codes:
            print(f"  Nowy kod: {code}")
            send_discord_ping(game_key, game, code, rewards, expiry)
            seen_normalized.add(code.upper())
            any_new = True

        state[game_key] = sorted(seen_normalized)
        time.sleep(1)

    # zawsze zapisujemy stan, nawet jesli nic nowego - zeby plik zawsze istnial w repo
    state["_failures"] = failures
    save_state(state)
    print("Zapisano stan." if any_new else "Brak nowych kodow.")


if __name__ == "__main__":
    main()
