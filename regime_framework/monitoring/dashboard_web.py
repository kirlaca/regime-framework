"""
monitoring/dashboard_web.py — a heartbeat_dashboard.py (Tkinter GUI) egyszerű webes megfelelője,
2026-09-07: felhasználói kérés, hogy a monitoring VPS-ről is elérhető legyen távoli asztal NÉLKÜL.

Nem Flask/Django -- szándékosan a Python beépített `http.server`-ét használja, hogy az .exe-csomagolás
ugyanolyan egyszerű maradjon, mint a Tkinter-verzióé (nincs új függőség). A biztonságot NEM az
alkalmazás adja (nincs jelszó/token) -- a felhasználó döntése szerint elég védelem, ha a VPS tűzfala
(Windows Firewall + a felhő-szolgáltató security group-ja) csak egyetlen ismert IP-ről engedi be a
portot, UGYANÚGY, ahogy az RDP is jelenleg csak egy IP-ről elérhető. NE tedd ezt a portot szélesebb
körben elérhetővé auth hozzáadása nélkül.

A `heartbeat_dashboard.py`-t (Tkinter GUI, VPS-en már bevált, éles monitoring) ez a script
SZÁNDÉKOSAN NEM módosítja/refaktorálja -- a heartbeat-parse/status logikát (`heartbeat_watchdog`)
és a tiszta (Tk-független) segédfüggvényeket/konstansokat (`heartbeat_dashboard` modul importja,
Tk-osztály PÉLDÁNYOSÍTÁSA NÉLKÜL, tehát nem nyit ablakot) újrahasznosítja, de az MT5-lekérdező
logikát (terminál-kapcsolat-kezelés, trade-történet/összesítés/komponens-bontás számítás) saját,
Tk-mentes függvényekként írja újra, mert az eredetiben ezek a `HeartbeatDashboard` osztály
metódusai, `self`-hez (és a Treeview-widgetekhez) kötve.

Egy háttérszál (`refresh_loop`) periodikusan frissíti a megosztott `STATE` dict-et (ugyanazokkal az
időközökkel, mint a Tkinter-verzió), a HTTP-kérések csak ebből a gyorsítótárból szolgálnak ki --
egy oldalletöltés SOSEM vár MT5-lekérdezésre.

Futtatás (fejlesztéshez): python -m regime_framework.monitoring.dashboard_web [--port 8765] [--host 0.0.0.0]

Önálló .exe csomagolás (ugyanaz a minta, mint heartbeat_dashboard.py -- lásd annak fejléc-
kommentjét a `--paths`/`--collect-all`/`--add-data` kapcsolók indoklásáért). KONZOL-alkalmazás,
NEM `--windowed` -- a szerver élőben a konzolon logol (kérések, hibák), és Ctrl+C-vel állítható le:

    pyinstaller --onefile --name RegimeFramework_DashboardWeb --paths "D:\\XM\\optuna_research" \\
      --collect-all numpy --collect-all MetaTrader5 \\
      --add-data "regime_framework/monitoring/webapp;regime_framework/monitoring/webapp" \\
      --distpath dist --workpath build --specpath build \\
      regime_framework/monitoring/dashboard_web.py

Az `--add-data` a PWA-fájlokat (`monitoring/webapp/manifest.json`, `icon.svg` -- lásd WEBAPP_DIR)
csomagolja be -- ezek statikus alkalmazás-eszközök, fájlrendszer-útvonalként hivatkozunk rájuk
(nem Python-importként), így a PyInstaller statikus elemzése önmagától nem találná meg őket.

**2026-09-11 óta a `market_holidays.json` és `live_baselines.json` NINCS becsomagolva** (lásd
`core/market_calendar.py` / `data/live_baselines_loader.py` fejléc-kommentjét) -- ezek az .exe
MELLÉ teendő, önállóan cserélhető fájlok, hogy egy évváltás (naptár) vagy negyedéves
újraoptimalizálás (baseline) NE igényeljen újrafordítást, csak egy `scp`-t. A `refresh_loop`
legfeljebb egy ciklusidőn belül (≤`COMPONENTS_REFRESH_S`) felveszi a cserélt fájlt, .exe-újraindítás
sem kell.

Eredmény: `dist/RegimeFramework_DashboardWeb.exe` -- a `heartbeat_dashboard.py`-hoz hasonlóan a
mellé tett `terminals.json`-t (mindkét .exe-hez ugyanaz a fájl), `market_holidays.json`-t és
`live_baselines.json`-t olvassa (lásd fent).
"""

import argparse
import calendar
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import MetaTrader5 as mt5

from regime_framework.monitoring.heartbeat_watchdog import (
    HEARTBEAT_PATTERN,
    check_heartbeat,
    parse_heartbeat,
)
from regime_framework.monitoring.heartbeat_dashboard import (
    CALENDAR_WARNING_DAYS_AHEAD,
    COMPONENT_COLORS,
    COMPONENT_LABELS,
    COMPONENT_ORDER,
    COMPONENTS_LOOKBACK_DAYS,
    HISTORY_LOOKBACK_DAYS,
    MAX_TRADES_SHOWN,
    PERIOD_LABELS,
    REGIME_LABELS,
    SUMMARY_LOOKBACK_DAYS,
    _lerp_color,
    humanize_age,
    load_terminals_config,
    period_start_times,
)
from regime_framework.core.market_calendar import is_market_holiday, load_calendar
from regime_framework.data.live_baselines_loader import load_live_baselines
from regime_framework.monitoring.baseline_drift import classify_component_drift

# A mobil/PWA-eszkozok (manifest.json, ikon) kulon mappaban elnek, hogy a "telepitheto app-kent
# viselkedjen" funkcio a fo dashboard-kodtol fuggetlenul karbantarthato/csereheto legyen -- lasd
# monitoring/webapp/.
#
# FONTOS, amit egy build-teszt derített ki (2026-09-08): a `core/market_calendar.py`-ban bevalt
# `Path(__file__).resolve().parent...` mintazat ITT NEM mukodik -- az a mintazat egy RENDES,
# importalt almodulra igaz, aminek a frozen `__file__`-je helyesen tukrozi a csomag-relativ utat
# (<MEIPASS>/regime_framework/core/market_calendar.py). A `dashboard_web.py` viszont maga a
# BELEPESI PONT script (ezt adjuk at a pyinstaller-nek), es EZ frozen allapotban NEM a csomagon
# beluli utvonalra kapja a `__file__`-jet -- emiatt a webapp-mappa 404-et adott, pedig a fajlok
# PONTOSAN ott voltak a kicsomagolt `_MEI...`-mappaban, ahol vartuk (ellenorizve kozvetlen
# fajlrendszer-vizsgalattal futas kozben). Ezert itt kulon kell kezelni a frozen esetet.
if getattr(sys, "frozen", False):
    WEBAPP_DIR = Path(sys._MEIPASS) / "regime_framework" / "monitoring" / "webapp"
else:
    WEBAPP_DIR = Path(__file__).resolve().parent / "webapp"

# `live_instances.json` -- lásd `load_live_instances_config()` -- az .exe MELLETT keresendő
# (`terminals.json` mintájára, lásd `heartbeat_dashboard._BASE_DIR`), NEM a `WEBAPP_DIR`-hez
# hasonlóan a PyInstaller-csomagon BELÜL -- ez egy kézzel karbantartott, telepítésenként eltérő
# config, nem statikus alkalmazás-eszköz.
if getattr(sys, "frozen", False):
    _CONFIG_BASE_DIR = os.path.dirname(sys.executable)
else:
    _CONFIG_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_INSTANCES_CONFIG_PATH = os.path.join(_CONFIG_BASE_DIR, "live_instances.json")

DEFAULT_PORT = 8765
HEARTBEAT_REFRESH_S = 10
HISTORY_REFRESH_S = 30
SUMMARY_REFRESH_S = 60
COMPONENTS_REFRESH_S = 90
PAGE_AUTOREFRESH_S = 15   # a böngésző ennyi másodpercenként tölti újra az oldalt

# 2026-09-11, felhasznaloi jelzes: egy 23:00-kor (szerveridő) zart trade csak kb. 2 orat kesobb
# jelent meg a listaban. Oka: a `history_deals_get()` felso hatarakent hasznalt `datetime.now()`
# a GEP SAJAT (helyi) orajat adta at, de az MT5 a hatarokat ugyanugy "szerveridő-mint-UTC"
# kodolasban ertelmezi, mint a `d.time` mezot (lasd `_refresh_trades()` fenti megjegyzese a
# 2026-09-09-i hasonlo hibarol). Mivel a szerveridő jelenleg orakkal ELORE jar a VPS helyi
# idejehez kepest (amerikai nyari idoszamitas), egy mar lezajlott, de "jovobeli digit-erteku"
# trade kimaradt a lekerdezesi ablakbol, amig a helyi ora szamjegyei utol nem ertek. Mivel jovobeli
# trade soha nem letezhet, biztonsagos a felso hatart mindig elore tolni -- ez semmilyen hamis
# adatot nem hozhat be, csak biztositja, hogy az ablak felso hatara mindig a valodi szerveridő
# felett legyen, fuggetlenul az aktualis DST-eltolastol.
HISTORY_TO_MARGIN = timedelta(hours=6)


def _history_to_bound():
    return datetime.now() + HISTORY_TO_MARGIN


# Rövid (nem a teljes COMPONENT_LABELS-féle leíró) címkék a "Legutóbbi zárt trade-ek" táblázat
# Komponens oszlopához (2026-09-12, felhasználói kérés) -- egy táblázat-sorba a teljes név
# ("MeanReversion" stb.) túl széles lenne, a rövid MQL5-kód (OWNER_TAG_* utótagja) tömörebb.
COMPONENT_SHORT_LABELS = {"RF_MR": "MR", "RF_TF": "TF", "RF_LHC": "LHC", "RF_FS": "FS"}

# Signal Copier kártya (2026-09-25, felhasználói kérés: az árnyék (SHADOW) futás a dashboardon is
# látszódjon). Csak FÁJL-alapú (Common\Files), nem kell hozzá MT5-hívás:
#   - a publisher pillanatképe:  RF_signal_<MASTER>_<magic>.txt  (1 mp-enként frissül)
#   - a slave heartbeatje: SHADOW-ban RF_SignalSlave_shadow_<SYM>_<magic>.txt; LIVE-ban az éles néven
#     (RegimeFramework_heartbeat_<SYM>_<magic>.txt, benne mode=slave)
#   - a slave eseménynaplója:    RF_SignalSlave_<SYM>_<magic>.csv  (OPEN/SL_MODIFY/CLOSE_*/...)
# A "Ma" összevetés valódi oldala a `_refresh_trades()` teljes (nem a 40-es kijelzési limittel
# csonkolt) lekérdezéséből számolt napi összesítő (`STATE["closed_by_day"]`).
SIGNAL_FILE_PATTERN = "RF_signal_*.txt"
SLAVE_SHADOW_HB_PATTERN = "RF_SignalSlave_shadow_*.txt"
SLAVE_CSV_TEMPLATE = "RF_SignalSlave_{symbol}_{magic}.csv"
SIGNAL_MAX_AGE_S = 120          # ugyanaz a küszöb, mint a vps_check v3-ban
SLAVE_HB_MAX_AGE_S = 30 * 60    # ugyanaz, mint az éles heartbeatnél (MAX_STALE_SECONDS)
SLAVE_EVENTS_SHOWN = 10


# Heartbeat archiválás + reset (2026-09-13, felhasznaloi keres): a "piac nyitva?" ellenorzes a
# meglevo hatterszaltol (refresh_loop) FUGGETLEN kerésre (do_POST) hivja meg az MT5 API-t --
# a kodbazis eddigi, kommentekben is rogzitett szabalya ("MT5-hivas KIZAROLAG a hattérszalban
# tortenik") ezert egy KOZOS lockkal bovul: mind a `refresh_loop` MT5-erinto hivasai, mind az uj
# vegpont MT5-hasznalata ugyanazt az `MT5_LOCK`-ot fogja, igy a `mt5` modul EGYETLEN, folyamat-
# szintu kapcsolat-allapota sosem szalversenyezik terminal-valtaskor.
MT5_LOCK = threading.Lock()

STATE_LOCK = threading.Lock()
STATE = {
    "updated_at": "-",
    "terminals": [],
    "terminals_names": [],
    "common_files_dirs": [],
    "heartbeats": [],
    "trades": [],
    "trades_summary": "",
    "trades_refreshed_epoch": 0.0,
    "summary_cards": {label: (None, None) for label in PERIOD_LABELS},
    "summary_detail": [],
    "summary_note": "",
    "regime_rows": [],
    "calendar_warnings": [],
    "component_stats": {},
    "components_note": "",
    "baseline_stats_by_instance": {},
    "baselines": {"instances": {}},
    "admin_calendar_status": {"status": "hiba", "text": "Még nincs adat."},
    "admin_baseline_rows": [],
    "closed_by_day": {},     # (symbol, magic, "YYYY-MM-DD" szerveridő) -> (darab, nettó $)
    "signal_copier": [],
    "mt5_link_issues": {},   # terminál-név -> üzenet (lásd Mt5Connector.connect)
}

# Adminisztráció fül (2026-09-11, felhasznaloi keres): mikortol szamit "esedekesnek" egy
# negyedeves ujraoptimalizalas -- a negyedev kb. 91 nap, egy kis ráhagyással (~2 hét) jelezzuk
# elore ("figyelem"), mielott tenylegesen "lejar".
BASELINE_WARN_DAYS = 80
BASELINE_OVERDUE_DAYS = 100

_YEAR_KEY_RE = re.compile(r"_(\d{4})$")


# ------------------------------------------------------------------ MT5 lekérdezés (Tk-mentes)

TERMINAL_STARTUP_GRACE_S = 120      # ennél fiatalabb látható terminálhoz még NEM csatlakozunk (IPC-verseny)
MT5_INIT_TIMEOUT_MS = 15000         # a beragadt initialize ne tartsa az MT5_LOCK-ot a 60 mp-es alapértékig


