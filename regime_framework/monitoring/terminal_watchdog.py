"""
monitoring/terminal_watchdog.py -- kis, ÁLLANDÓ háttérfolyamat, ami a `terminals.json`-ban
felsorolt MT5-terminálokat figyeli, és ha valamelyik NEM fut, ÚJRAINDÍTJA.

**Miért kell ez, és miért nem elég, ha a dashboard_web.py saját maga indítja újra a terminált
(2026-09-13, ÉLESBEN felfedezett hiba, lásd SESSION_LOG.md "Heartbeat archiválás" bejegyzését)**:
a `dashboard_web.py` (és minden általa KÖZVETLENÜL indított gyermek-folyamat) Session 0-ban fut
-- a láthatatlan "services" munkamenetben --, mert MAGA a dashboard .exe is egy SSH-n át hívott
`wmic process call create`-del lett elindítva (lásd a deploy-receptet a fejléc-kommentekben
máshol). Egy Session-0-beli szülő GYERMEKE -- FÜGGETLENÜL attól, melyik API-val (`wmic`,
`subprocess.Popen`, stb.) hozzuk létre -- ALAPBÓL szintén Session 0-ba kerül. Egy GUI-alkalmazás
(mint a terminal64.exe) Session 0-ban NEM kap látható asztalt -- ezért a felhasználó RDP-
képernyőjén semmi nem jelenik meg, még ha a folyamat technikailag el is indul (élesben pontosan
ez történt: a PID létrejött, de `SessionId=0`-ban, láthatatlanul).

**EZÉRT ennek a scriptnek KIZÁRÓLAG a felhasználó SAJÁT, INTERAKTÍV RDP-munkameneteéből szabad
elindulnia** (pl. a Windows "Indítópult" (`shell:startup`) mappájából automatikusan bejelentkezéskor,
vagy kézi dupla kattintással egy .cmd-ből -- UGYANOTT/UGYANÚGY, ahogy a terminálokat magukat is
elindítod). ÍGY minden GYERMEKE (a terminálok, amiket újraindít) UGYANABBA a látható munkamenetbe
kerül, mint ő maga -- ez teljesen elkerüli a Session 0 problémát, mert a láncban SOHA nincs egy
SSH/WMI-eredetű, session-mentes ős.

**A `dashboard_web.py` maga NEM indíthatja el ezt a scriptet** -- ő saját maga Session 0-ban ül,
tehát a gyermeke (ez a watchdog) is oda kerülne, ami semmit nem oldana meg. A "Heartbeat
archiválás + reset" funkció (lásd `_restart_terminal()` dashboard_web.py-ban) ezután MÁR NEM
próbálja közvetlenül újraindítani a terminált -- csak leállítja, és ez a watchdog (legkésőbb
`WATCHDOG_INTERVAL_S` másodpercen belül) automatikusan észreveszi a hiányt és újraindítja, a
HELYES munkamenetben. A dashboard rövid ideig VÁRAKOZVA ELLENŐRZI is, hogy ez tényleg megtörtént-e,
és ezt jelenti a felhasználónak -- nem csendben feltételezi.

Futtatás (fejlesztéshez): python -m regime_framework.monitoring.terminal_watchdog

Önálló .exe csomagolás -- UGYANAZ a minta, mint dashboard_web.py, DE `--windowed`, hogy NE
nyisson látható konzolablakot az RDP-asztalon (csak a logfájlba ír):

    pyinstaller --onefile --windowed --name RegimeFramework_TerminalWatchdog \\
      --paths "D:\\XM\\optuna_research" \\
      --distpath dist --workpath build --specpath build \\
      regime_framework/monitoring/terminal_watchdog.py

Eredmény: `dist/RegimeFramework_TerminalWatchdog.exe` -- a `heartbeat_dashboard.py`-hoz/
`dashboard_web.py`-hoz hasonlóan a mellé tett `terminals.json`-t olvassa (ugyanaz a fájl,
mindhárom .exe-hez). Helyezd az Indítópult mappába (vagy egy onnan hívott .cmd-be), hogy minden
RDP-bejelentkezéskor automatikusan elinduljon.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

WATCHDOG_INTERVAL_S = 10

if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(_BASE_DIR, "terminal_watchdog.log")
TERMINALS_CONFIG_PATH = os.path.join(_BASE_DIR, "terminals.json")


def load_terminals_config():
    """Szándékosan SAJÁT, minimális `terminals.json`-olvasó -- NEM `heartbeat_dashboard.
    load_terminals_config()` importálva, mert az az egész `heartbeat_dashboard` modult (és azon
    keresztül a teljes `MetaTrader5`/numpy importláncot) behúzná, pedig ennek a wachdognak
    egyáltalán nincs szüksége az MT5 Python API-ra -- csak a `terminals.json` `name`/`path`
    mezőire. (2026-09-13: az első build emiatt `ImportError: numpy._core.multiarray failed to
    import`-tal állt le indításkor -- lásd SESSION_LOG.md.) Csak azokat a bejegyzéseket adja
    vissza, amiknek van `path`-ja -- a `path=None` ("alapértelmezett terminál") esetet nem tudjuk
    figyelni/újraindítani, mert nincs konkrét .exe, amit ellenőrizhetnénk."""
    if not os.path.isfile(TERMINALS_CONFIG_PATH):
        return []
    try:
        # utf-8-sig: a BOM-mal mentett fájlt is elfogadja (2026-10-16: egy BOM-os terminals.json
        # miatt a watchdog csendben "nincs mit figyelni" állapotba került); BOM nélkül változatlan.
        with open(TERMINALS_CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        _log(f"⚠️ terminals.json beolvasása sikertelen ({exc}) -- nincs mit figyelni.")
        return []
    # 2026-10-16: opcionális `args` (pl. ["/portable"]) -- a portable módban futó terminált
    # csak ugyanazzal a kapcsolóval szabad újraindítani, különben a %APPDATA% alatti, MÁSIK
    # adatmappával (EA-k és profil nélkül) indulna. Ha nincs megadva, a viselkedés változatlan.
    return [
        {"name": t.get("name", t.get("path", "?")), "path": t.get("path"),
         "args": [str(a) for a in t.get("args", [])]}
        for t in data.get("terminals", []) if t.get("path")
    ]


def _log(message):
    # SZÁNDÉKOSAN csak AKCIÓKOR/hibakor írunk sort, NEM minden egyes ellenőrző ciklusban --
    # egy 10 mp-enkénti "minden rendben" sor néhány nap alatt használhatatlanul nagy logfájlt
    # adna, elfedve a valóban érdekes eseményeket.
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    # A `print()` A KONZOL kódlapjától (pl. cp1250) függ, ami nem minden karaktert (pl. emoji)
    # tud kódolni -- 2026-09-13-i teszt: egy UnicodeEncodeError ITT elszállt VÉDELEM NÉLKÜL, ami
    # a `main()` ciklus hiba-ágán belül ledöntötte az EGÉSZ watchdogot, pont a legfontosabb
    # pillanatban (egy hiba naplózásakor). A logFÁJL (utf-8, mindig ez az elsődleges, megbízható
    # csatorna) NEM omolhat össze emiatt -- ezért a konzol-kiírás soha nem terjedhet tovább.
    try:
        print(line)
    except Exception:
        pass
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _is_running(path):
    # `creationflags=CREATE_NO_WINDOW` -- 2026-09-13, felhasznaloi jelzes: enelkul a `wmic.exe`
    # (egy konzolos program) minden 10 mp-es ellenorzo ciklusban felvillantott egy sajat konzol-
    # ablakot a kepernyon, mert a HIVO (ez a watchdog) `--windowed` modban fut, sajat konzol
    # nelkul -- ilyenkor Windows UJ, lathato konzolt nyit a gyermeknek. Ez a flag ezt teljesen
    # elnyomja, a wmic HANGTALANUL, lathatatlanul fut le, ahogy egy hatterfolyamat-ellenorzesnek
    # kell.
    escaped_path = path.replace("\\", "\\\\")
    result = subprocess.run(
        ["wmic", "process", "where", f"ExecutablePath='{escaped_path}'", "get", "ProcessId"],
        capture_output=True, text=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return any(line.strip().isdigit() for line in result.stdout.splitlines())


def _start(terminal):
    # `subprocess.Popen` -- NEM `wmic`/szolgáltatás-hívás -- ez a SAJÁT (interaktív) munkamenetünkből
    # indítja a gyermeket, lásd a modul fejléc-kommentjét arról, miért kritikus ez.
    subprocess.Popen([terminal["path"], *terminal["args"]], cwd=os.path.dirname(terminal["path"]))
    _log(f"Elindítva (hiányzott): {terminal['name']} ({terminal['path']} {' '.join(terminal['args'])})")


def main():
    _log("RegimeFramework terminál-watchdog elindult.")
    terminals = load_terminals_config()
    if not terminals:
        _log("Nincs 'path'-tal rendelkező terminál a terminals.json-ban -- nincs mit figyelni.")
        return
    for t in terminals:
        _log(f"Figyelt terminál: {t['name']} -> {t['path']} {' '.join(t['args'])}".rstrip())

    while True:
        for terminal in terminals:
            try:
                if not _is_running(terminal["path"]):
                    _start(terminal)
            except Exception as exc:
                _log(f"⚠️ Hiba a(z) {terminal['name']} ellenőrzésekor/indításakor: {exc}")
        time.sleep(WATCHDOG_INTERVAL_S)


if __name__ == "__main__":
    main()
