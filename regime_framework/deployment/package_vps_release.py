"""
deployment/package_vps_release.py — összegyűjti a VPS-re/élő szerverre kiteendő fájlokat egy
verziózott `dist/vN/` mappába, hogy egyetlen mappa átmásolásával lehessen telepíteni.

Mit csomagol (lásd PRODUCTION_READINESS.md P3 #8/#9):
  - `RegimeFramework_EA.ex5`      -- a lefordított EA (a MQL5/Experts/ megfelelő mappájába kerül)
  - `RegimeFramework_EA_US100Cash.set` / `_US500Cash.set` -- az ÉLŐ presetek (US100 fix lotos,
    US500 margin-alapú -- lásd PRODUCTION_READINESS.md P1 #3). US30 SZÁNDÉKOSAN NINCS benne, mert
    nem élesített (a hold-out teszt megbukott rajta).
  - `RegimeFramework_HeartbeatWatchdog.exe` -- a monitoring watchdog, Python-telepítés nélkül futtatható
  - `TELEPITES.txt` -- generált, emberi olvasásra szánt lépéslista a csomagban

BIZTONSÁGI ELLENŐRZÉS (ne csomagoljunk véletlenül elavult buildet): összeveti a forrásfájlok
(`.mq5`, `heartbeat_watchdog.py`) és a lefordított/buildelt kimenetek (`.ex5`, `.exe`)
módosítási idejét -- ha a forrás ÚJABB, mint a build, FIGYELMEZTET (nem tiltja le, de a
`--force` nélküli futtatás megkérdezi, hogy biztosan folytassuk-e), mert ez azt jelentené, hogy
a csomagolt fájl NEM a legfrissebb kódot tartalmazza.

Futtatás: python -m regime_framework.deployment.package_vps_release
(Nem igényel MT5-terminál-kapcsolatot -- tisztán fájlműveletek.)
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# (forrás, build) parok -- a build mindig a PROJECT_ROOT-hoz kepest ertendo, a friss-e ellenorzeshez
STALENESS_CHECKS = [
    (PROJECT_ROOT / "RegimeFramework_EA.mq5", PROJECT_ROOT / "RegimeFramework_EA.ex5"),
    (PROJECT_ROOT / "regime_framework" / "monitoring" / "heartbeat_watchdog.py",
     PROJECT_ROOT / "dist" / "RegimeFramework_HeartbeatWatchdog.exe"),
]

# (forras eleresi ut, cel fajlnev) parok -- ez kerul be minden egyes kiadasi mappaba
RELEASE_FILES = [
    (PROJECT_ROOT / "RegimeFramework_EA.ex5", "RegimeFramework_EA.ex5"),
    (PROJECT_ROOT / "presets" / "RegimeFramework_EA_US100Cash.set", "RegimeFramework_EA_US100Cash.set"),
    (PROJECT_ROOT / "presets" / "RegimeFramework_EA_US500Cash.set", "RegimeFramework_EA_US500Cash.set"),
    (PROJECT_ROOT / "dist" / "RegimeFramework_HeartbeatWatchdog.exe", "RegimeFramework_HeartbeatWatchdog.exe"),
]

README_TEMPLATE = """RegimeFramework -- VPS telepitesi csomag ({version})
====================================================

Ez a mappa mindent tartalmaz, amit a kereskedesi VPS-re/szerverre at kell masolni.
Reszletes indoklas/hatterinformacio: PRODUCTION_READINESS.md (a fejlesztoi gepen).

1. RegimeFramework_EA.ex5
   -> Masold a VPS MT5-terminaljanak "MQL5/Experts/" mappajaba (pl. egy sajat
      "RegimeFramework" almappaba). A forras (.mq5) NEM kell a VPS-re, csak a lefordított .ex5.