def _terminal_processes(path):
    """[(pid, session_id, age_s)] -- a `path` futtatható fájlú futó folyamatok, munkamenet-azonosítóval
    és korral (mp). A 0-s munkamenet (Session 0) a láthatatlan szolgáltatás-munkamenet: egy ott futó
    terminál GUI nélküli, rejtett példány (lásd `Mt5Connector.connect()`). None, ha a lekérdezés nem
    sikerült (pl. a wmic nem érhető el) -- a hívó ekkor NEM csatlakozik."""
    escaped_path = path.replace("\\", "\\\\")
    try:
        result = subprocess.run(
            ["wmic", "process", "where", f"ExecutablePath='{escaped_path}'", "get",
             "CreationDate,ProcessId,SessionId", "/format:csv"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    procs = []
    now = datetime.now()
    for line in result.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
            try:
                age = (now - datetime.strptime(parts[1][:14], "%Y%m%d%H%M%S")).total_seconds()
            except ValueError:
                age = 0.0   # ismeretlen kor -> "friss"-nek tekintjük (óvatos: várakozás)
            procs.append((parts[2], int(parts[3]), age))
    return procs


def _set_link_issue(terminal_name, message):
    # mindig ÚJ dict (nem helyben módosítás) -- a renderelő szál a régi példányon iterálhat
    with STATE_LOCK:
        issues = {k: v for k, v in STATE["mt5_link_issues"].items() if k != terminal_name}
        if message:
            issues[terminal_name] = message
        STATE["mt5_link_issues"] = issues


def _kill_pids(pids):
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, text=True, timeout=15,
                       creationflags=subprocess.CREATE_NO_WINDOW)


class Mt5Connector:
    """Ugyanaz a mintázat, mint `HeartbeatDashboard._connect()` -- explicit shutdown+initialize
    terminálváltáskor, mert a Python MT5 API egyszerre csak EGY kapcsolatot tart nyitva.

    **2026-09-29, ÉLESBEN talált hiba (production/LIVE_STATE.json open_issues)**: az
    `mt5.initialize(path=...)` ELINDÍT egy terminált, ha nem tud a futóhoz csatlakozni -- és mivel
    a dashboard a 0-s munkamenetben fut, az így indított terminál LÁTHATATLAN (lásd
    `_restart_terminal()` fejléc: Session 0 izoláció). 2026-09-26 19:55-kor az IC-terminál MT5-
    frissítés utáni újraindulása alatt a dashboard így indított egy rejtett példányt, amely elfoglalta
    a terminál API-csatornáját ("IPC dispatcher not started" a látható példány naplójában), és onnantól
    a dashboard mindig a rejtett példányt használta / indította újra. Ezért:
      (1) initialize CSAK akkor, ha a terminál már fut egy látható (nem 0-s) munkamenetben;
      (2) ha az initialize mégis ÚJ folyamatot hozott létre, azt azonnal leállítjuk, és jelezzük,
          hogy a futó terminál nem fogad API-kapcsolatot (zárt piacon, RDP-ről újraindítandó);
      (3) egy rejtett (0-s munkamenetbeli) példány létét figyelmeztetésként jelezzük (nem állítjuk le
          automatikusan -- nem biztos, hogy a dashboard indította);
      (4) INDULÁSI TÜRELMI IDŐ (A-kritika J1): a 09-26-os hiba VERSENY volt -- a látható terminál
          folyamata már futott, az IPC-je még nem. Ha a legfiatalabb látható példány
          < TERMINAL_STARTUP_GRACE_S, vagy a látható PID-halmaz az előző hívás óta változott, ebben a
          ciklusban NEM hívunk initialize-t (várakozás);
      (5) CSAK a 0-s munkamenetbeli új PID-et állítjuk le (J2) -- egy közben RDP-ről indított, látható
          terminált soha;
      (6) explicit, rövid initialize-timeout (J3); ha a folyamat-lekérdezés sikertelen, nem
          csatlakozunk (J4)."""

    def __init__(self):
        self._connected_path = "__unset__"
        self._last_visible = {}   # path -> a legutóbb látott látható PID-halmaz
        # path -> (látható PID-halmaz, üzenet): a terminál NEM fogad API-kapcsolatot -- amíg a látható
        # PID-halmaz nem változik (azaz a terminált nem indítják újra), NEM próbálkozunk újra, különben
        # minden ciklusban egy rejtett példány indulna és állna le (2026-09-29, élesben megelőzve)
        self._no_ipc = {}

    def connect(self, terminal):
        path = terminal["path"]
        name = terminal["name"]
        if not path:
            _set_link_issue(name, "nincs 'path' a terminals.json-ban -- a dashboard nem csatlakozik "
                                  "(path nélkül az API maga keresne/indítana terminált).")
            return False
        procs = _terminal_processes(path)
        if procs is None:
            self._connected_path = "__unset__"
            _set_link_issue(name, "a terminál-folyamatok nem kérdezhetők le (wmic) -- biztonsági okból "
                                  "nem csatlakozunk.")
            return False
        visible = {pid for pid, sess, _ in procs if sess != 0}
        hidden = [pid for pid, sess, _ in procs if sess == 0]
        hidden_note = (f" Rejtett (session 0) példány fut: PID {', '.join(hidden)} -- nem kellene "
                       "futnia; zárt piacon leállítandó.") if hidden else ""
        previous_visible = self._last_visible.get(path)
        self._last_visible[path] = visible
        if not visible:
            self._connected_path = "__unset__"
            _set_link_issue(name, "a terminál nem fut látható munkamenetben -- a dashboard nem "
                                  "csatlakozik és nem indít terminált." + hidden_note)
            return False
        youngest = min(age for _, sess, age in procs if sess != 0)
        if youngest < TERMINAL_STARTUP_GRACE_S or (previous_visible is not None and previous_visible != visible):
            self._connected_path = "__unset__"
            _set_link_issue(name, f"a terminál most indult / újraindult ({youngest:.0f} mp) -- várakozás, "
                                  "amíg az API-csatornája elkészül." + hidden_note)
            return False
        if self._connected_path == path:
            _set_link_issue(name, hidden_note.strip())
            return True
        no_ipc = self._no_ipc.get(path)
        if no_ipc is not None:
            if no_ipc[0] == visible:
                _set_link_issue(name, no_ipc[1] + hidden_note)
                return False
            del self._no_ipc[path]
        try:
            mt5.shutdown()
        except Exception:
            pass
        before = {pid for pid, _, _ in procs}
        ok = mt5.initialize(path=path, timeout=MT5_INIT_TIMEOUT_MS)
        after = _terminal_processes(path) or []
        spawned = [pid for pid, sess, _ in after if pid not in before and sess == 0]
        if spawned:
            try:
                mt5.shutdown()
            except Exception:
                pass
            _kill_pids(spawned)
            self._connected_path = "__unset__"
            msg = (f"a futó terminál (PID {', '.join(sorted(visible))}) NEM fogad API-kapcsolatot; "
                   f"az MT5 API saját rejtett példányt indított (PID {', '.join(spawned)}), ezt leállítottuk. "
                   "Teendő: a terminál újraindítása zárt piacon, RDP-ről (addig nem próbálkozunk újra).")
            self._no_ipc[path] = (visible, msg)
            _set_link_issue(name, msg + hidden_note)
            return False
        self._connected_path = path if ok else "__unset__"
        _set_link_issue(name, hidden_note.strip() if ok else
                        f"mt5.initialize sikertelen: {mt5.last_error()}" + hidden_note)
        return ok


# EGYETLEN, folyamatszintű connector (2026-09-29): a `mt5` modul kapcsolata is folyamatszintű --
# két külön Mt5Connector-példány (háttérszál + archiválás-végpont) egymás tudta nélkül váltotta a
# kapcsolatot, és a háttérszál utána rossz terminálból olvashatott. Mindig MT5_LOCK alatt használandó.
CONNECTOR = Mt5Connector()


def _known_magics(common_files_dirs):
    magics = set()
    for d in common_files_dirs:
        for path in glob.glob(os.path.join(d, HEARTBEAT_PATTERN)):
            fields = parse_heartbeat(path)
            magic = fields.get("magic")
            if magic and magic.isdigit():
                magics.add(int(magic))
    return magics


# --- Tavoli le/fel-kapcsolo (2026-09-09) -- lasd a live EA-k g_controlFileName fejlec-kommentjet
# ugyanerrol a mechanizmusrol: egy fajl LETEZESE tiltja az UJ belepeseket, a fajl NEVE szimmetrikus
# a heartbeat-fajlevel, csak "_control_" "_heartbeat_" helyett -- UGYANABBAN a konyvtarban, mert az
# EA is ugyanoda (FILE_COMMON) ir/olvas.
CONTROL_FILE_TEMPLATE = "RegimeFramework_control_{symbol}_{magic}.txt"


def _control_file_path(directory, symbol, magic):
    return os.path.join(directory, CONTROL_FILE_TEMPLATE.format(symbol=symbol, magic=magic))


def _find_instance_dir(common_files_dirs, symbol, magic):
    """Megkeresi, MELYIK common_files_dir-ben van az adott szimbolum+magic heartbeat-fajlja --
    csak akkor irunk/torlunk vezerlo-fajlt, ha ez egy VALODI, jelenleg ismert peldany (lasd
    Handler.do_POST) -- ez vedi ki, hogy a vegpont tetszoleges fajlnevre visszaelheto legyen."""
    heartbeat_name = f"RegimeFramework_heartbeat_{symbol}_{magic}.txt"
    for d in common_files_dirs:
        if os.path.isfile(os.path.join(d, heartbeat_name)):
            return d
    return None


def load_live_instances_config():
    """`live_instances.json`-t olvas be -- lásd `live_instances.example.json` a formátumért.
    Kézzel karbantartott lista az ÖSSZES élő EA-példányról (symbol+magic, terminálhoz kötve) --
    ez dönti el a "Heartbeat archiválás" funkciónál, mely heartbeat-fájl SZÁMÍT élőnek (a rajta
    kívül eső fájlok "árvának" minősülnek, archiválás után törölhetők), ÉS mely symbolokat kell
    piac-nyitva szempontból ellenőrizni egy terminál újraindítása előtt.

    Ha a fájl hiányzik/hibás, ÜRES listát ad vissza -- ez SZÁNDÉKOS: egy hiányzó/sérült regiszter
    esetén az árva-törlés/reset funkció NE találjon egyetlen "ismert" példányt sem (a hívó ezt
    biztonsági okból elutasításként kezeli, lásd `Handler.do_POST`), mert egy üres regiszter
    melletti "minden árva, minden törölhető" végkimenetel messze veszélyesebb tévedés lenne, mint
    egy elutasított művelet."""
    if os.path.isfile(LIVE_INSTANCES_CONFIG_PATH):
        try:
            with open(LIVE_INSTANCES_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [
                {"terminal": i["terminal"], "symbol": i["symbol"], "magic": int(i["magic"])}
                for i in data.get("instances", [])
            ]
        except (json.JSONDecodeError, OSError, KeyError, ValueError) as exc:
            print(f"⚠️ live_instances.json beolvasása sikertelen ({exc}) -- üres regiszterre esik vissza.")
    return []


def _is_symbol_active(symbol, samples=5, interval_s=3.0):
    """Igaz, ha `symbol`-on ÉRKEZIK élő quote a hívás alatt (kb. `samples*interval_s` másodperces
    valós idejű megfigyeléssel) -- ez a "piac nyitva" jel. Hamis, ha nem érkezik új tick. None, ha
    a symbol nem kérdezhető le (pl. elgépelt/nem ismert symbol) -- a hívó ezt "nem tudjuk
    eldönteni"-ként kezelje, NE "zárva"-ként.

    SZÁNDÉKOSAN NEM a tick időbélyegét (`tick.time`) hasonlítja a gép saját órájához: lásd
    `_refresh_trades()` fejléc-kommentjét -- az MT5 timestampek a BRÓKER SZERVER saját (nem
    feltétlenül a helyi géppel egyező) óráját kódolják, egy abszolút küszöb ezért DST/időzóna-
    eltolás miatt órákkal tévedhetne. Ehelyett KÉT (vagy több) mintát veszünk egy általunk
    kontrollált, valós idejű ablakban, és azt nézzük, változott-e a tick -- ez teljesen független
    a szerver-vs-helyi óraeltolástól. Likvid index CFD-n (USTEC/US30/stb.) nyitott piacon
    másodpercenként több tick is jön -- ha eközben `samples*interval_s` (alapból ~12 mp) alatt
    EGYETLEN új tick sem érkezik, az megbízhatóan piac-zárásra utal.

    `mt5.symbol_select(symbol, True)` -- gyakori MT5 Python API buktató: `symbol_info_tick()`
    None-t ad vissza, ha a symbol NINCS a Market Watch-ban kiválasztva, MÉG AKKOR IS, ha egyébként
    létezik és kereskedik rajta egy EA (a chart megnyitása általában kiválasztja, de erre nem
    szabad blindul támaszkodni egy biztonsági ellenőrzésben) -- ez a hívás ártalmatlanul
    hozzáadja, ha még nem lenne ott."""
    mt5.symbol_select(symbol, True)
    last = None
    for i in range(samples):
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        current = (tick.time, getattr(tick, "time_msc", 0))
        if last is not None and current != last:
            return True
        last = current
        if i < samples - 1:
            time.sleep(interval_s)
    return False


HEARTBEAT_ARCHIVE_DIR_NAME = "heartbeat_archive"


WATCHDOG_RELAUNCH_TIMEOUT_S = 20
WATCHDOG_RELAUNCH_POLL_S = 2


def _find_pids_by_path(path):
    # `creationflags=CREATE_NO_WINDOW`: ha ezt a kódot valaha interaktív munkamenetből futtatnánk
    # (pl. `run_debug.bat`), a `wmic.exe` konzolablaka ne villanjon fel a képernyőn -- lásd
    # `terminal_watchdog.py._is_running()` ugyanerről, ott élesben ez okozott zavaró villogást.
    escaped_path = path.replace("\\", "\\\\")
    result = subprocess.run(
        ["wmic", "process", "where", f"ExecutablePath='{escaped_path}'", "get", "ProcessId"],
        capture_output=True, text=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]


def _restart_terminal(terminal):
    """CSAK LEÁLLÍTJA a `terminal["path"]`-hoz tartozó `terminal64.exe` folyamat(oka)t -- az
    ÚJRAINDÍTÁST SZÁNDÉKOSAN NEM ez a függvény végzi.

    **2026-09-13, ÉLESBEN felfedezett hiba (lásd SESSION_LOG.md)**: ez a függvény korábban
    `wmic process call create`-tel maga próbálta újraindítani a terminált -- ez a Windows
    "Session 0 izolációja" miatt egy LÁTHATATLAN munkamenetbe indította az MT5-öt (a dashboard
    saját maga is Session 0-ban fut, mert SSH-n át hívott `wmic`-kel lett elindítva -- egy
    Session-0-beli szülő GYERMEKE, BÁRMELY API-val hozva létre, szintén oda kerül). A felhasználó
    RDP-képernyőjén emiatt semmi nem jelent meg, pedig a folyamat technikailag elindult.

    A tényleges újraindítást ezért a felhasználó INTERAKTÍV RDP-munkamenetéből induló
    `terminal_watchdog.py` végzi (lásd annak fejléc-kommentjét) -- ez a függvény csak leállít,
    majd rövid ideig VÁRAKOZVA ELLENŐRZI, hogy a watchdog tényleg visszahozta-e a terminált, és
    ezt az EREDMÉNYT (nem csak feltételezést) adja vissza, hogy a felhasználó AZONNAL lássa, ha a
    watchdog netán nem fut."""
    path = terminal.get("path")
    if not path:
        raise RuntimeError(
            f"'{terminal['name']}' terminálnak nincs beállítva 'path'-ja a terminals.json-ban -- "
            "nem tudjuk biztonságosan azonosítani, melyik folyamatot állítsuk le."
        )
    old_pids = _find_pids_by_path(path)
    for pid in old_pids:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, text=True, timeout=15,
                        creationflags=subprocess.CREATE_NO_WINDOW)

    waited = 0.0
    while waited < WATCHDOG_RELAUNCH_TIMEOUT_S:
        time.sleep(WATCHDOG_RELAUNCH_POLL_S)
        waited += WATCHDOG_RELAUNCH_POLL_S
        new_pids = _find_pids_by_path(path)
        if new_pids:
            return {"stopped_pids": old_pids, "relaunched": True, "new_pids": new_pids,
                    "waited_s": waited}
    return {"stopped_pids": old_pids, "relaunched": False, "new_pids": [], "waited_s": waited}


def _archive_and_reset_terminal(terminal, instances):
    """Lásd PLAN.md a teljes indoklásért. Csak akkor hívható, ha a hívó MÁR megerősítette, hogy a
    terminál MINDEN, `live_instances.json`-ban rá regisztrált instrumentumának piaca zárva -- ez a
    függvény saját maga NEM ellenőriz piaci állapotot.

    Lépések: (1) a terminál `common_files_dir`-jéből minden heartbeat+control fájl átmásolása egy
    időbélyeges archív-mappába (mtime megőrizve, `shutil.copy2`), (2) az archivált fájlok
    TARTALMA (nem a fájlnév -- a symbol tartalmazhat speciális karaktereket, pl. `US100Cash#`)
    alapján árva-ellenőrzés a `live_instances.json` TELJES (nem csak erre a terminálra szűkített)
    regiszteréhez képest, árvák törlése az EREDETI (élő) mappából, (3) a terminál-folyamat
    kényszerített leállítása (lásd `_restart_terminal`).

    **2026-09-13, ÉLESBEN felfedezett hiba**: a `known` regiszter korábban csak ERRE a terminálra
    volt szűkítve (`i["terminal"] == terminal["name"]`) -- ez hibás, mert a `terminals.json`
    két bejegyzése (IC Markets/XM) alapértelmezetten UGYANAZT a megosztott `Common\\Files`
    mappát használja (egyik sincs "portable" módban, külön mappával), tehát egy adott terminál
    `common_files_dir`-je a MÁSIK terminál élő heartbeat-fájljait is tartalmazhatja. A terminál-
    szűkített `known` emiatt tévesen ÁRVÁNAK, majd TÖRLÉSRE ítélt egy élő XM-heartbeatet, amikor
    az "IC Markets" gombot nyomtuk meg. A `known` ezért MOST globális -- egy fájl csak akkor
    árva, ha SEMMILYEN terminálhoz nincs regisztrálva, nem csak ehhez az egyhez."""
    common_dir = terminal["common_files_dir"]
    known = {(i["symbol"], i["magic"]) for i in instances}

    heartbeat_paths = sorted(glob.glob(os.path.join(common_dir, HEARTBEAT_PATTERN)))
    if not heartbeat_paths:
        return {"archived": 0, "orphans_deleted": 0, "archive_dir": None,
                "restart": _restart_terminal(terminal)}

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_terminal_name = re.sub(r"[^A-Za-z0-9_-]+", "_", terminal["name"])
    archive_dir = os.path.join(_CONFIG_BASE_DIR, HEARTBEAT_ARCHIVE_DIR_NAME,
                                f"{safe_terminal_name}_{stamp}")
    os.makedirs(archive_dir, exist_ok=False)

    manifest_lines = [f"Terminál: {terminal['name']}", f"Időbélyeg: {stamp}",
                       f"Forrás: {common_dir}", ""]
    archived = 0
    orphans_deleted = 0
    for hb_path in heartbeat_paths:
        fields = parse_heartbeat(hb_path)
        symbol = fields.get("symbol", "")
        magic_raw = fields.get("magic", "")
        magic = int(magic_raw) if magic_raw.isdigit() else None

        related_paths = [hb_path]
        if symbol and magic is not None:
            control_path = _control_file_path(common_dir, symbol, magic)
            if os.path.isfile(control_path):
                related_paths.append(control_path)

        for path in related_paths:
            shutil.copy2(path, os.path.join(archive_dir, os.path.basename(path)))
        archived += len(related_paths)

        is_orphan = magic is None or (symbol, magic) not in known
        manifest_lines.append(
            f"{os.path.basename(hb_path)} -- symbol={symbol!r} magic={magic_raw!r}"
            + ("  -> ÁRVA, törölve archiválás után" if is_orphan else "")
        )
        if is_orphan:
            for path in related_paths:
                os.remove(path)
            orphans_deleted += 1

    with open(os.path.join(archive_dir, "MANIFEST.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(manifest_lines) + "\n")

    restart_info = _restart_terminal(terminal)
    return {"archived": archived, "orphans_deleted": orphans_deleted, "archive_dir": archive_dir,
            "restart": restart_info}


def _component_stats_by_instance(connector, terminals, magics, date_from):
    """Lásd `HeartbeatDashboard._component_stats()` fejléc-kommentjét a párosítási logika
    indoklásáért (nyitó deal comment, position_id-vel párosítva) -- itt szó szerint ugyanaz.

    A `stats` kulcsa `(terminal["name"], magic, tag)`, NEM csak `tag` -- 2. fázis (lásd PLAN.md
    7. pont): a `terminal["name"]` (`"IC Markets"`/`"XM"`) KELL a megkülönböztetéshez, mert két
    élő példány (XM US100Cash# és IC Markets USTEC) UGYANAZT a magic number-t (202609) használja
    -- tisztán magic alapján a trade-jeik összefolynának. Lásd `_pool_component_stats_by_tag()`
    a visszafelé kompatibilis, tag-only aggregátumhoz (a meglévő portfólió-szintű kártyához)."""
    stats = {}
    unreachable = []
    for terminal in terminals:
        if not connector.connect(terminal):
            unreachable.append(terminal["name"])
            continue
        deals = mt5.history_deals_get(date_from, _history_to_bound()) or ()
        entry_tag_by_position = {
            d.position_id: (d.comment or "?") for d in deals
            if d.magic in magics and d.entry == mt5.DEAL_ENTRY_IN
        }
        for d in deals:
            if d.magic not in magics or d.entry != mt5.DEAL_ENTRY_OUT:
                continue
            tag = entry_tag_by_position.get(d.position_id, d.comment or "?")
            net = d.profit + d.swap + d.commission
            key = (terminal["name"], d.magic, tag)
            s = stats.setdefault(key, {"count": 0, "wins": 0, "gross_profit": 0.0,
                                        "gross_loss": 0.0, "net": 0.0})
            s["count"] += 1
            s["net"] += net
            if net > 0:
                s["wins"] += 1
                s["gross_profit"] += net
            elif net < 0:
                s["gross_loss"] += -net
    return stats, unreachable


def _pool_component_stats_by_tag(stats_by_instance):
    """A finomabb szemcsés `(terminal, magic, tag) -> stats`-ból visszaállítja a régi,
    portfólió-szintű `tag -> stats` nézetet (a meglévő "Komponensek szerinti bontás" kártyához,
    aminek a kimenete a 2. fázis refaktor után is VÁLTOZATLAN kell maradjon)."""
    pooled = {}
    for (_terminal, _magic, tag), s in stats_by_instance.items():
        p = pooled.setdefault(tag, {"count": 0, "wins": 0, "gross_profit": 0.0,
                                     "gross_loss": 0.0, "net": 0.0})
        p["count"] += s["count"]
        p["wins"] += s["wins"]
        p["gross_profit"] += s["gross_profit"]
        p["gross_loss"] += s["gross_loss"]
        p["net"] += s["net"]
    return pooled


# ------------------------------------------------------------------ háttérszál: STATE frissítése

def _refresh_heartbeats(common_files_dirs):
    paths = sorted(set(
        p for d in common_files_dirs for p in glob.glob(os.path.join(d, HEARTBEAT_PATTERN))
    ))
    rows = []
    for path in paths:
        result = check_heartbeat(path)
        f = result["fields"]
        status = result["status"]
        tag = "HIBA" if "HIBA" in status else ("STALE" if status.startswith("STALE") else "OK")
        symbol = f.get("symbol", "")
        magic = f.get("magic", "")
        control_disabled = False
        if symbol and magic.isdigit():
            control_disabled = os.path.exists(_control_file_path(os.path.dirname(path), symbol, magic))
        rows.append({
            "file": result["file"], "status": status, "tag": tag,
            "age": humanize_age(result["age_seconds"]),
            "ready": f.get("classifier_ready", "?"), "positions": f.get("open_positions", "?"),
            "errors": result["error_count"], "last_error": f.get("last_error_msg", "") or "-",
            "equity": f.get("account_equity", "?"), "margin_free": f.get("account_margin_free", "?"),
            "symbol": symbol, "magic": magic, "control_disabled": control_disabled,
        })
    with STATE_LOCK:
        STATE["heartbeats"] = rows


def _refresh_trades(connector, terminals, common_files_dirs):
    magics = _known_magics(common_files_dirs)
    if not magics:
        with STATE_LOCK:
            STATE["trades"] = []
            STATE["trades_summary"] = "Nincs ismert magic number (heartbeat-fájl) -- nincs mit szűrni."
        return

    date_from = datetime.now() - timedelta(days=HISTORY_LOOKBACK_DAYS)
    date_to = _history_to_bound()
    all_rows = []
    unreachable = []
    for terminal in terminals:
        if not connector.connect(terminal):
            unreachable.append(terminal["name"])
            continue
        deals = mt5.history_deals_get(date_from, date_to) or ()
        # A ZÁRÓ deal COMMENT-je nem mindig a miénk (a bróker felülírhatja, pl. "[sl]"/"[tp]") --
        # a NYITÓ (DEAL_ENTRY_IN) deal komment-jét (OWNER_TAG_*) kell position_id alapján
        # visszakeresni, ugyanaz a minta, mint a `_component_stats_by_instance()`-ben (2026-09-12,
        # felhasználói kérés: komponens-oszlop a "Legutóbbi zárt trade-ek" táblázatban).
        entry_tag_by_position = {
            d.position_id: (d.comment or "?") for d in deals
            if d.magic in magics and d.entry == mt5.DEAL_ENTRY_IN
        }
        for d in deals:
            if d.entry == mt5.DEAL_ENTRY_OUT and d.magic in magics:
                component_tag = entry_tag_by_position.get(d.position_id, d.comment or "?")
                all_rows.append((terminal["name"], component_tag, d))

    all_rows.sort(key=lambda row: row[2].time, reverse=True)
    shown = all_rows[:MAX_TRADES_SHOWN]

    # Napi összesítő a Signal Copier kártyához -- a TELJES (nem csonkolt) listából, szerveridős
    # dátummal (lásd lent a `d.time` szerveridő-epoch megjegyzést).
    closed_by_day = {}
    for _, _, d in all_rows:
        key = (d.symbol, d.magic, datetime.utcfromtimestamp(d.time).strftime("%Y-%m-%d"))
        count, net = closed_by_day.get(key, (0, 0.0))
        closed_by_day[key] = (count + 1, net + d.profit + d.swap + d.commission)

    total_profit = 0.0
    trade_rows = []
    for terminal_name, component_tag, d in shown:
        profit = d.profit + d.swap + d.commission
        total_profit += profit
        tag = "pos" if profit > 0 else ("neg" if profit < 0 else "zero")
        # JAVÍTÁS (2026-09-14, felhasznaloi eszlelet -- LastHourContinuation, ami a forráskód
        # szerint KIZÁRÓLAG LONG-ot köt, a monitorban mégis mindig SHORT-ként jelent meg): a `d`
        # itt a ZÁRÓ (DEAL_ENTRY_OUT) deal -- egy LONG pozíció zárása mindig egy SELL-lel
        # történik (eladod, amit vettél), egy SHORT záró pedig BUY-jal. Az irány tehát a záró
        # deal TÍPUSÁVAL ELLENTÉTES, nem azzal megegyező -- a korábbi verzió pont fordítva volt.
        direction = "LONG" if d.type == mt5.DEAL_TYPE_SELL else "SHORT"
        trade_rows.append({
            "terminal": terminal_name,
            "component": COMPONENT_SHORT_LABELS.get(component_tag, component_tag),
            # KRITIKUS (2026-09-09, felhasznaloi jelzes: a dashboard 2 oraval elt a napi bróker-
            # emailtol): a `d.time` MT5-epoch NEM valodi UTC -- a szerver SAJAT oraallasat kodolja,
            # "UTC-nek almcazva" (dokumentalt MT5 API sajatossag). `datetime.fromtimestamp()` ezt
            # MEG EGYSZER eltolta volna a gep sajat idozonajaval (dupla eltolas) -- helyette
            # `utcfromtimestamp()`-et hasznalunk, ami a nyers ertéket VÁLTOZATLANUL szerveridokent
            # adja vissza, pontosan úgy, ahogy a broker e-mail/az MT5 Journal is mutatja.
            "time": datetime.utcfromtimestamp(d.time).strftime("%Y-%m-%d %H:%M"),
            "symbol": d.symbol, "magic": d.magic, "direction": direction,
            "volume": f"{d.volume:.2f}", "price": f"{d.price:.2f}",
            "profit": f"{profit:+.2f}", "tag": tag,
        })

    summary = (f"{len(all_rows)} zárt trade az elmúlt {HISTORY_LOOKBACK_DAYS} napban "
               f"(max {MAX_TRADES_SHOWN} kiírva) · össz. nettó: {total_profit:+.2f}")
    if unreachable:
        summary += f" · ⚠️ nem elérhető: {', '.join(unreachable)}"
    with STATE_LOCK:
        STATE["trades"] = trade_rows
        STATE["trades_summary"] = summary
        STATE["trades_refreshed_epoch"] = time.time()
        STATE["closed_by_day"] = closed_by_day


def _parse_slave_csv(path):
    """A slave eseménynaplója (`;`-vel tagolt, ANSI). Hiányzó/olvashatatlan fájl -> üres lista.
    A fejléc-oszlopszámtól eltérő (pl. éppen íródó) sorokat kihagyjuk."""
    try:
        with open(path, "rb") as f:
            lines = f.read().decode("cp1252", errors="replace").splitlines()
    except OSError:
        return []
    if not lines:
        return []
    header = lines[0].split(";")
    return [dict(zip(header, parts)) for parts in (ln.split(";") for ln in lines[1:]) if len(parts) == len(header)]


def _server_day(server_time_text):
    """"2026.09.25 11:20:13" (MQL5 TimeToString) -> "2026-09-25"."""
    return (server_time_text or "")[:10].replace(".", "-")


def _float_or_zero(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _summarize_slave_events(events, today):
    """SHADOW-események összesítése: a nyitott virtuális pozíció, a mai és az összes virtuális zárás,
    a mai nyitások jel-kora. A LIVE-módú események valódi kötések -- azok a `closed_by_day`-ben
    (bróker-történet) szerepelnek, itt nem számoljuk őket duplán."""
    open_pos = None
    today_count, today_net, total_count, total_net = 0, 0.0, 0, 0.0
    open_ages_today = []
    for ev in events:
        if ev.get("mode") != "SHADOW":
            continue
        name, ticket = ev.get("event", ""), ev.get("master_ticket", "")
        if name == "OPEN":
            open_pos = {"ticket": ticket, "dir": ev.get("dir", ""), "tag": ev.get("tag", ""),
                        "price": ev.get("price", ""), "sl": ev.get("sl", ""), "tp": ev.get("tp", ""),
                        "since": ev.get("server_time", "")}
            if _server_day(ev.get("server_time")) == today:
                open_ages_today.append(int(_float_or_zero(ev.get("signal_age_ms"))))
        elif name in ("SL_MODIFY", "TP_MODIFY") and open_pos and open_pos["ticket"] == ticket:
            open_pos["sl"], open_pos["tp"] = ev.get("sl", open_pos["sl"]), ev.get("tp", open_pos["tp"])
        elif name.startswith("CLOSE_"):
            net = _float_or_zero(ev.get("pnl_money"))
            total_count, total_net = total_count + 1, total_net + net
            if _server_day(ev.get("server_time")) == today:
                today_count, today_net = today_count + 1, today_net + net
            if open_pos and open_pos["ticket"] == ticket:
                open_pos = None
        elif name == "DEINIT":
            open_pos = None   # az EA leállásakor a virtuális pozíció elveszett
    return {"open_pos": open_pos, "today": (today_count, today_net), "total": (total_count, total_net),
            "open_ages_today": open_ages_today}


def _refresh_signal_copier(common_files_dirs):
    now = time.time()
    # slave-heartbeatek: SHADOW-ban saját néven, LIVE-ban az éles néven (mode=slave) -- (dir, symbol,
    # magic) szerint a LEGFRISSEBBET vesszük, így egy SHADOW->LIVE átállás után sem látszik kétszer
    slaves = {}
    for d in common_files_dirs:
        candidates = glob.glob(os.path.join(d, SLAVE_SHADOW_HB_PATTERN))
        candidates += [p for p in glob.glob(os.path.join(d, HEARTBEAT_PATTERN))
                       if parse_heartbeat(p).get("mode") == "slave"]
        for path in candidates:
            fields = parse_heartbeat(path)
            key = (d, fields.get("symbol", "?"), fields.get("magic", "?"))
            mtime = os.path.getmtime(path)
            if key not in slaves or mtime > slaves[key][0]:
                slaves[key] = (mtime, path, fields)

    with STATE_LOCK:
        closed_by_day = dict(STATE.get("closed_by_day", {}))

    entries = []
    for (d, symbol, magic), (mtime, path, f) in sorted(slaves.items()):
        today = _server_day(f.get("server_time")) or datetime.now().strftime("%Y-%m-%d")
        signal_name = f.get("signal_file", "")
        signal_path = os.path.join(d, signal_name) if signal_name else ""
        # a publisher 1 mp-enként atomikusan cseréli a fájlt -- egy épp a csere pillanatában
        # olvashatatlan fájl ne szakítsa meg a teljes frissítési kört, csak ez az érték maradjon ki
        try:
            signal = parse_heartbeat(signal_path) if signal_path and os.path.isfile(signal_path) else {}
            signal_age = (now - os.path.getmtime(signal_path)) if signal else None
        except OSError:
            signal, signal_age = {}, None
        csv_path = os.path.join(d, f.get("csv_log") or SLAVE_CSV_TEMPLATE.format(symbol=symbol, magic=magic))
        events = _parse_slave_csv(csv_path)
        summary = _summarize_slave_events(events, today)

        def real(sym, mag):
            try:
                return closed_by_day.get((sym, int(mag), today), (0, 0.0))
            except (TypeError, ValueError):
                return (0, 0.0)

        entries.append({
            "symbol": symbol, "magic": magic, "today": today,
            "mode_config": f.get("exec_mode_config", "?"), "mode_effective": f.get("exec_mode_effective", "?"),
            "block_reason": f.get("block_reason", ""), "errors": f.get("trade_error_count", "0"),
            "last_error": f.get("last_error_msg", "") or "-",
            "hb_age_s": now - mtime, "signal_file": signal_name, "signal_age_s": signal_age,
            "master_symbol": signal.get("master_symbol", "?"), "master_magic": signal.get("master_magic", "?"),
            "master_regime": signal.get("master_regime", "?"), "master_vol": signal.get("master_vol_band", "?"),
            "master_has_pos": signal.get("has_position") == "1", "master_ticket": signal.get("ticket", ""),
            "master_dir": {"1": "BUY", "-1": "SELL"}.get(signal.get("direction", ""), ""),
            "master_tag": signal.get("tag", ""),
            "summary": summary,
            "real_master_today": real(signal.get("master_symbol"), signal.get("master_magic")),
            "real_slave_today": real(symbol, magic),
            "events": list(reversed(events[-SLAVE_EVENTS_SHOWN:])),
        })
    with STATE_LOCK:
        STATE["signal_copier"] = entries


def _refresh_summary(connector, terminals, common_files_dirs):
    magics = _known_magics(common_files_dirs)
    now = datetime.now()
    starts = period_start_times(now)

    if not magics:
        with STATE_LOCK:
            STATE["summary_cards"] = {label: (None, None) for label in PERIOD_LABELS}
            STATE["summary_detail"] = []
            STATE["summary_note"] = "Nincs ismert magic number (heartbeat-fájl) -- nincs mit összesíteni."
        return

    date_from = now - timedelta(days=SUMMARY_LOOKBACK_DAYS)
    per_terminal = []
    unreachable = []
    for terminal in terminals:
        if not connector.connect(terminal):
            unreachable.append(terminal["name"])
            continue
        info = mt5.account_info()
        balance = info.balance if info else None
        deals = mt5.history_deals_get(date_from, _history_to_bound()) or ()
        closing = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT and d.magic in magics]
        nominal_by_period = {}
        for label, start in starts.items():
            # Lasd a `_refresh_trades` fenti megjegyzeset a `d.time` szerveridő-epoch
            # sajatossagarol -- `start.timestamp()` (valodi UTC-kre konvertal, a GEP sajat
            # idozonajabol kiindulva) rossz hatart adna `d.time`-hoz kepest, es pl. egy 23:00-kor
            # (szerveridő) zart trade-et a KOVETKEZO napra sorolt volna (ezt eszlelte a
            # felhasznalo). `calendar.timegm()` a `start` naptári/óra-mezőit UGYANOLYAN "naiv"
            # modon epoch-ha alakitja, mint ahogy a `d.time` mar eleve kodolva van -- igy mindket
            # oldal ugyanabban a (szerveridő-) vonatkoztatasi rendszerben van.
            start_ts = calendar.timegm(start.timetuple())
            nominal_by_period[label] = sum(
                d.profit + d.swap + d.commission for d in closing if d.time >= start_ts
            )
        per_terminal.append((terminal["name"], balance, nominal_by_period))

    total_balance = sum(b for _, b, _ in per_terminal if b is not None) or None
    cards = {}
    for label in PERIOD_LABELS:
        combined_nominal = sum(n[label] for _, _, n in per_terminal)
        combined_percent = (combined_nominal / total_balance * 100) if total_balance else None
        cards[label] = (combined_nominal, combined_percent)

    detail_rows = []
    for name, balance, nominal_by_period in per_terminal:
        row = {"terminal": name, "balance": f"{balance:,.2f}" if balance is not None else "n/a",
               "periods": []}
        for label in PERIOD_LABELS:
            nominal = nominal_by_period[label]
            pct = (nominal / balance * 100) if balance else None
            row["periods"].append((f"{nominal:+.2f}", f"{pct:+.2f}%" if pct is not None else "n/a"))
        today_nominal = nominal_by_period["Ma"]
        row["tag"] = "pos" if today_nominal > 0 else ("neg" if today_nominal < 0 else "zero")
        detail_rows.append(row)

    note = (f"A %-ok a jelenlegi teljes egyenleghez viszonyítva ({SUMMARY_LOOKBACK_DAYS} napos "
            f"lekérdezési ablak, hétfői hét-kezdéssel).")
    if unreachable:
        note += f" ⚠️ nem elérhető: {', '.join(unreachable)}"
    with STATE_LOCK:
        STATE["summary_cards"] = cards
        STATE["summary_detail"] = detail_rows
        STATE["summary_note"] = note


def _calendar_covered_years(calendar_data):
    """A `market_holidays.json` `closed_YYYY`/`early_close_YYYY` kulcsaiból gyűjti ki, mely
    évekre van egyáltalán naptáradat -- ebből deríthető ki, hogy közeleg-e az évváltás."""
    years = set()
    for market_info in calendar_data.get("markets", {}).values():
        for key in market_info:
            m = _YEAR_KEY_RE.search(key)
            if m:
                years.add(int(m.group(1)))
    return years


def _check_calendar_year_status(calendar_data, today):
    years = _calendar_covered_years(calendar_data)
    if not years:
        return {"status": "hiba", "text": "A naptárban nincs egyetlen év-specifikus bejegyzés sem."}
    max_year = max(years)
    if today.year > max_year:
        return {
            "status": "hiba",
            "text": (f"A naptár NEM fedi a {today.year}-es évet (utolsó rögzített: {max_year}) -- "
                     f"az ünnepnap-védelem gyakorlatilag KI van kapcsolva minden szimbólumra! "
                     f"Frissítsd a `market_holidays.json`-t."),
        }
    if today.year == max_year and today.month >= 11:
        return {
            "status": "figyelem",
            "text": (f"Közeleg az évváltás -- a naptár egyelőre csak {max_year}-ig van felvéve, "
                     f"a {max_year + 1}-es adatok még hiányoznak."),
        }
    return {"status": "ok", "text": f"A naptár lefedi a {max_year}-es évet, nincs teendő."}


def _check_baseline_ages(baselines, now_utc):
    """Minden `live_baselines.json`-beli példány `generated_at`-jából számolt kor (nap), a
    negyedéves újraoptimalizálás esedékességének jelzésére -- lásd
    quarterly-baseline-refresh-checklist memória. A baseline-generálás időpontját használjuk az
    "utolsó optimalizálás" közelítéseként, mert ez az egyetlen strukturált időbélyeg, amit a
    rutin ténylegesen rögzít."""
    rows = []
    for key, inst in sorted(baselines.get("instances", {}).items()):
        generated_at = inst.get("generated_at")
        age_days = None
        status = "hiba"
        try:
            gen_dt = datetime.fromisoformat(generated_at)
            if gen_dt.tzinfo is None:
                gen_dt = gen_dt.replace(tzinfo=timezone.utc)
            age_days = (now_utc - gen_dt).days
            if age_days >= BASELINE_OVERDUE_DAYS:
                status = "lejart"
            elif age_days >= BASELINE_WARN_DAYS:
                status = "figyelem"
            else:
                status = "ok"
        except (TypeError, ValueError):
            pass
        rows.append({
            "instance": key, "generated_at": (generated_at or "?")[:10],
            "age_days": age_days, "status": status,
        })
    rows.sort(key=lambda r: (r["age_days"] is None, -(r["age_days"] or 0)))
    return rows


def _refresh_components(connector, terminals, common_files_dirs):
    # --- rezsim heartbeat-fájlokból ---
    paths = sorted(set(
        p for d in common_files_dirs for p in glob.glob(os.path.join(d, HEARTBEAT_PATTERN))
    ))
    regime_rows = []
    symbols_seen = set()
    for path in paths:
        fields = parse_heartbeat(path)
        symbol = fields.get("symbol", "?")
        symbols_seen.add(symbol)
        regime = fields.get("current_regime", "?")
        regime_rows.append({
            "file": os.path.basename(path), "symbol": symbol,
            "regime": REGIME_LABELS.get(regime, regime),
            "vol": fields.get("current_vol_band", "?"),
            "ready": fields.get("classifier_ready", "?"),
        })

    # --- naptár-figyelmeztetés ---
    warnings = []
    try:
        calendar = load_calendar()
        today = datetime.now().date()
        for offset in range(0, CALENDAR_WARNING_DAYS_AHEAD + 1):
            check_date = today + timedelta(days=offset)
            for symbol in sorted(symbols_seen):
                if symbol == "?":
                    continue
                if is_market_holiday(symbol, check_date, calendar):
                    when = "MA" if offset == 0 else f"{offset} nap múlva ({check_date.isoformat()})"
                    warnings.append(f"{symbol}: piaci ünnepnap {when}")
        admin_calendar_status = _check_calendar_year_status(calendar, today)
    except Exception as exc:
        warnings = [f"Naptár beolvasási hiba: {exc}"]
        admin_calendar_status = {"status": "hiba", "text": f"Naptár beolvasási hiba: {exc}"}

    # --- komponens-bontás ---
    magics = _known_magics(common_files_dirs)
    if magics:
        date_from = datetime.now() - timedelta(days=COMPONENTS_LOOKBACK_DAYS)
        stats_by_instance, unreachable = _component_stats_by_instance(
            connector, terminals, magics, date_from
        )
        stats = _pool_component_stats_by_tag(stats_by_instance)
        total = sum(s["count"] for s in stats.values())
        note = f"{total} zárt trade összesen (kb. {COMPONENTS_LOOKBACK_DAYS // 365} éves ablak)"
        if unreachable:
            note += f" · ⚠️ nem elérhető: {', '.join(unreachable)}"
    else:
        stats_by_instance, stats, note = {}, {}, "Nincs ismert magic number -- nincs mit összesíteni."

    # --- élő vs. validált-alap drift (2. fázis, PLAN.md 7. pont) ---
    try:
        baselines = load_live_baselines()
    except (OSError, ValueError) as exc:
        baselines = {"instances": {}}
        print(f"⚠️ live_baselines.json beolvasása sikertelen: {exc}")

    admin_baseline_rows = _check_baseline_ages(baselines, datetime.now(timezone.utc))

    with STATE_LOCK:
        STATE["regime_rows"] = regime_rows
        STATE["calendar_warnings"] = warnings
        STATE["component_stats"] = stats
        STATE["components_note"] = note
        STATE["baseline_stats_by_instance"] = stats_by_instance
        STATE["baselines"] = baselines
        STATE["admin_calendar_status"] = admin_calendar_status
        STATE["admin_baseline_rows"] = admin_baseline_rows


def refresh_loop(terminals, common_files_dirs):
    connector = CONNECTOR
    with STATE_LOCK:
        STATE["terminals"] = terminals
        STATE["terminals_names"] = [t["name"] for t in terminals]
        STATE["common_files_dirs"] = common_files_dirs

    last = {"hb": 0.0, "trades": 0.0, "summary": 0.0, "components": 0.0}
    while True:
        now = time.monotonic()
        try:
            if now - last["hb"] >= HEARTBEAT_REFRESH_S:
                _refresh_heartbeats(common_files_dirs)
                _refresh_signal_copier(common_files_dirs)
                last["hb"] = now
            if now - last["trades"] >= HISTORY_REFRESH_S:
                with MT5_LOCK:
                    _refresh_trades(connector, terminals, common_files_dirs)
                last["trades"] = now
            if now - last["summary"] >= SUMMARY_REFRESH_S:
                with MT5_LOCK:
                    _refresh_summary(connector, terminals, common_files_dirs)
                last["summary"] = now
            if now - last["components"] >= COMPONENTS_REFRESH_S:
                with MT5_LOCK:
                    _refresh_components(connector, terminals, common_files_dirs)
                last["components"] = now
        except Exception as exc:   # egy átmeneti MT5-hiba ne állítsa le a háttérszálat véglegesen
            print(f"⚠️ refresh_loop hiba: {exc}")
        with STATE_LOCK:
            STATE["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        time.sleep(2)


# ------------------------------------------------------------------ HTML renderelés

def _e(value):
    return html.escape(str(value))


def _pill(tag, text):
    return f"<span class='pill pill-{tag.lower()}'>{_e(text)}</span>"


def _render_heartbeat_archive_buttons(terminals):
    if not terminals:
        return "<p class='empty'>Nincs betöltött terminál.</p>"
    buttons = "".join(
        f"<button class='archive-btn' data-terminal='{_e(t['name'])}'>"
        f"{_e(t['name'])} — archiválás + reset</button>"
        for t in terminals
    )
    return f"<div class='archive-buttons'>{buttons}</div>"


def _render_control_cell(r):
    if not (r["symbol"] and r["magic"]):
        return "<span class='muted'>?</span>"
    symbol_attr = _e(r["symbol"])
    if r["control_disabled"]:
        pill = _pill("hiba", "Leállítva")
        action, cls, label = "start", "start", "Indítás"
    else:
        pill = _pill("ok", "Fut")
        action, cls, label = "stop", "stop", "Leállítás"
    button = (
        f"<button class='ctl-btn {cls}' data-symbol='{symbol_attr}' data-magic='{_e(r['magic'])}' "
        f"data-action='{action}'>{label}</button>"
    )
    return f"{pill} {button}"


def _render_heartbeats(rows):
    if not rows:
        return "<p class='empty'>Nincs heartbeat-fájl -- fut-e az EA valamelyik charton?</p>"
    body = "".join(
        f"<tr><td class='mono'>{_e(r['file'])}</td><td>{_pill(r['tag'], r['status'])}</td>"
        f"<td>{_e(r['age'])}</td><td>{_e(r['ready'])}</td><td>{_e(r['positions'])}</td>"
        f"<td>{_e(r['errors'])}</td><td class='muted-cell'>{_e(r['last_error'])}</td>"
        f"<td>{_e(r['equity'])}</td><td>{_e(r['margin_free'])}</td>"
        f"<td class='ctl-cell'>{_render_control_cell(r)}</td></tr>"
        for r in rows
    )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Fájl (szimbólum_magic)</th><th>Állapot</th>"
        "<th>Utolsó heartbeat kora</th><th>Rezsim kész</th><th>Nyitott poz.</th>"
        "<th>Hibák</th><th>Utolsó hiba</th><th>Equity</th><th>Szabad margin</th>"
        "<th>Vezérlés</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _render_trades(rows):
    if not rows:
        return "<p class='empty'>Nincs megjeleníthető trade.</p>"
    body = "".join(
        f"<tr><td>{_e(r['terminal'])}</td><td class='mono'>{_e(r['component'])}</td>"
        f"<td>{_e(r['time'])}</td>"
        f"<td class='mono'>{_e(r['symbol'])}</td><td>{_e(r['magic'])}</td>"
        f"<td>{_pill('info' if r['direction'] == 'LONG' else 'neutral', r['direction'])}</td>"
        f"<td>{_e(r['volume'])}</td><td>{_e(r['price'])}</td>"
        f"<td class='num {r['tag']}'>{_e(r['profit'])}</td></tr>"
        for r in rows
    )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Terminál</th><th>Komponens</th>"
        "<th>Zárás ideje</th><th>Szimbólum</th>"
        "<th>Magic</th><th>Irány</th><th>Volumen</th><th>Ár</th><th>Profit ($)</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _render_refresh_meta(refreshed_epoch, interval_s):
    """Fix magasságú, egysoros "köv. frissítés" jelző + elfogyó csík (2026-09-11, felhasznaloi
    jelzes: a korabbi valtozo hosszusagu szoveg mobilon 1 es 2 sor kozott valtott a szerver-render
    (placeholder "...") es az azt kovetoen lefuto JS-tick kozott, ami a lenti trade-tablat egy
    pillanatra "felcsusztatta". A DOM-alak (label span + csik-track + csik-toltes) MINDIG ugyanaz,
    szerver-oldalon is mar a valos allapottal renderelve -- a JS csak a szoveget/szelesseget
    frissiti masodpercenkent, sosem a szerkezetet, igy nincs magassag-ugras."""
    elapsed = max(0.0, time.time() - refreshed_epoch) if refreshed_epoch else 0.0
    remaining = max(0, round(interval_s - elapsed))
    pct = max(0, min(100, round((remaining / interval_s) * 100))) if interval_s else 0
    return (
        f"<div class='refresh-meta' id='tradesRefreshMeta' "
        f"data-epoch='{refreshed_epoch:.0f}' data-interval='{interval_s}'>"
        f"<span class='refresh-meta-label'>Frissítés: <span class='refresh-meta-secs'>{remaining}</span>mp</span>"
        f"<span class='refresh-bar-track'><span class='refresh-bar-fill' style='width:{pct}%'></span></span>"
        f"</div>"
    )


def _render_summary_cards(cards):
    parts = []
    for label in PERIOD_LABELS:
        nominal, percent = cards.get(label, (None, None))
        if nominal is None:
            parts.append(
                f"<div class='stat-card'><div class='stat-label'>{_e(label)}</div>"
                f"<div class='stat-value muted'>–</div><div class='stat-sub muted'>nincs adat</div></div>"
            )
            continue
        tag = "pos" if nominal > 0 else ("neg" if nominal < 0 else "zero")
        arrow = "▲" if nominal > 0 else ("▼" if nominal < 0 else "•")
        pct_text = f"{percent:+.2f}%" if percent is not None else "n/a"
        parts.append(
            f"<div class='stat-card {tag}'><div class='stat-label'>{_e(label)}</div>"
            f"<div class='stat-value'>{nominal:+,.2f} $</div>"
            f"<div class='stat-sub'><span class='arrow'>{arrow}</span> {_e(pct_text)}</div></div>"
        )
    return "<div class='stat-grid'>" + "".join(parts) + "</div>"


def _render_summary_detail(rows):
    if not rows:
        return "<p class='empty'>Nincs terminálonkénti adat.</p>"
    header_cells = "".join(f"<th>{_e(p)} ($)</th><th>{_e(p)} (%)</th>" for p in PERIOD_LABELS)
    body = ""
    for row in rows:
        period_cells = "".join(f"<td class='num'>{_e(nom)}</td><td class='num'>{_e(pct)}</td>"
                                for nom, pct in row["periods"])
        body += (f"<tr><td>{_e(row['terminal'])}</td>"
                 f"<td>{_e(row['balance'])}</td>{period_cells}</tr>")
    return (
        f"<div class='table-wrap'><table><thead><tr><th>Terminál</th><th>Egyenleg</th>{header_cells}</tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _render_regime_rows(rows):
    if not rows:
        return "<p class='empty'>Nincs adat.</p>"
    body = "".join(
        f"<tr><td class='mono'>{_e(r['file'])}</td><td>{_e(r['symbol'])}</td><td>{_e(r['regime'])}</td>"
        f"<td>{_e(r['vol'])}</td><td>{_e(r['ready'])}</td></tr>"
        for r in rows
    )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Fájl (szimbólum_magic)</th><th>Szimbólum</th>"
        "<th>Aktuális rezsim</th><th>Volatilitás</th><th>Rezsim-osztályozó kész</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _render_component_cards(stats):
    total_count = sum(s["count"] for s in stats.values()) or 0
    parts = []
    for tag in COMPONENT_ORDER:
        s = stats.get(tag, {"count": 0, "wins": 0, "gross_profit": 0.0, "gross_loss": 0.0, "net": 0.0})
        share = (s["count"] / total_count) if total_count else 0.0
        pale, rich = COMPONENT_COLORS[tag]
        accent = _lerp_color(pale, rich, max(share, 0.15))
        label = COMPONENT_LABELS.get(tag, tag)
        if s["count"] == 0:
            body = "<div class='empty' style='margin-top:10px'>nincs adat</div>"
        else:
            win_rate = s["wins"] / s["count"] * 100
            pf = (s["gross_profit"] / s["gross_loss"]) if s["gross_loss"] > 0 else float("inf")
            pf_text = f"{pf:.2f}" if pf != float("inf") else "∞"
            net_class = "pos" if s["net"] > 0 else ("neg" if s["net"] < 0 else "zero")
            body = (
                f"<div class='share-bar'><div class='share-fill' style='width:{share * 100:.0f}%;"
                f"background:{accent}'></div></div>"
                f"<div class='component-meta'>{s['count']} trade &nbsp;·&nbsp; {share * 100:.0f}% részesedés</div>"
                f"<div class='component-meta'>Találat: {win_rate:.0f}% &nbsp; PF: {pf_text}</div>"
                f"<div class='component-net {net_class}'>{s['net']:+,.2f} $</div>"
            )
        parts.append(
            f"<div class='puzzle-card' style='--accent:{accent}'>"
            f"<div class='puzzle-title'>{_e(label)}</div>{body}</div>"
        )
    return "<div class='puzzle-row'>" + "".join(parts) + "</div>"


# Drift-pill státusz -> meglévő .pill-* CSS-osztály (lásd `_pill()`), semmi új vizuális nyelv.
_DRIFT_PILL_TAG = {"ok": "ok", "caution": "stale", "drift": "hiba", "pending": "neutral"}
_DRIFT_PILL_LABEL = {"ok": "OK", "caution": "Figyelendő", "drift": "Eltérés", "pending": "Várakozik"}


def _render_baseline_drift_cards(stats_by_instance, baselines):
    """2. fázis (lásd PLAN.md 7. pont): a `live_baselines.json["instances"]`-en iterál (NEM a
    live `stats_by_instance`-en), hogy egy még 0 élő trade-es példány is megjelenjen "várakozik"
    jelzéssel, ne csak csendben hiányozzon a kártyasorból."""
    instances = baselines.get("instances", {})
    if not instances:
        return "<p class='empty'>Nincs betöltött baseline (live_baselines.json).</p>"

    parts = []
    for instance in instances.values():
        broker, symbol, magic = instance["broker"], instance["symbol"], instance["magic"]
        rows = []
        for tag in COMPONENT_ORDER:
            baseline_component = instance["components"].get(tag)
            if baseline_component is None:
                continue
            live_stats = stats_by_instance.get((broker, magic, tag), {
                "count": 0, "wins": 0, "gross_profit": 0.0, "gross_loss": 0.0, "net": 0.0,
            })
            result = classify_component_drift(tag, live_stats, baseline_component)
            pill = _pill(_DRIFT_PILL_TAG[result["status"]], _DRIFT_PILL_LABEL[result["status"]])
            rows.append(
                f"<div class='component-meta'>{_e(COMPONENT_LABELS.get(tag, tag))} {pill}</div>"
                f"<div class='component-meta muted-cell'>{_e(result['detail'])}</div>"
            )
        parts.append(
            "<div class='puzzle-card'>"
            f"<div class='puzzle-title'>{_e(broker)} · {_e(symbol)} (magic {_e(magic)})</div>"
            + "".join(rows) + "</div>"
        )
    return "<div class='puzzle-row'>" + "".join(parts) + "</div>"


def _net_line(label, count_net):
    count, net = count_net
    cls = "pos" if net > 0 else ("neg" if net < 0 else "zero")
    return (f"<div class='component-meta'>{_e(label)}: {count} kötés &nbsp;"
            f"<span class='num {cls}'>{net:+,.2f} $</span></div>")


def _render_signal_copier(entries):
    """Signal Copier kártyasor (lásd SIGNAL_FILE_PATTERN fölötti komment). Ha nincs slave, a blokk
    ki sem rajzolódik -- a dashboard a copier nélkül ugyanúgy néz ki, mint eddig."""
    if not entries:
        return ("<div class='block'><h2>Signal Copier — master → slave</h2>"
                "<p class='empty'>Nincs futó slave (nincs RF_SignalSlave heartbeat a Common\\Files mappában).</p></div>")
    blocks = []
    for x in entries:
        eff, cfg = x["mode_effective"], x["mode_config"]
        mode_pill = _pill("info", "ÁRNYÉK (csak naplóz)") if eff == "SHADOW" else (
            _pill("ok", "ÉLES") if eff == "LIVE" else _pill("hiba", eff))
        forced = (cfg == "LIVE" and eff == "SHADOW")
        hb_pill = _pill("ok", humanize_age(x["hb_age_s"])) if x["hb_age_s"] <= SLAVE_HB_MAX_AGE_S \
            else _pill("stale", humanize_age(x["hb_age_s"]))
        slave_card = (
            "<div class='puzzle-card'>"
            f"<div class='puzzle-title'>Slave · {_e(x['symbol'])} (magic {_e(x['magic'])})</div>"
            f"<div class='component-meta'>{mode_pill}</div>"
            f"<div class='component-meta'>Beállított: {_e(cfg)}"
            + (" &nbsp;" + _pill("stale", "kényszerített árnyék") if forced else "") + "</div>"
            f"<div class='component-meta muted-cell'>{_e(x['block_reason'] or '-')}</div>"
            f"<div class='component-meta'>Heartbeat: {hb_pill}</div>"
            f"<div class='component-meta'>Hibák: {_e(x['errors'])} · {_e(x['last_error'])}</div>"
            "</div>"
        )
        age = x["signal_age_s"]
        sig_pill = _pill("hiba", "NINCS JELZÉSFÁJL") if age is None else (
            _pill("ok", f"{age:.0f} mp") if age <= SIGNAL_MAX_AGE_S else _pill("hiba", f"ELAVULT ({humanize_age(age)})"))
        master_pos = (f"{_e(x['master_dir'])} {_e(COMPONENT_SHORT_LABELS.get(x['master_tag'], x['master_tag']))} "
                      f"#{_e(x['master_ticket'])}") if x["master_has_pos"] else "nincs nyitott pozíció"
        master_card = (
            "<div class='puzzle-card'>"
            f"<div class='puzzle-title'>Master-jel · {_e(x['master_symbol'])} (magic {_e(x['master_magic'])})</div>"
            f"<div class='component-meta'>Jelzés kora: {sig_pill}</div>"
            f"<div class='component-meta'>Rezsim: {_e(REGIME_LABELS.get(x['master_regime'], x['master_regime']))} / {_e(x['master_vol'])}</div>"
            f"<div class='component-meta'>Master: {master_pos}</div>"
            f"<div class='component-meta muted-cell mono'>{_e(x['signal_file'])}</div>"
            "</div>"
        )
        op = x["summary"]["open_pos"]
        if op:
            vpos_body = (
                f"<div class='component-meta'>{_pill('info' if op['dir'] == 'BUY' else 'neutral', op['dir'])} "
                f"{_e(COMPONENT_SHORT_LABELS.get(op['tag'], op['tag']))} · master #{_e(op['ticket'])}</div>"
                f"<div class='component-meta'>Nyitás: {_e(op['price'])} ({_e(op['since'][11:16])})</div>"
                f"<div class='component-meta'>SL {_e(op['sl'])} · TP {_e(op['tp'])}</div>"
            )
        else:
            vpos_body = "<div class='empty' style='margin-top:4px'>nincs</div>"
        vpos_card = f"<div class='puzzle-card'><div class='puzzle-title'>Virtuális pozíció</div>{vpos_body}</div>"
        ages = x["summary"]["open_ages_today"]
        age_text = f"jel-kor nyitáskor: átl. {sum(ages) / len(ages):.0f} ms, max {max(ages)} ms" if ages else "ma még nem nyitott"
        today_card = (
            "<div class='puzzle-card'>"
            f"<div class='puzzle-title'>Ma ({_e(x['today'])}, szerveridő)</div>"
            + _net_line(f"Master valódi ({x['master_symbol']})", x["real_master_today"])
            + _net_line(f"Éles EA valódi ({x['symbol']})", x["real_slave_today"])
            + _net_line("Slave virtuális", x["summary"]["today"])
            + f"<div class='component-meta muted-cell'>{_e(age_text)}</div>"
            + _net_line("Slave virtuális összesen", x["summary"]["total"])
            + "</div>"
        )
        ev_rows = "".join(
            f"<tr><td>{_e(ev.get('server_time', ''))}</td><td>{_e(ev.get('mode', ''))}</td>"
            f"<td class='mono'>{_e(ev.get('event', ''))}</td><td>{_e(ev.get('master_ticket', ''))}</td>"
            f"<td>{_e(ev.get('dir', ''))}</td><td class='num'>{_e(ev.get('price', ''))}</td>"
            f"<td class='num'>{_e(ev.get('sl', ''))}</td><td class='num'>{_e(ev.get('tp', ''))}</td>"
            f"<td class='num'>{_e(ev.get('pnl_money', ''))}</td><td class='muted-cell'>{_e(ev.get('note', ''))}</td></tr>"
            for ev in x["events"]
        )
        ev_table = (
            "<div class='table-wrap' style='margin-top:12px'><table><thead><tr><th>Szerveridő</th><th>Mód</th>"
            "<th>Esemény</th><th>Master-ticket</th><th>Irány</th><th>Ár</th><th>SL</th><th>TP</th>"
            "<th>PnL ($)</th><th>Megjegyzés</th></tr></thead>"
            f"<tbody>{ev_rows}</tbody></table></div>"
        ) if ev_rows else "<p class='empty'>Még nincs esemény a naplóban.</p>"
        # sorrend a jelzés útja szerint: master -> slave (felhasználói kérés, 2026-09-25)
        blocks.append("<div class='puzzle-row'>" + master_card + slave_card + vpos_card + today_card + "</div>" + ev_table)
    return (
        "<div class='block'><h2>Signal Copier — master → slave</h2>"
        "<div class='sub'>Az IC Markets (referencia) döntéseit követő slave. ÁRNYÉK módban NEM kereskedik, csak "
        "virtuális pozíciót vezet és naplóz -- a „Ma” sorokban a valódi kötések (bróker-történet) mellett a slave "
        "virtuális eredménye látszik.</div>"
        + "".join(blocks) + "</div>"
    )


# Adminisztráció fül -- ugyanaz a pill-szótár-minta, mint a drift-badge-eknél fent.
_ADMIN_PILL_TAG = {"ok": "ok", "figyelem": "stale", "hiba": "hiba", "lejart": "hiba"}
_ADMIN_PILL_LABEL = {"ok": "OK", "figyelem": "Figyelem", "hiba": "Hiba", "lejart": "Lejárt"}


def _render_admin_calendar(status):
    pill = _pill(_ADMIN_PILL_TAG.get(status["status"], "neutral"),
                 _ADMIN_PILL_LABEL.get(status["status"], status["status"]))
    return f"<div class='component-meta'>{pill}</div><div class='sub' style='margin:8px 0 0'>{_e(status['text'])}</div>"


def _render_admin_baselines(rows):
    if not rows:
        return "<p class='empty'>Nincs betöltött baseline (live_baselines.json).</p>"
    body = "".join(
        f"<tr><td class='mono'>{_e(r['instance'])}</td><td>{_e(r['generated_at'])}</td>"
        f"<td>{_e(r['age_days']) if r['age_days'] is not None else '?'}</td>"
        f"<td>{_pill(_ADMIN_PILL_TAG.get(r['status'], 'neutral'), _ADMIN_PILL_LABEL.get(r['status'], r['status']))}</td></tr>"
        for r in rows
    )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Példány</th><th>Utolsó baseline</th>"
        "<th>Kor (nap)</th><th>Állapot</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


PAGE_CSS = """
:root {
  --bg:#f3f4f8; --bg-elev:#ffffff; --border:#e5e7f0; --text:#161821; --muted:#6b7280;
  --accent:#6366f1; --accent-soft:#eef0ff;
  --pos:#15803d; --pos-soft:#e9f9ee; --neg:#dc2626; --neg-soft:#fdecec;
  --amber:#b45309; --amber-soft:#fff4e0;
  --shadow:0 1px 2px rgba(16,24,40,.04), 0 4px 10px rgba(16,24,40,.05);
  --radius:14px;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#0e1015; --bg-elev:#171922; --border:#282b36; --text:#e7e9ef; --muted:#8b90a0;
    --accent:#818cf8; --accent-soft:#20223a;
    --pos:#4ade80; --pos-soft:#123321; --neg:#f87171; --neg-soft:#3a1414;
    --amber:#fbbf24; --amber-soft:#3a2c05;
    --shadow:0 1px 2px rgba(0,0,0,.5), 0 4px 12px rgba(0,0,0,.35);
    color-scheme: dark;
  }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font-family:'Segoe UI', system-ui, -apple-system, sans-serif; -webkit-font-smoothing:antialiased; }
.app { max-width:1240px; margin:0 auto; padding:0 20px 60px; }
.topbar { position:sticky; top:0; z-index:5; background:var(--bg); padding:18px 0 14px;
          border-bottom:1px solid var(--border); margin-bottom:20px;
          display:flex; align-items:center; gap:18px; flex-wrap:wrap; }
.brand { font-size:16px; font-weight:700; letter-spacing:-.01em; display:flex; align-items:center; gap:9px; white-space:nowrap; }
.brand .dot { width:9px; height:9px; border-radius:50%; background:var(--accent); box-shadow:0 0 0 4px var(--accent-soft); }
.tabs { display:flex; gap:3px; background:var(--bg-elev); border:1px solid var(--border); padding:4px; border-radius:11px; }
.tab-btn { border:none; background:transparent; color:var(--muted); font:inherit; font-size:12.5px; font-weight:600;
           padding:7px 14px; border-radius:8px; cursor:pointer; transition:background .15s,color .15s; white-space:nowrap; }
.tab-btn:hover { color:var(--text); }
.tab-btn.active { background:var(--accent); color:#fff; }
.actions { margin-left:auto; display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
.updated { font-size:11.5px; color:var(--muted); }
.refresh-btn { display:inline-flex; align-items:center; gap:7px; border:1px solid var(--border); background:var(--bg-elev);
               color:var(--text); font:inherit; font-size:12.5px; font-weight:600; padding:7px 14px; border-radius:9px;
               cursor:pointer; box-shadow:var(--shadow); }
.refresh-btn:hover { border-color:var(--accent); color:var(--accent); }
.refresh-btn .icon { display:inline-block; transition:transform .5s ease; }
.refresh-btn.spinning .icon { transform:rotate(360deg); }
.banner { display:flex; gap:10px; align-items:center; background:var(--amber-soft); color:var(--amber);
          border:1px solid var(--amber); border-radius:12px; padding:12px 16px; font-size:13px; font-weight:600;
          margin-bottom:18px; }
.panel { display:none; }
.panel.active { display:block; animation:fadeIn .18s ease; }
@keyframes fadeIn { from{opacity:0; transform:translateY(3px);} to{opacity:1; transform:none;} }
.block { background:var(--bg-elev); border:1px solid var(--border); border-radius:var(--radius);
         box-shadow:var(--shadow); padding:18px 20px; margin-bottom:18px; }
.block h2 { font-size:13.5px; margin:0 0 3px; font-weight:700; }
.block .sub { font-size:12px; color:var(--muted); margin:0 0 14px; }
.table-wrap { overflow-x:auto; border:1px solid var(--border); border-radius:10px; }
table { width:100%; border-collapse:collapse; font-size:12.5px; }
th, td { text-align:left; padding:9px 12px; white-space:nowrap; }
thead th { background:var(--bg); color:var(--muted); font-weight:600; font-size:10.5px;
           text-transform:uppercase; letter-spacing:.05em; border-bottom:1px solid var(--border); }
tbody tr:not(:last-child) td { border-bottom:1px solid var(--border); }
tbody tr:hover { background:var(--accent-soft); }
.mono { font-family:Consolas,'Cascadia Code',monospace; font-size:11.5px; }
.muted-cell, .muted { color:var(--muted); }
.num { text-align:right; font-variant-numeric:tabular-nums; }
.num.pos { color:var(--pos); } .num.neg { color:var(--neg); } .num.zero { color:var(--muted); }
.empty { color:var(--muted); font-style:italic; font-size:13px; padding:6px 0; }
.pill { display:inline-flex; align-items:center; padding:3px 10px; border-radius:999px; font-size:10.5px; font-weight:700; letter-spacing:.02em; }
.pill-ok { background:var(--pos-soft); color:var(--pos); }
.pill-stale { background:var(--amber-soft); color:var(--amber); }
.pill-hiba { background:var(--neg-soft); color:var(--neg); }
.pill-info { background:var(--accent-soft); color:var(--accent); }
.pill-neutral { background:var(--bg); color:var(--muted); border:1px solid var(--border); }
.stat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
.stat-card { background:var(--bg); border:1px solid var(--border); border-radius:12px; padding:16px; }
.stat-label { font-size:11.5px; color:var(--muted); margin-bottom:10px; text-transform:uppercase; letter-spacing:.04em; }
.stat-value { font-size:23px; font-weight:700; font-variant-numeric:tabular-nums; }
.stat-sub { font-size:12.5px; color:var(--muted); margin-top:4px; }
.stat-card.pos .stat-value, .stat-card.pos .arrow { color:var(--pos); }
.stat-card.neg .stat-value, .stat-card.neg .arrow { color:var(--neg); }
.puzzle-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }
.puzzle-card { background:var(--bg); border:1px solid var(--border); border-top:3px solid var(--accent);
               border-radius:12px; padding:14px; }
.puzzle-title { font-weight:700; font-size:12.5px; margin-bottom:10px; }
.share-bar { height:6px; border-radius:99px; background:var(--border); overflow:hidden; margin-bottom:10px; }
.share-fill { height:100%; border-radius:99px; }
.refresh-meta { display:flex; align-items:center; gap:8px; height:14px; margin:0 0 14px;
                font-size:11px; color:var(--muted); white-space:nowrap; }
.refresh-meta-label { white-space:nowrap; }
.refresh-bar-track { flex:0 0 54px; height:5px; border-radius:99px; background:var(--border); overflow:hidden; }
.refresh-bar-fill { display:block; height:100%; border-radius:99px; background:var(--accent);
                     transition:width 1s linear; }
.admin-steps { margin:0; padding-left:20px; }
.admin-steps li { margin-bottom:10px; font-size:13px; line-height:1.5; }
.admin-steps li:last-child { margin-bottom:0; }
.component-meta { font-size:11.5px; color:var(--muted); margin-bottom:3px; }
.component-net { font-size:15px; font-weight:700; margin-top:6px; }
.component-net.pos { color:var(--pos); } .component-net.neg { color:var(--neg); } .component-net.zero { color:var(--muted); }
.ctl-cell { white-space:nowrap; }
.ctl-btn { border:1px solid var(--border); background:var(--bg-elev); color:var(--text); font:inherit;
           font-size:11px; font-weight:600; padding:4px 10px; border-radius:7px; cursor:pointer; margin-left:6px; }
.ctl-btn:hover { border-color:var(--accent); color:var(--accent); }
.ctl-btn.stop:hover { border-color:var(--neg); color:var(--neg); }
.ctl-btn.start:hover { border-color:var(--pos); color:var(--pos); }
.archive-buttons { display:flex; flex-wrap:wrap; gap:8px; }
.archive-btn { border:1px solid var(--amber); background:var(--amber-soft); color:var(--amber); font:inherit;
               font-size:11px; font-weight:600; padding:4px 10px; border-radius:7px; cursor:pointer; }
.archive-btn:hover { filter:brightness(0.92); }

/* --- Mobil / PWA -- 2026-09-08, felhasznaloi kerés: "app-szerű" hasznalat telefonon --------- */
@media (max-width: 640px) {
  .app { padding: 0 12px 90px; }
  .topbar { flex-direction: column; align-items: stretch; gap: 8px; padding: 12px 0 10px; }
  .actions { width: 100%; justify-content: space-between; align-items: center; }
  .updated { font-size: 11px; line-height: 1.4; }
  .updated-detail { display: none; } /* a teljes Common\Files-útvonal csak asztali nézetben látszik */
  .refresh-btn { flex: 0 0 auto; padding: 9px; border-radius: 50%; }
  .refresh-label { display: none; } /* mobilon csak az ikon -- kevés a hely a felirat mellett */
  .refresh-btn .icon { font-size: 16px; }
  /* A fül-sav a képernyő aljára rögzül, mint egy natív app tab-barja -- ujjal kényelmesebb, mint
     egy felül, szűk sávba zsúfolt gombsor. */
  .tabs {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 20;
    border-radius: 0; border-width: 1px 0 0 0; padding: 6px 6px calc(6px + env(safe-area-inset-bottom));
    justify-content: space-around; box-shadow: 0 -2px 12px rgba(0,0,0,.12);
  }
  .tab-btn { flex: 1; text-align: center; padding: 11px 6px; font-size: 12.5px; }
  .tab-long { display: none; } /* az alsó fülsávon 5 fül fér el -- "Signal Copier" helyett csak "Copier" */
  .block { padding: 14px; }
  table { font-size: 11.5px; }
  th, td { padding: 7px 9px; }
  .stat-grid, .puzzle-row { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 380px) {
  .stat-grid, .puzzle-row { grid-template-columns: 1fr; }
}
/* Amikor "Kezdőképernyőhöz adva" (PWA standalone) fut, nincs böngésző-UI -- a felső biztonsagi
   zóna (pl. iOS notch) miatt extra felső térköz kell a sticky sávnak. */
@media (display-mode: standalone) {
  .topbar { padding-top: calc(env(safe-area-inset-top) + 12px); }
}
"""

PAGE_JS = """
(function () {
  var tabs = document.querySelectorAll('.tab-btn');
  var panels = document.querySelectorAll('.panel');
  function activate(name) {
    tabs.forEach(function (t) { t.classList.toggle('active', t.dataset.tab === name); });
    panels.forEach(function (p) { p.classList.toggle('active', p.dataset.panel === name); });
    try { localStorage.setItem('rf_active_tab', name); } catch (e) {}
  }
  tabs.forEach(function (t) { t.addEventListener('click', function () { activate(t.dataset.tab); }); });
  var fromQuery = new URLSearchParams(location.search).get('tab');
  var saved = fromQuery;
  if (!saved) { try { saved = localStorage.getItem('rf_active_tab'); } catch (e) {} }
  activate(saved && document.querySelector('.tab-btn[data-tab="' + saved + '"]') ? saved : 'status');

  // Csendes adat-frissítés: NEM location.reload() -- az teljes navigációt jelentene (villanás,
  // scroll-pozíció elvesztése), ehelyett csak lekérjük az aktuális oldalt és a NÉHÁNY, ismert ID-jú
  // tartalom-konténer innerHTML-jét cseréljük -- a fül-állapot/scroll érintetlen marad.
  var SWAP_IDS = ['updatedText', 'calendarSlot', 'panel-status', 'panel-copier', 'panel-summary', 'panel-regime', 'panel-admin'];
  var refreshing = false;
  function refreshData() {
    if (refreshing) return;
    refreshing = true;
    // A vizszintesen gorgetheto tablazatok (.table-wrap) gorgetesi pozicioit KULON el kell
    // menteni MIELOTT az innerHTML-cserere kerulne sor -- az uj DOM-elemek mindig 0 gorgetessel
    // jonnek letre, enelkul minden frissites visszaugrana a tabla bal szelere (2026-09-09,
    // felhasznaloi jelzes -- mobilon a jobb oldali oszlopokra gorgetve a 15 mp-es auto-frissites
    // visszadobta a nezetet). Feltetelezzuk, hogy a tablazatok szama/sorrendje frissitesek kozott
    // nem valtozik -- index szerint parositjuk a regi/uj .table-wrap elemeket.
    var scrollPositions = Array.prototype.map.call(
      document.querySelectorAll('.table-wrap'), function (el) { return el.scrollLeft; }
    );
    fetch(location.pathname + location.search, { cache: 'no-store' })
      .then(function (r) { return r.text(); })
      .then(function (htmlText) {
        var doc = new DOMParser().parseFromString(htmlText, 'text/html');
        SWAP_IDS.forEach(function (id) {
          var oldEl = document.getElementById(id);
          var newEl = doc.getElementById(id);
          if (oldEl && newEl) oldEl.innerHTML = newEl.innerHTML;
        });
        Array.prototype.forEach.call(document.querySelectorAll('.table-wrap'), function (el, i) {
          if (scrollPositions[i]) el.scrollLeft = scrollPositions[i];
        });
      })
      .catch(function () { /* átmeneti hiba -- a következő ciklus úgyis újra próbálja */ })
      .then(function () { refreshing = false; });
  }

  var btn = document.getElementById('refreshBtn');
  if (btn) {
    btn.addEventListener('click', function () {
      btn.classList.add('spinning');
      refreshData();
      setTimeout(function () { btn.classList.remove('spinning'); }, 500);
    });
  }

  // Tavoli le/fel-kapcsolo (2026-09-09) -- a gombok minden refreshData()-hivas utan UJRA
  // legeneralodnak (innerHTML-csere), ezert eseny-delegalassal, a stabil document-en figyelunk,
  // nem az egyes gombokra kulon-kulon kotve. Megerosito confirm() ELOTT, mert nincs szerver-oldali
  // auth -- ez az EGYETLEN vedelem egy veletlen erintes ellen (lasd PLAN.md/SESSION_LOG.md).
  document.addEventListener('click', function (e) {
    var ctlBtn = e.target.closest('.ctl-btn');
    if (!ctlBtn) return;
    var symbol = ctlBtn.dataset.symbol;
    var magic = ctlBtn.dataset.magic;
    var action = ctlBtn.dataset.action;
    var verb = action === 'stop' ? 'LEÁLLÍTOD' : 'ELINDÍTOD';
    if (!confirm(verb + ': ' + symbol + ' (magic ' + magic + ')?\\nEz valós kereskedést érint.')) return;
    ctlBtn.disabled = true;
    fetch('/api/control?symbol=' + encodeURIComponent(symbol) + '&magic=' + encodeURIComponent(magic)
          + '&action=' + encodeURIComponent(action), { method: 'POST' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return refreshData(); })
      .catch(function (err) { alert('Hiba: ' + err.message); ctlBtn.disabled = false; });
  });

  // Heartbeat archiválás + reset (2026-09-13) -- ugyanaz az esemeny-delegalasi minta, mint a
  // fenti .ctl-btn-nel (a panel-admin is a SWAP_IDS resze, tehat a gomb minden refreshData()
  // utan ujrageneralodik). A szerver-oldali valasz-szoveg (siker VAGY elutasitas oka, pl. "piac
  // nyitva") kozvetlenul alert()-ben jelenik meg, mert ez az egyetlen hely, ahol a felhasznalo
  // ezt latja.
  document.addEventListener('click', function (e) {
    var archBtn = e.target.closest('.archive-btn');
    if (!archBtn) return;
    var terminal = archBtn.dataset.terminal;
    if (!confirm('Ez ÚJRAINDÍTJA a(z) ' + terminal + ' MT5 terminált és MINDEN benne futó EA-t.\\n'
        + 'Csak akkor csináld, ha a piac ZÁRVA van MINDEN ott futó instrumentumra.\\n\\nFolytatod?')) return;
    archBtn.disabled = true;
    fetch('/api/archive-heartbeats?terminal=' + encodeURIComponent(terminal), { method: 'POST' })
      .then(function (r) { return r.text().then(function (t) { alert(t); }); })
      .then(function () { return refreshData(); })
      .catch(function (err) { alert('Hiba: ' + err.message); })
      .then(function () { archBtn.disabled = false; });
  });
  setInterval(refreshData, __AUTOREFRESH_MS__);

  // Elo visszaszamlalo (2026-09-11, felhasznaloi keres): a trade-lista szerver-oldali
  // frissitese fuggetlen ciklusidoben fut (HISTORY_REFRESH_S), a bongeszo pedig kulon
  // idokozonkent kerdezi le az oldalt (PAGE_AUTOREFRESH_S) -- ez a masodperces szamlalo
  // MINDKETTOTOL fuggetlenul, sajat 1 mp-es tick-kel fut, hogy a felhasznalo lassa, mennyi
  // ideje frissult ill. mikor varhato a kovetkezo adat, nem csak higgyen benne.
  function tickRefreshMeta() {
    var el = document.getElementById('tradesRefreshMeta');
    if (!el) return;
    var epoch = parseInt(el.dataset.epoch, 10);
    var interval = parseInt(el.dataset.interval, 10);
    if (!epoch || !interval) return;
    // Csak a szoveget/csik-szelesseget irjuk at, a DOM-szerkezetet (label + track + fill) SOHA --
    // igy a sor magassaga allando marad, nincs "felcsuszas" frissiteskor (lasd _render_refresh_meta
    // fejlec-kommentjet).
    var secsEl = el.querySelector('.refresh-meta-secs');
    var fillEl = el.querySelector('.refresh-bar-fill');
    var remaining = Math.max(0, Math.round(interval - (Date.now() / 1000 - epoch)));
    var pct = Math.max(0, Math.min(100, Math.round((remaining / interval) * 100)));
    if (secsEl) secsEl.textContent = remaining;
    if (fillEl) fillEl.style.width = pct + '%';
  }
  tickRefreshMeta();
  setInterval(tickRefreshMeta, 1000);
})();
"""


def render_page():
    with STATE_LOCK:
        s = dict(STATE)

    calendar_html = ""
    if s["calendar_warnings"]:
        calendar_html = f"<div class='banner'>⚠️ {_e('   ·   '.join(s['calendar_warnings']))}</div>"
    if s["mt5_link_issues"]:
        calendar_html += "".join(f"<div class='banner'>⚠️ MT5-kapcsolat · {_e(name)}: {_e(msg)}</div>"
                                 for name, msg in sorted(s["mt5_link_issues"].items()))

    common_dirs = s["common_files_dirs"]
    common_dirs_text = (f"Common\\Files mappák: {_e(', '.join(common_dirs))}" if len(common_dirs) > 1
                         else f"Common\\Files mappa: {_e(common_dirs[0]) if common_dirs else '?'}")

    page_js = PAGE_JS.replace("__AUTOREFRESH_MS__", str(PAGE_AUTOREFRESH_S * 1000))

    return f"""<!doctype html>
<html lang="hu"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>RegimeFramework EA — dashboard</title>
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/webapp/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/webapp/icon.svg">
<meta name="theme-color" content="#6366f1">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="RegimeFW">
<style>{PAGE_CSS}</style>
</head><body><div class="app">

<div class="topbar">
  <div class="brand"><span class="dot"></span>RegimeFramework</div>
  <nav class="tabs">
    <button class="tab-btn" data-tab="status">Élő állapot</button>
    <button class="tab-btn" data-tab="copier"><span class="tab-long">Signal </span>Copier</button>
    <button class="tab-btn" data-tab="summary">Összesítés</button>
    <button class="tab-btn" data-tab="regime">Rezsim</button>
    <button class="tab-btn" data-tab="admin">Adminisztráció</button>
  </nav>
  <div class="actions">
    <span class="updated" id="updatedText"><span class="updated-detail">Terminálok: {_e(', '.join(s['terminals_names']))} · {common_dirs_text}<br></span>
    Frissítve: {_e(s['updated_at'])}</span>
    <button id="refreshBtn" class="refresh-btn"><span class="icon">⟳</span><span class="refresh-label">Frissítés</span></button>
  </div>
</div>

<div id="calendarSlot">{calendar_html}</div>

<section class="panel" data-panel="status">
  <div id="panel-status">
  <div class="block">
    <h2>EA-példányok állapota</h2>
    <div class="sub">Hétvégén/piaci zárás idején a STALE állapot VÁRHATÓ, nem feltétlenül hiba.</div>
    {_render_heartbeats(s['heartbeats'])}
  </div>
  <div class="block">
    <h2>Legutóbbi zárt trade-ek</h2>
    <div class="sub">{_e(s['trades_summary'])}</div>
    {_render_refresh_meta(s['trades_refreshed_epoch'], HISTORY_REFRESH_S)}
    {_render_trades(s['trades'])}
  </div>
  </div>
</section>

<section class="panel" data-panel="copier">
  <div id="panel-copier">
  {_render_signal_copier(s['signal_copier'])}
  </div>
</section>

<section class="panel" data-panel="summary">
  <div id="panel-summary">
  <div class="block">
    <h2>Eredmény időszakonként</h2>
    <div class="sub">A jelenlegi teljes egyenleg %-ában · {_e(s['summary_note'])}</div>
    {_render_summary_cards(s['summary_cards'])}
  </div>
  <div class="block">
    <h2>Terminálonkénti bontás</h2>
    {_render_summary_detail(s['summary_detail'])}
  </div>
  </div>
</section>

<section class="panel" data-panel="regime">
  <div id="panel-regime">
  <div class="block">
    <h2>Aktuális rezsim EA-példányonként</h2>
    {_render_regime_rows(s['regime_rows'])}
  </div>
  <div class="block">
    <h2>Komponensek szerinti bontás — teljes történet</h2>
    <div class="sub">{_e(s['components_note'])}</div>
    {_render_component_cards(s['component_stats'])}
  </div>
  <div class="block">
    <h2>Élő teljesítmény vs. validált alap</h2>
    <div class="sub">Példányonként/komponensenként -- a validált (walk-forward backtest)
      baseline-hoz képest. "Várakozik" = még nincs elég élő trade a megbízható összevetéshez.</div>
    {_render_baseline_drift_cards(s['baseline_stats_by_instance'], s['baselines'])}
  </div>
  </div>
</section>

<section class="panel" data-panel="admin">
  <div id="panel-admin">
  <div class="block">
    <h2>Naptár / évváltás</h2>
    <div class="sub">A `market_holidays.json` melyik évig van feltöltve -- ez adja az élő EA-k
      ünnepnap-védelmét is (`MarketHolidays.mqh`), nem csak a dashboard figyelmeztetést.</div>
    {_render_admin_calendar(s['admin_calendar_status'])}
  </div>
  <div class="block">
    <h2>Negyedéves újraoptimalizálás</h2>
    <div class="sub">Az utolsó `live_baselines.json`-generálás óta eltelt idő példányonként --
      "Lejárt" ≥ {BASELINE_OVERDUE_DAYS} nap, "Figyelem" ≥ {BASELINE_WARN_DAYS} nap.</div>
    {_render_admin_baselines(s['admin_baseline_rows'])}
  </div>
  <div class="block">
    <h2>Optimalizációs rutin -- gyors összefoglaló</h2>
    <ol class="admin-steps">
      <li><b>Optuna</b>: a szimbólum warm-start/retune szkriptje (`research/&lt;symbol&gt;_warmstart_retune.py`),
        ≥200 trial (lásd feedback-optuna-trial-minimum), amíg a walk-forward pontszám javul.</li>
      <li><b>Strategy Tester</b>: a nyertes paraméterek kereszt-ellenőrzése MT5 Strategy Testerben,
        valós tick-adaton, mindkét élő bróker terminálján.</li>
      <li><b>.set fájl kirakása</b>: export a bevált paraméterekkel (`Experts/RegimeFramework/
        presets/&lt;SYMBOL&gt;.set`), majd az élő charton az EA input frissítése/reload.</li>
      <li><b>Baseline frissítés</b>: `generate_live_baseline.py` mindkét bróker terminállal, majd
        a kimenő `live_baselines.json` felmásolása a VPS-re -- <b>exe-újrafordítás/-indítás
        NÉLKÜL</b>, lásd fent.</li>
    </ol>
  </div>
  <div class="block">
    <h2>Heartbeat archiválás + reset</h2>
    <div class="sub">Csak ZÁRT piacon fut le (a `live_instances.json`-ban regisztrált ÖSSZES
      instrumentumra ellenőrizve) -- archiválja az aktuális heartbeat-fájlokat egy időbélyeges
      mappába, törli az árva (nem regisztrált) fájlokat, majd ÚJRAINDÍTJA a teljes terminál-
      folyamatot (minden benne futó EA-t érinti) a tartós hibaszámláló/hibaüzenet-reset
      érdekében. Ha bármelyik instrumentum piaca nyitva van, a teljes művelet elutasítva.</div>
    {_render_heartbeat_archive_buttons(s.get('terminals', []))}
  </div>
  </div>
</section>

</div>
<script>{page_js}</script>
</body></html>"""


# ------------------------------------------------------------------ HTTP szerver

# Statikus PWA-fajlok (útvonal -> (fájlnév a WEBAPP_DIR-ben, Content-Type)) -- lásd WEBAPP_DIR.
STATIC_ROUTES = {
    "/manifest.json": ("manifest.json", "application/manifest+json"),
    "/webapp/icon.svg": ("icon.svg", "image/svg+xml"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in STATIC_ROUTES:
            filename, content_type = STATIC_ROUTES[path]
            try:
                body = (WEBAPP_DIR / filename).read_bytes()
            except OSError:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)
            return

        if path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        body = render_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_text(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # Tavoli le/fel-kapcsolo (2026-09-09) -- lasd a live EA-k g_controlFileName fejlec-
        # kommentjet, PLAN.md-t es SESSION_LOG.md-t a teljes mechanizmus-indoklasert. Ez a
        # dashboard ELSO IRO vegpontja -- nincs szerver-oldali auth (ugyanaz a dontes, mint a
        # tobbi GET-oldalnal), a kliens-oldali confirm() az egyetlen vedelem veletlen erintes ellen.
        path = self.path.split("?", 1)[0]
        if path == "/api/archive-heartbeats":
            self._handle_archive_heartbeats()
            return
        if path != "/api/control":
            self.send_response(404)
            self.end_headers()
            return

        query = parse_qs(urlsplit(self.path).query)
        symbol = query.get("symbol", [""])[0]
        magic = query.get("magic", [""])[0]
        action = query.get("action", [""])[0]

        with STATE_LOCK:
            common_files_dirs = list(STATE["common_files_dirs"])

        directory = _find_instance_dir(common_files_dirs, symbol, magic) if symbol and magic else None
        if not directory or action not in ("start", "stop"):
            self._respond_text(400, "Ismeretlen példány vagy érvénytelen action.")
            return

        control_path = _control_file_path(directory, symbol, magic)
        try:
            if action == "stop":
                with open(control_path, "w", encoding="utf-8") as f:
                    f.write(f"disabled_at={datetime.now().isoformat(timespec='seconds')}\n"
                            f"reason=manual dashboard stop\n")
            elif os.path.exists(control_path):
                os.remove(control_path)
        except OSError as exc:
            self._respond_text(500, f"Fájlművelet sikertelen: {exc}")
            return

        self._respond_text(200, "OK")

    def _handle_archive_heartbeats(self):
        # "Heartbeat archiválás + reset" (2026-09-13, felhasznaloi keres) -- lasd PLAN.md
        # ("graceful-prancing-reef") a teljes indoklasert. Ez a dashboard MASODIK iro vegpontja,
        # es a legnagyobb hatasu: teljes terminal-folyamatot (tobb EA-t) inditja ujra, es fajlokat
        # torol. A kliens-oldali confirm() ELOTT ITT IS az egyetlen vedelem veletlen erintes ellen,
        # DE szerver-oldalon egy VALODI (nem csak UI-szintu) piac-nyitva ellenorzes is van --
        # nyitott piacon a MUVELET EGESZE elutasitva, meg archivalas sem tortenik.
        query = parse_qs(urlsplit(self.path).query)
        terminal_name = query.get("terminal", [""])[0]

        with STATE_LOCK:
            terminals = list(STATE.get("terminals", []))
        terminal = next((t for t in terminals if t["name"] == terminal_name), None)
        if terminal is None:
            self._respond_text(400, f"Ismeretlen terminál: {terminal_name!r}")
            return

        instances = load_live_instances_config()
        terminal_instances = [i for i in instances if i["terminal"] == terminal_name]
        if not terminal_instances:
            self._respond_text(
                409,
                "Nincs regisztrált EA-példány ehhez a terminálhoz a live_instances.json-ban -- "
                "biztonsági okból nem futtatjuk (minden fájl árvának tűnne, és a piac-állapotot "
                "sem tudnánk ellenőrizni). Töltsd ki a regisztert, majd próbáld újra."
            )
            return

        symbols = sorted({i["symbol"] for i in terminal_instances})
        connector = CONNECTOR
        with MT5_LOCK:
            if not connector.connect(terminal):
                self._respond_text(500, f"Nem sikerült csatlakozni a(z) {terminal_name} terminálhoz.")
                return
            open_symbols = []
            unknown_symbols = []
            for symbol in symbols:
                active = _is_symbol_active(symbol)
                if active is None:
                    unknown_symbols.append(symbol)
                elif active:
                    open_symbols.append(symbol)

        if unknown_symbols:
            self._respond_text(
                409,
                f"Nem sikerült lekérdezni a piac állapotát ehhez: {', '.join(unknown_symbols)} -- "
                "biztonsági okból nem futtatjuk (sem archiválás, sem reset)."
            )
            return
        if open_symbols:
            self._respond_text(
                409,
                f"Piac NYITVA ezeken: {', '.join(open_symbols)} -- nincs archiválás/reset, amíg "
                "mindegyik instrumentum piaca zárva nincs."
            )
            return

        try:
            result = _archive_and_reset_terminal(terminal, instances)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self._respond_text(500, f"Archiválás/reset sikertelen: {exc}")
            return

        restart = result["restart"]
        if restart["relaunched"]:
            restart_msg = (f"terminál leállítva, a watchdog {restart['waited_s']:.0f} mp alatt "
                            f"visszahozta (PID {', '.join(restart['new_pids'])}).")
        else:
            restart_msg = (
                f"⚠️ terminál LEÁLLÍTVA, de {restart['waited_s']:.0f} mp alatt NEM indult újra "
                "automatikusan -- fut-e a terminal_watchdog.py a VPS-en (interaktív RDP-"
                "munkamenetből)? Indítsd el kézzel a terminált, amíg ezt kivizsgáljuk."
            )
        self._respond_text(
            200 if restart["relaunched"] else 207,
            f"{result['archived']} fájl archiválva"
            + (f" ide: {result['archive_dir']}" if result["archive_dir"] else " (nem volt mit)")
            + f" · {result['orphans_deleted']} árva törölve · {restart_msg}"
        )

    def log_message(self, fmt, *args):
        # KRITIKUS: self.address_string() (az ős osztály alapértelmezése) forditott DNS-t hivna
        # (socket.getfqdn()) MINDEN egyes keresnel -- ha a VPS-en a DNS-feloldas akad/blokkolt,
        # ez kerésenkent akar percekig is elakadhat, valasz nelkul (2026-09-08, VPS-en eszlelt
        # "Empty reply from server" hiba oka -- a nyers IP-cim hasznalata NEM igenyel halozati
        # hivast).
        print(f"[{self.log_date_time_string()}] {self.client_address[0]} " + fmt % args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0",
                         help="Melyik interfészen figyeljen (alapértelmezett: 0.0.0.0, minden interfész).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    terminals = load_terminals_config()
    common_files_dirs = sorted({t["common_files_dir"] for t in terminals})

    thread = threading.Thread(target=refresh_loop, args=(terminals, common_files_dirs), daemon=True)
    thread.start()

    # ThreadingHTTPServer, NEM sima HTTPServer (2026-09-08, VPS-en eszlelt teljes lefagyas oka):
    # az egyszalu HTTPServer EGYSZERRE csak EGY kapcsolatot kezel -- ha barmelyik kliens-kapcsolat
    # megszakad/elakad (halozati villanas, ket tab egyszerre), a szerver MINDENKI masnak is
    # leblokkol, amig az az egy fel nem szabadul. A megosztott STATE-et amugy is STATE_LOCK vedi,
    # es MT5-hivas KIZAROLAG a hattérszalban tortenik (a kereskiszolgalo szalak csak a STATE-et
    # olvassak) -- tobbszalu kiszolgalasra biztonsagosan atallithato.
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"RegimeFramework dashboard (web) fut: http://{args.host}:{args.port}/")
    print("FONTOS: nincs jelszó/token -- a hozzáférést a tűzfalon (csak ismert IP-ről engedélyezve) "
          "kell korlátozni, ugyanúgy, ahogy az RDP-nél. Ctrl+C a leállításhoz.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            mt5.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
