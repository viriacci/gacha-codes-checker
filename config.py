GAMES = {
    "genshin": {
        "name": "Genshin Impact",
        "source": "api",
        "api_key": "genshin",  # klucz w JSON-ie z db.hashblen.com/codes
        "url": "https://game8.co/games/Genshin-Impact/archives/304759",  # fallback: dociaganie nagrod gdy API ich nie ma
        "role_id": "1521672555042177196",
        "color": 0x1E90FF,
        "redeem_base": "https://genshin.hoyoverse.com/en/gift?code=",
        "icon_url": "https://raw.githubusercontent.com/viriacci/gacha-codes-checker/main/icons/Genshin.png",
    },
    "zzz": {
        "name": "Zenless Zone Zero",
        "source": "api",
        "api_key": "zzz",
        "url": "https://game8.co/games/Zenless-Zone-Zero/archives/435683",
        "role_id": "1521672938330394774",
        "color": 0x9B30FF,
        "redeem_base": "https://zenless.hoyoverse.com/redemption?code=",
        "icon_url": "https://raw.githubusercontent.com/viriacci/gacha-codes-checker/main/icons/zzz.png",
    },
    "hsr": {
        "name": "Honkai: Star Rail",
        "source": "api",
        "api_key": "hsr",
        "url": "https://game8.co/games/Honkai-Star-Rail/archives/410296",
        "role_id": "1521672961747058782",
        "color": 0xFFD700,
        "redeem_base": "https://hsr.hoyoverse.com/gift?code=",
        "icon_url": "https://raw.githubusercontent.com/viriacci/gacha-codes-checker/main/icons/HSR.png",
    },
    "wuwa": {
        "name": "Wuthering Waves",
        "source": "scrape",  # brak publicznego API - scrapujemy Game8, best-effort
        "url": "https://game8.co/games/Wuthering-Waves/archives/453149",
        "role_id": "1521796934874955826",
        "color": 0x00CED1,
        "redeem_base": None,  # WuWa nie ma redeem strony z URL - kod wpisuje sie w grze
        "icon_url": "https://raw.githubusercontent.com/viriacci/gacha-codes-checker/main/icons/Wuwa.png",
    },
    "nte": {
        "name": "Neverness to Everness",
        "source": "scrape",  # brak publicznego API - scrapujemy Game8, best-effort
        "url": "https://game8.co/games/Neverness-to-Everness/archives/593718",
        "role_id": "1521796878403108894",
        "color": 0xFF4500,
        "redeem_base": None,
        "fallback_sources": [
            {"url": "https://mobalytics.gg/neverness-to-everness/redemption-codes", "parser": "mobalytics"},
        ],
        "icon_url": "https://raw.githubusercontent.com/viriacci/gacha-codes-checker/main/icons/NTE.png",
    },
}

CODES_API_URL = "https://db.hashblen.com/codes"
STATE_FILE = "seen_codes.json"
