"""
Sprawdza kody do gier (API dla Genshin/ZZZ/HSR, scraping Game8 dla WuWa/NTE)
i wysyła ping na Discorda przy nowych kodach.
Uruchamiane cyklicznie przez GitHub Actions (patrz .github/workflows/check_codes.yml).
"""

import json
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from datetime import datetime, timezone
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import GAMES, CODES_API_URL, STATE_FILE

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
ADMIN_WEBHOOK_URL = os.environ.get("ADMIN_DISCORD_WEBHOOK_URL")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
}


def sanitize_code(raw_code: str) -> str:
    """
    Prawdziwy kod do gry to zawsze litery/cyfry (czasem podkreslnik).
    Usuwa wszystko inne - emoji, spacje, znaczniki "NEW" ktore czasem
    doklejaja sie do tekstu kodu przy scrapowaniu roznych stron.
    """
    code = (raw_code or "").strip()
    return code if re.fullmatch(r"[A-Za-z0-9_-]{3,100}", code) else ""


def get_with_retry(url: str, headers: dict = None, timeout: int = 20, attempts: int = 3):
    """
    GET z ponowieniami przy chwilowym bledzie sieci (timeout, zerwane polaczenie).
    Nie ponawia przy odpowiedzi HTTP z tresci (np. 202 WAF) - to nie jest blad sieci,
    tylko celowa odpowiedz serwera, ktora i tak obsluzy kod wolajacy.
    """
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < attempts:
                try:
                    delay = min(30, max(1, float(response.headers.get("Retry-After", 3 * attempt))))
                except ValueError:
                    delay = 3 * attempt
                time.sleep(delay)
                continue
            return response
        except requests.RequestException as e:
            last_exc = e
            if attempt < attempts:
                wait = 3 * attempt
                print(f"  [WARN] Proba {attempt}/{attempts} nie powiodla sie ({e}), ponawiam za {wait}s...")
                time.sleep(wait)
    raise last_exc


def load_state():
    if not Path(STATE_FILE).exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                print(f"  [WARN] {STATE_FILE} jest pusty - zaczynam od czystego stanu.")
                raise ValueError("Pusty plik stanu")
            state = json.loads(content)
            if not isinstance(state, dict) or any(not isinstance(v, list) for k, v in state.items() if not k.startswith("_")) or not isinstance(state.get("_failures", {}), dict):
                raise ValueError("Niepoprawna struktura stanu")
            return state
    except json.JSONDecodeError as e:
        print(f"  [WARN] {STATE_FILE} jest uszkodzony ({e}) - zaczynam od czystego stanu "
              f"(niebezpieczenstwo: zdublowane pingi dla juz wyslanych kodow w tym runie).")
        raise


def save_state(state):
    target = Path(STATE_FILE)
    tmp = target.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    tmp.replace(target)


_api_cache = {}
def fetch_codes_from_api(game_key: str, game: dict):
    """Pobiera kody dla gier obslugiwanych przez db.hashblen.com/codes (bez scrapowania)."""
    try:
        if CODES_API_URL not in _api_cache:
            resp = get_with_retry(CODES_API_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("Niepoprawny format API")
            _api_cache[CODES_API_URL] = data
        data = _api_cache[CODES_API_URL]
    except (requests.RequestException, ValueError) as e:
        print(f"[ERROR] API {CODES_API_URL} nie odpowiedzialo poprawnie: {e}", file=sys.stderr)
        return None

    entries = data.get(game["api_key"])
    if not isinstance(entries, list):
        return None
    results = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("code"), str):
            return None
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
        code = sanitize_code(entry["code"])
        if not code:
            continue
        results.append((code, reward_text, None))
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

            code = sanitize_code(code_input["value"])
            if not code:
                continue

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

            code = sanitize_code(cells[0].get_text(strip=True))
            if not code or code.upper() == "CODE":
                continue

            reward_items = [li.get_text(strip=True) for li in cells[1].find_all("li")]
            if reward_items:
                reward_text = "\n".join(f"• {item}" for item in reward_items if item)
            else:
                flat = cells[1].get_text(strip=True)
                reward_text = f"• {flat}" if flat else ""

            results.append((code, reward_text, None))  # Mobalytics nie pokazuje daty wygasniecia

    return results