2. RegimeFramework_EA_US100Cash.set / RegimeFramework_EA_US500Cash.set
   -> Masold a VPS MT5-terminaljanak "MQL5/Presets/" mappajaba (pl. ugyanabba a
      "RegimeFramework" almappaba).
   -> US100Cash# chartra az US100-as presetet toltsd be (fix 0.1 lot).
   -> US500Cash# chartra az US500-as presetet toltsd be (margin-alapu meretezes, alloc_pct=1.762%).
   -> US30Cash#-ra NINCS itt preset -- az a szimbolum SZANDEKOSAN nincs elesitve.

3. RegimeFramework_HeartbeatWatchdog.exe
   -> Masold barhova a VPS-re (pl. C:\\RegimeFramework\\monitoring\\).
   -> Allits be egy utemezett feladatot (Windows Feladatutemezo), ami 15-30 percenkent futtatja.
   -> Nem igenyel Python-telepitest a VPS-en.

4. FONTOS, amit a VPS-i MT5 Terminalban KULON be kell allitani (ezt fajl-masolassal nem lehet):
   -> Eszkozok > Beallitasok > Ertesitesek fulon MetaQuotes ID megadasa + mobil app parositasa,
      hogy az EA sajat push-ertesitesei (kritikus kereskedesi hibaknal) tenylegesen megerkezzenek.

5. Ha barmi elteres van a fenti fajlok es a fejlesztoi gepen levo forras kozott, ELOSZOR
   forditsd/build-eld ujra, csak UTANA csomagold (lasd package_vps_release.py --force, ha
   tudatosan egy regebbi build-et akarsz csomagolni).
"""


def check_staleness(force):
    any_stale = False
    for source, build in STALENESS_CHECKS:
        if not build.exists():
            logger.warning("⚠️ Hiányzó build: %s (forrás: %s) -- előbb hozd létre.", build, source)
            any_stale = True
            continue
        if not source.exists():
            continue  # forras hianya kulon eset, de a build meg letezhet -- nem blokkolo
        if source.stat().st_mtime > build.stat().st_mtime:
            logger.warning("⚠️ A forrás (%s) ÚJABB, mint a build (%s) -- a csomagolt fájl "
                            "ELAVULT lehet. Fordítsd/build-eld újra, mielőtt kiadod.", source.name, build.name)
            any_stale = True
    if any_stale and not force:
        answer = input("Folytassuk ELAVULT build-del a csomagolást? [y/N]: ").strip().lower()
        if answer != "y":
            logger.info("Megszakítva -- fordítsd/build-eld újra a jelzett fájlokat, majd futtasd újra.")
            sys.exit(1)
    return any_stale


def next_version(dist_dir):
    existing = []
    if dist_dir.exists():
        for p in dist_dir.iterdir():
            if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit():
                existing.append(int(p.name[1:]))
    return f"v{max(existing, default=0) + 1}"


def main():
    parser = argparse.ArgumentParser(description="VPS telepítési csomag összeállítása a dist/ mappába.")
    parser.add_argument("--force", action="store_true", help="elavult build esetén se kérdezzen vissza")
    args = parser.parse_args()

    missing = [str(source) for source, _ in RELEASE_FILES if not source.exists()]
    if missing:
        logger.error("❌ Hiányzó fájl(ok), nem lehet csomagolni:\n  " + "\n  ".join(missing))
        return 1

    check_staleness(args.force)

    dist_dir = PROJECT_ROOT / "dist"
    version = next_version(dist_dir)
    release_dir = dist_dir / version
    release_dir.mkdir(parents=True, exist_ok=False)

    for source, dest_name in RELEASE_FILES:
        shutil.copy2(source, release_dir / dest_name)
        logger.info("  ✅ %s -> %s/%s", source, version, dest_name)

    (release_dir / "TELEPITES.txt").write_text(README_TEMPLATE.format(version=version), encoding="utf-8")
    logger.info("  ✅ TELEPITES.txt generálva")

    logger.info("\n📦 Kiadási csomag kész: %s", release_dir)
    logger.info("   Másold át ezt a MAPPÁT (a tartalmát) a VPS-re, és kövesd a TELEPITES.txt lépéseit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
