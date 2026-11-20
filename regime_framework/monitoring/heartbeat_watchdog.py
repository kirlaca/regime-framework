"""
monitoring/heartbeat_watchdog.py — PRODUCTION_READINESS.md P3 #9. pont: külső (nem MQL5-beli)
felügyelet, ami észreveszi, ha az EA leállt/lefagyott, vagy kereskedési hibát halmozott fel.

Az EA (`RegimeFramework_EA.mq5`, `WriteHeartbeat()`) minden ÚJ M10-baron ír egy kis szöveges
állapotfájlt a közös (terminál-független) `MQL5/Files/` mappába (`FILE_COMMON` flag) —
`RegimeFramework_heartbeat_<szimbólum>_<magic>.txt`. Ez a script ezeket olvassa ki, és jelzi:
  1. STALE (elavult) — a fájl utolsó módosítási ideje régebbi, mint a várt bar-időköz többszöröse
     (ez jelezhet leállt EA-t, VPS/terminál-leállást, vagy egyszerűen piaci zárva tartást —
     hétvégén/ünnepnapon NORMÁLIS, ha nincs friss heartbeat, ezt a kimenet jelzi is).
  2. HIBA — `trade_error_count` > 0 (kereskedési hiba történt indítás óta, lásd `last_error_msg`).
  3. Minden egyéb esetben OK.

FONTOS: ez a script MAGA NEM küld push/Telegram/email értesítést — az EA saját maga küld push-t
(`SendNotification()`) kereskedési hiba esetén (a felhasználónak be kell kapcsolnia a Terminal
Eszközök > Beállítások > Értesítések fülön, és párosítania a MetaTrader mobil appot). Ez a script
egy MÁSODIK, FÜGGETLEN védelmi réteg — arra az esetre, ha az EA/terminál/VPS maga áll le teljesen
(amikor a `SendNotification()` már nem tudna lefutni). Adjon hozzá saját értesítési csatornát
(pl. Telegram bot API-hívás) a `main()` végén, ha ezt scheduláltan (pl. Windows Task Scheduler-rel)
futtatja — ehhez NEM kell MT5-kapcsolat, csak a heartbeat-fájlok elérése.

Kilépési kód: 0 = minden rendben, 1 = legalább egy figyelmeztetés/hiba (scriptelt/scheduláció
számára hasznos: `if errorlevel 1 ...`).

Futtatás: python -m regime_framework.monitoring.heartbeat_watchdog
(NEM igényel MT5-terminál-kapcsolatot, csak a Common Files mappa elérését.)
"""

import glob
import logging
import os
import time

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# A bar-idokoz (M10 = 600 mp) tobbszorose, mielott "elavultnak" jeloljuk a heartbeat-et --
# annyi tureshatarral, hogy egy-ket kesleltetett tick ne riasszon feleslegesen.
MAX_STALE_SECONDS = 3 * 600  # 30 perc

COMMON_FILES_DIR = os.path.join(
    os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", "Common", "Files"
)
HEARTBEAT_PATTERN = "RegimeFramework_heartbeat_*.txt"


def parse_heartbeat(path):
    fields = {}
    with open(path, "r", encoding="ansi", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            fields[key] = value
    return fields


def check_heartbeat(path):
    fields = parse_heartbeat(path)
    age_seconds = time.time() - os.path.getmtime(path)
    is_stale = age_seconds > MAX_STALE_SECONDS
    error_count = int(fields.get("trade_error_count", "0") or "0")

    status = "OK"
    if is_stale:
        status = "STALE"
    if error_count > 0:
        status = "HIBA" if status == "OK" else f"{status}+HIBA"

    return {
        "file": os.path.basename(path), "status": status, "age_seconds": age_seconds,
        "fields": fields, "error_count": error_count,
    }


def main():
    if not os.path.isdir(COMMON_FILES_DIR):
        logger.error("❌ A közös Files mappa nem található: %s", COMMON_FILES_DIR)
        return 1

    paths = glob.glob(os.path.join(COMMON_FILES_DIR, HEARTBEAT_PATTERN))
    if not paths:
        logger.warning("⚠️ Egyetlen heartbeat-fájl sem található (%s) — fut-e az EA valamelyik "
                        "chartra felhelyezve?", os.path.join(COMMON_FILES_DIR, HEARTBEAT_PATTERN))
        return 1

    logger.info("--- 🔎 RegimeFramework EA heartbeat-ellenőrzés (%s) ---\n", time.strftime("%Y-%m-%d %H:%M:%S"))

    any_issue = False
    for path in sorted(paths):
        result = check_heartbeat(path)
        f = result["fields"]
        any_issue = any_issue or result["status"] != "OK"

        icon = "✅" if result["status"] == "OK" else "🛑"
        logger.info("%s %s — állapot: %s", icon, result["file"], result["status"])
        logger.info("    utolsó heartbeat: %.0f másodperce | szerver idő a fájlban: %s",
                    result["age_seconds"], f.get("server_time", "?"))
        logger.info("    rezsim-osztályozó kész: %s | nyitott pozíció: %s | heartbeat számláló: %s",
                    f.get("classifier_ready", "?"), f.get("open_positions", "?"), f.get("heartbeat_counter", "?"))
        logger.info("    equity: %s | szabad margin: %s", f.get("account_equity", "?"), f.get("account_margin_free", "?"))
        if result["error_count"] > 0:
            logger.info("    ⚠️ kereskedési hibák száma indítás óta: %d | utolsó: %s",
                        result["error_count"], f.get("last_error_msg", "?"))
        if result["status"].startswith("STALE"):
            logger.info("    ⚠️ elavult heartbeat -- ELLENŐRIZD, hogy fut-e még az EA/terminál/VPS. "
                        "(Hétvégén/piaci zárás idején ez VÁRHATÓ, nem feltétlenül hiba.)")
        logger.info("")

    if not any_issue:
        logger.info("Minden ellenőrzött EA-példány rendben, friss heartbeat-tel fut.")
    return 1 if any_issue else 0


if __name__ == "__main__":
    raise SystemExit(main())
