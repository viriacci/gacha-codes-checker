GAMES = {
    "genshin": {
        "name": "Genshin Impact",
        "source": "api",
        "api_key": "genshin",  # klucz w JSON-ie z db.hashblen.com/codes
        "role_id": "1521672555042177196",
        "color": 0x1E90FF,
        "redeem_base": "https://genshin.hoyoverse.com/en/gift?code=",
        "icon_url": "https://raw.githubusercontent.com/viriacci/gacha-codes-checker/cfe4564b5059cb84ee9216a030e0957ac34d43dd/icons/Genshin.png",
    },
    "zzz": {
        "name": "Zenless Zone Zero",
        "source": "api",
        "api_key": "zzz",
        "role_id": "1521672938330394774",
        "color": 0x9B30FF,
        "redeem_base": "https://zenless.hoyoverse.com/redemption?code=",
        "icon_url": "https://github.com/viriacci/gacha-codes-checker/blob/main/icons/zzz.png?raw=true",
    },
    "hsr": {
        "name": "Honkai: Star Rail",
        "source": "api",
        "api_key": "hsr",
        "role_id": "1521672961747058782",
        "color": 0xFFD700,
        "redeem_base": "https://hsr.hoyoverse.com/gift?code=",
        "icon_url": "https://github.com/viriacci/gacha-codes-checker/blob/main/icons/HSR.png?raw=true",
    },
    "wuwa": {
        "name": "Wuthering Waves",
        "source": "scrape",  # brak publicznego API - scrapujemy Game8, best-effort
        "url": "https://game8.co/games/Wuthering-Waves/archives/453149",
        "role_id": "1521796934874955826",
        "color": 0x00CED1,
        "redeem_base": None,  # WuWa nie ma redeem strony z URL - kod wpisuje sie w grze
        "icon_url": "https://github.com/viriacci/gacha-codes-checker/blob/main/icons/Wuwa.png?raw=true",
    },
    "nte": {
        "name": "Neverness to Everness",
        "source": "scrape",  # brak publicznego API - scrapujemy Game8, best-effort
        "url": "https://game8.co/games/Neverness-to-Everness/archives/593718",
        "role_id": "1521796878403108894",
        "color": 0xFF4500,
        "redeem_base": None,
        "icon_url": "https://github.com/viriacci/gacha-codes-checker/blob/main/icons/NTE.png?raw=true",
    },
}
 
CODES_API_URL = "https://db.hashblen.com/codes"
STATE_FILE = "seen_codes.json"
 
