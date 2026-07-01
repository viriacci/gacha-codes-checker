GAMES = {
    "genshin": {
        "name": "Genshin Impact",
        "url": "https://game8.co/games/Genshin-Impact/archives/304759",
        "role_id": "1521672555042177196",
        "color": 0x1E90FF,
        "redeem_base": "https://genshin.hoyoverse.com/en/gift?code=",
    },
    "zzz": {
        "name": "Zenless Zone Zero",
        "url": "https://game8.co/games/Zenless-Zone-Zero/archives/435683",
        "role_id": "1521672938330394774",
        "color": 0x9B30FF,
        "redeem_base": "https://zenless.hoyoverse.com/redemption?code=",
    },
    "hsr": {
        "name": "Honkai: Star Rail",
        "url": "https://game8.co/games/Honkai-Star-Rail/archives/410296",
        "role_id": "1521672961747058782",
        "color": 0xFFD700,
        "redeem_base": "https://hsr.hoyoverse.com/gift?code=",
    },
    "wuwa": {
        "name": "Wuthering Waves",
        "url": "https://game8.co/games/Wuthering-Waves/archives/453149",
        "role_id": "1521796934874955826",
        "color": 0x00CED1,
        "redeem_base": "https://mc.kurogames.com/main/exchangeCode",  # WuWa nie ma prostego ?code= redeema, patrz uwaga w scraper.py
    },
    "nte": {
        "name": "Neverness to Everness",
        "url": "https://game8.co/games/Neverness-to-Everness/archives/593718",
        "role_id": "1521796878403108894",
        "color": 0xFF4500,
        "redeem_base": None,  # do potwierdzenia - gra jeszcze nie ma ugruntowanego systemu redeem URL
    },
}

STATE_FILE = "seen_codes.json"