def fetch_open_codes(game):
    try:
        resp = get_with_retry("https://api.ennead.cc/codes/" + game["open_slug"], timeout=15)
        resp.raise_for_status()
        entries = resp.json()
        if not isinstance(entries, list):
            raise ValueError("Expected list")
        results = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("code"), str):
                raise ValueError("Invalid entry")
            code = sanitize_code(entry["code"])
            if not code:
                raise ValueError("Invalid code")
            rewards = entry.get("rewards") or []
            if not isinstance(rewards, list) or not all(isinstance(x, str) for x in rewards):
                raise ValueError("Invalid rewards")
            results.append((code, "\n".join("• " + x for x in rewards), None))
        return results
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"  [WARN] OpenGachaCodes: {type(exc).__name__}")
        return None


def extract_gachafeed(html):
    """Read explicit working-code history or the counted active-code summary."""
    soup = BeautifulSoup(html, "html.parser")
    expected = ["code", "found", "rewards", "end date", "status"]
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [x.get_text(" ", strip=True).lower() for x in rows[0].find_all(["th", "td"])]
        if header != expected:
            continue
        result = []
        malformed = False
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) != 5:
                malformed = True
                break
            status = cells[4].get_text(" ", strip=True).casefold().strip("✓✔ ")
            if status != "working":
                continue
            code = sanitize_code(cells[0].get_text(strip=True))
            if not code:
                malformed = True
                break
            reward = cells[2].get_text(" ", strip=True)
            expiry = cells[3].get_text(" ", strip=True)
            if expiry.lower() in ("not stated", "no expiry listed", ""):
                expiry = None
            if expiry:
                try:
                    if datetime.strptime(expiry, "%b %d, %Y").date() < datetime.now(timezone.utc).date():
                        continue
                except ValueError:
                    pass
            result.append((code, None if reward.lower() == "not stated" else "• " + reward, expiry))
        if result and not malformed:
            return result
        # An empty history is not sufficient evidence that there are no working codes.
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    summary = re.search(r"there (?:are|is) (\d+) working (?:Neverness to Everness|Wuthering Waves) codes?\s*:\s*([^.!?]+)", text, re.I)
    if summary:
        count = int(summary.group(1))
        raw_codes = re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", summary.group(2).strip())
        codes = [sanitize_code(x) for x in raw_codes]
        if count == len(codes) and count > 0 and all(codes) and len(set(codes)) == count:
            return [(code, None, None) for code in codes]
    if re.search(r"\b0 active codes\b|\bno (?:active|working) (?:Neverness to Everness|Wuthering Waves) codes\b", text, re.I):
        return []
    return None


def extract_ntebuild(html):
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [x.get_text(" ", strip=True).lower() for x in rows[0].find_all(["th", "td"])]
        if header != ["code", "rewards", "validity", "status"]:
            continue
        result = []
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) != 4:
                return None
            if cells[3].get_text(" ", strip=True).casefold().strip("✓✔ ") != "working":
                continue
            code = sanitize_code(cells[0].get_text(strip=True))
            if not code:
                return None
            reward = cells[1].get_text(" ", strip=True)
            result.append((code, "• " + reward if reward else None, None))
        return result if len(rows) > 1 else None
    return None


def fetch_ntebuild():
    try:
        response = get_with_retry("https://www.ntebuild.com/codes", headers=HEADERS, timeout=15)
        response.raise_for_status()
        result = extract_ntebuild(response.text)
        if result is not None:
            print(f"[INFO] NTEBuild: {len(result)} aktywnych kodow")
        else:
            print("[WARN] NTEBuild: nierozpoznana struktura")
        return result
    except (requests.RequestException, ValueError):
        print("[WARN] NTEBuild: zrodlo niedostepne")
        return None


def fetch_gachafeed(game):
    url = "https://gachafeed.moe/" + game["open_slug"] + "/codes/"
    try:
        response = get_with_retry(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        result = extract_gachafeed(response.text)
        if result is None:
            print("[WARN] Gachafeed: nierozpoznana struktura tabeli")
        else:
            print(f"[INFO] Gachafeed: {len(result)} aktywnych kodow")
        return result
    except (requests.RequestException, ValueError):
        print("[WARN] Gachafeed: zrodlo niedostepne")
        return None


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

    results = parser_fn(resp.text)
    if not results:
        print(f"  [WARN] Brak rozpoznanych kodow: {url}; wynik niepewny, probuje inne zrodlo.")
        return None
    return results


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


def expiry_date(value):
    if not value:
        return None
    value = re.sub(r"^\s*(?:expires?|until|end date)\s*:?\s*", "", str(value), flags=re.I).strip()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            pass
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else None
    except ValueError:
        return None


def collect_codes(game_key, game):
    sources = []
    if game["source"] == "api":
        sources.append(("API", lambda: fetch_codes_from_api(game_key, game)))
        sources.append(("Game8", lambda: fetch_codes_from_scrape(game_key, game)))
    else:
        sources += [("OpenGachaCodes", lambda: fetch_open_codes(game)),
                    ("Gachafeed", lambda: fetch_gachafeed(game)),
                    ("Game8/fallback", lambda: fetch_codes_from_scrape(game_key, game))]
        if game_key == "nte":
            sources.append(("NTEBuild", fetch_ntebuild))
    merged = {}
    successful = 0
    now = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [(name, pool.submit(fn)) for name, fn in sources]
        for name, future in tasks:
            try:
                result = future.result()
            except Exception as exc:
                print(f"[WARN] {name}: {type(exc).__name__}")
                continue
            if result is None:
                continue
            successful += 1
            print(f"[INFO] {name}: {len(result)} codes")
            for code, rewards, expiry in result:
                deadline = expiry_date(expiry)
                if deadline and deadline <= now:
                    continue
                key = code.upper()
                old = merged.get(key)
                if old:
                    old_deadline = expiry_date(old[2])
                    selected = expiry if deadline and (not old_deadline or deadline < old_deadline) else old[2]
                    merged[key] = (old[0], old[1] or rewards, selected)
                else:
                    merged[key] = (code, rewards, expiry)
    return list(merged.values()) if successful else None


def build_group(game_key, game, codes, ping=True):
    emoji = EMOJI.get(game_key, "🎮")
    fields = []
    now = datetime.now(timezone.utc)
    for code, rewards, expiry in codes:
        value = "`" + code + "`"
        if rewards:
            value += "\n" + rewards[:650]
        if expiry:
            deadline = expiry_date(expiry)
            if deadline and deadline <= now:
                value += "\n⛔ Kod wygasł"
            elif deadline and deadline <= now + timedelta(hours=24):
                value += "\n⚠️ Wygasa w ciągu 24h: " + expiry[:120]
            else:
                value += "\nWygasa: " + expiry[:120]
        if game.get("redeem_base") and not (expiry_date(expiry) and expiry_date(expiry) <= now):
            value += "\n[Odbierz](" + game["redeem_base"] + code + ")"
        fields.append({"name":code,"value":value[:1024],"inline":False})
    embed = {"title":f"{emoji} {game['name']} — kody","color":game["color"],"fields":fields}
    if game.get("icon_url"):
        embed["thumbnail"] = {"url":game["icon_url"]}
    return {"content":f"<@&{game['role_id']}> {emoji} Nowe kody do **{game['name']}**!" if ping else "",
            "embeds":[embed],"allowed_mentions":{"parse":[],"roles":[game["role_id"]] if ping else []}}


def post_webhook(payload, url=None, method="POST"):
    url = url or WEBHOOK_URL
    if not url:
        raise RuntimeError("Webhook unavailable")
    for attempt in range(4):
        try:
            if method == "POST":
                response = requests.post(url, json=payload, timeout=15)
            else:
                response = requests.patch(url, json=payload, timeout=15)
        except requests.RequestException:
            raise RuntimeError("Discord network error") from None
        if response.status_code == 429 and attempt < 3:
            time.sleep(min(60, max(1, float(response.json().get("retry_after", 1)))))
            continue
        if response.status_code >= 300:
            raise RuntimeError(f"Discord HTTP {response.status_code}")
        return response


def private_notice(message):
    # Never send operational information to the public webhook.
    print("::notice::" + message.replace("\n"," "))
    if ADMIN_WEBHOOK_URL:
        try:
            post_webhook({"content":message[:1800],"allowed_mentions":{"parse":[]}}, ADMIN_WEBHOOK_URL)
        except (RuntimeError, ValueError):
            print("[WARN] Private webhook delivery failed")


def expire_messages(state):
    for message_id, item in list(state.get("_messages", {}).items()):
        codes = [tuple(c) for c in item["codes"]]
        expired = sorted(c[0] for c in codes if expiry_date(c[2]) and expiry_date(c[2]) <= datetime.now(timezone.utc))
        if expired == item.get("expired", []):
            continue
        try:
            post_webhook(build_group(item["game"], GAMES[item["game"]], codes, False),
                         WEBHOOK_URL.split("?")[0].rstrip("/") + "/messages/" + message_id, "PATCH")
            item["expired"] = expired
        except (RuntimeError, ValueError) as exc:
            if str(exc) == "Discord HTTP 404":
                del state["_messages"][message_id]
            else:
                print("[WARN] Expiry update failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", choices=GAMES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not WEBHOOK_URL and not args.dry_run:
        print("Brak DISCORD_WEBHOOK_URL w zmiennych srodowiskowych.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    failures = state.get("_failures", {})
    any_new = False
    errors = False

    for game_key, game in GAMES.items():
        if args.game and game_key != args.game:
            continue
        print(f"Sprawdzam {game['name']} (zrodlo: {game['source']})...")

        codes = collect_codes(game_key, game)

        if codes is None:
            # calkowita awaria tego zrodla w tym runie - liczymy do alertu, nie przerywamy calego runu
            count = failures.get(game_key, 0) + 1
            failures[game_key] = count
            print(f"  [WARN] Zrodlo dla {game['name']} calkowicie niedostepne ({count}. raz z rzedu).")
            if not args.dry_run and (count == 1 or count % 4 == 0):
                private_notice(f"Awaria źródeł {game['name']}: {count} kolejnych prób")
            errors = True
            state[game_key] = sorted(state.get(game_key, []))
            continue

        if failures.get(game_key, 0) and not args.dry_run:
            private_notice(f"Przywrócono źródło: {game['name']}")
        failures[game_key] = 0
        print(f"  Znaleziono {len(codes)} aktywnych kodow.")

        # dedup bez rozrozniania wielkosci liter - porownujemy znormalizowane (upper),
        # ale wysylamy/wyswietlamy oryginalny zapis kodu
        seen_normalized = {x.upper() for x in state.get(game_key, [])}
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

        # Five embeds fields per message keep total safely below Discord's 6000-character limit.
        unique = {code.upper(): (code, rewards, expiry) for code, rewards, expiry in new_codes}
        pending = list(unique.values())
        for offset in range(0, len(pending), 5):
            group = pending[offset:offset + 5]
            for code, _, _ in group:
                print(f"  Nowy kod: {code}")
            if args.dry_run:
                continue
            try:
                url = WEBHOOK_URL + ("&" if "?" in WEBHOOK_URL else "?") + "wait=true"
                response = post_webhook(build_group(game_key, game, group, ping=offset == 0), url)
                message_id = response.json()["id"]
            except (RuntimeError, ValueError, KeyError):
                print("[ERROR] Discord delivery failed; codes remain pending", file=sys.stderr)
                errors = True
                continue
            seen_normalized.update(code.upper() for code, _, _ in group)
            if any(expiry_date(expiry) for _, _, expiry in group):
                state.setdefault("_messages", {})[message_id] = {"game":game_key,"codes":group,"expired":[]}
            state[game_key] = sorted(seen_normalized)
            state["_failures"] = failures
            save_state(state)
            any_new = True

        state[game_key] = sorted(seen_normalized)
        time.sleep(1)

    # zawsze zapisujemy stan, nawet jesli nic nowego - zeby plik zawsze istnial w repo
    state["_failures"] = failures
    if not args.dry_run:
        expire_messages(state)
        save_state(state)
    print("Zapisano stan." if any_new else "Brak nowych kodow.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
