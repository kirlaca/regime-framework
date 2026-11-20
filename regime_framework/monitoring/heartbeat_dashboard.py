"""
monitoring/heartbeat_dashboard.py — a `heartbeat_watchdog.py` CLI-ellenőrzésének GUI-verziója,
kereskedési történettel, TÖBB TERMINÁL/BRÓKER kezelésével, és egy idő-összesítő nézettel
(2026-09-06).

Nem duplikálja a heartbeat parse/status-logikát -- a `heartbeat_watchdog` modult importálja
(`parse_heartbeat`, `check_heartbeat`, `HEARTBEAT_PATTERN`), csak egy auto-frissülő Tkinter
felületet rajzol rá. Cél: a "$2000-os IC Markets pilot, 1 hónap, beavatkozás nélkül, de passzívan
figyelve" igényhez egy egy-pillantásos áttekintés, ahelyett hogy a heartbeat .txt fájlokat kellene
kézzel megnyitogatni.

HÁROM FÜL:
  1. "Élő állapot" -- EA-példányok heartbeat-státusza + legutóbbi zárt trade-ek listája.
  2. "Összesítés" -- nap/hét/hónap/év bontású eredmény, nominálisan és %-ban, kártyás elrendezésben
     (2026-09-06, felhasználói kérés: "harmonikusabb, szebb felület", szándékosan nem
     előírt konkrét elrendezéssel).
  3. "Rezsim & komponensek" (2026-09-07, felhasználói kérés) -- aktuális rezsim EA-példányonként
     (a heartbeat `current_regime`/`current_vol_band` mezőiből, lásd RegimeFramework_EA(_ICMarkets)
     .mq5 WriteHeartbeat()), komponensenkénti (MeanReversion/TrendFollowing/LastHourContinuation/
     FridayShort) teljes trade-történet-bontás pasztell "puzzle"-kártyákon (a telítettség a
     komponens saját trade-arányát mutatja, heatmap-szerűen), és egy naptár-figyelmeztető sáv, ha
     a következő `CALENDAR_WARNING_DAYS_AHEAD` napon belül piaci ünnepnap várható valamelyik
     ismert szimbólumra (`data/market_holidays.json`, lásd `core/market_calendar.py`). A
     komponens-bontás a NYITÓ deal comment-jét használja (position_id-vel párosítva a záróhoz),
     NEM a záró deal saját comment-jét, mert egy natív SL/TP-zárás felülírhatja azt.

A %-os számítás EGYSZERŰSÍTETT: minden időszak %-a a JELENLEGI (élő, `account_info().balance`)
teljes egyenleghez viszonyítva ("ez az időszaki eredmény a mostani tőkéd hány százaléka") -- NEM
egy teljes historikus egyenleg-görbe rekonstrukciója napi bontásban. Ez a leggyakoribb, legkönnyebben
értelmezhető megközelítés retail kereskedési felületeken, és elkerüli a hiba-lehetőségeket, amiket
egy hiányos/hosszú historikus deal-lista alapú rekonstrukció hozna be.

TÖBB TERMINÁL (a VPS-en egy külön könyvtárból indított MÁSODIK MT5-példány is fut, amit ez a
fejlesztői gép nem lát közvetlenül): a terminál-útvonalak egy `terminals.json` fájlból jönnek
(ugyanebben a mappában, lásd `terminals.example.json` sablon) -- HA NINCS ilyen fájl, a script
single-terminál módban fut (visszafelé kompatibilis, a jelenlegi gép/telepítés alapértelmezett
terminálját használja `mt5.initialize()`-zal, path nélkül).

A heartbeat-fájlok mindig a szokásos, MEGOSZTOTT `%APPDATA%\\MetaQuotes\\Terminal\\Common\\Files`
mappában landolnak MINDEN telepített terminálnál (kivéve ha egy adott példány PORTABLE módban fut
és emiatt saját, külön Common-mappát használ -- ekkor a `terminals.json`-ban a `common_files_dir`
mezővel felülírható terminálonként). A trade-történethez/összesítéshez viszont MINDEN konfigurált
terminálhoz KÜLÖN kell kapcsolódni (`mt5.initialize(path=...)`, majd `mt5.shutdown()`, egymás
után) -- a Python MT5 API egyszerre csak EGY terminál-kapcsolatot tart nyitva.

Futtatás (fejlesztéshez, Python-nal): python -m regime_framework.monitoring.heartbeat_dashboard

Önálló .exe csomagolás (VPS-re, Python-telepítés NÉLKÜL futtatható -- 2026-09-06, felhasználói
kérés). A `optuna_research` gyökeréből:

    pyinstaller --onefile --windowed --name RegimeFramework_Dashboard --paths "D:\\XM\\optuna_research" \\
      --collect-all numpy --collect-all MetaTrader5 \\
      --distpath dist --workpath build --specpath build \\
      regime_framework/monitoring/heartbeat_dashboard.py

A `--paths` kapcsoló KRITIKUS -- e nélkül a PyInstaller a `D:\\XM\\Optuna\\venv`-be telepített
elavult editable-install-t találhatná meg elsőként (lásd [[regime-framework-gotchas]] 5. pont),
és a RÉGI kódot csomagolná be. A `--collect-all numpy --collect-all MetaTrader5` a MetaTrader5
csomag belső numpy-függőségét hidalja át (enélkül `ModuleNotFoundError: numpy` fut-időben).

**2026-09-11 óta nincs `--add-data` a naptár-JSON-hoz** (lásd `core/market_calendar.py` fejléc-
kommentjét) -- a `market_holidays.json`-t mostantól az .exe MELLETT keresi (`sys.executable`
könyvtárában), hogy egy évváltás ne igényeljen újrafordítást, csak fájlcserét. Eredmény:
`dist/RegimeFramework_Dashboard.exe` -- VPS-re másolva, mellé egy kitöltött `terminals.json`-nal
(lásd `terminals.example.json`) ÉS egy `market_holidays.json`-nal, Python nélkül futtatható.
"""

import glob
import json
import os
import sys
import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk

import MetaTrader5 as mt5

from regime_framework.monitoring.heartbeat_watchdog import (
    COMMON_FILES_DIR as DEFAULT_COMMON_FILES_DIR,
    HEARTBEAT_PATTERN,
    check_heartbeat,
    parse_heartbeat,
)
from regime_framework.core.market_calendar import is_market_holiday, load_calendar

HEARTBEAT_REFRESH_MS = 10_000    # 10 másodpercenként
HISTORY_REFRESH_MS = 30_000      # 30 másodpercenként (MT5-lekérdezés drágább, mint fájlolvasás)
SUMMARY_REFRESH_MS = 60_000      # 60 másodpercenként (a legdrágább lekérdezés, hosszú historikus ablak)
COMPONENTS_REFRESH_MS = 90_000   # 90 másodpercenként ("teljes történet" lekérdezés, ritkán változik)
HISTORY_LOOKBACK_DAYS = 30
SUMMARY_LOOKBACK_DAYS = 400      # bőven egy naptári év + puffer, az "Ez az év" kártyához
COMPONENTS_LOOKBACK_DAYS = 3650  # "teljes történet" -- ~10 év, bőven távoli kezdőpont
MAX_TRADES_SHOWN = 40
CALENDAR_WARNING_DAYS_AHEAD = 3  # 2026-09-07: felhasználói kérés, "3 nappal előtte naptár figyelmeztetés"

# --- Komponensek (2026-09-07, "melyik komponens kereskedett" monitoring-bővítés) ---
# Az EA a POSITION_COMMENT/deal.comment mezőbe írja ezeket nyitáskor (OWNER_TAG_* a .mq5-ben) --
# lásd RegimeFramework_EA(_ICMarkets).mq5 OWNER_TAG_* defineket.
COMPONENT_LABELS = {
    "RF_MR": "MeanReversion", "RF_TF": "TrendFollowing",
    "RF_LHC": "LastHourContinuation", "RF_FS": "FridayShort",
}
COMPONENT_ORDER = ["RF_MR", "RF_TF", "RF_LHC", "RF_FS"]
# (halvány, telt) pasztell szín-pár komponensenként -- a kettő közti interpolációt a használati
# gyakoriság (trade-darabszám aránya) vezérli, "mint egy heating charton" (felhasználói kérés).
COMPONENT_COLORS = {
    "RF_MR": ("#eaf1fb", "#a9c7ec"),    # pasztell kék
    "RF_TF": ("#eaf7ee", "#a7d9b6"),    # pasztell zöld
    "RF_LHC": ("#f3edfa", "#c6aee0"),   # pasztell lila
    "RF_FS": ("#fdf1e6", "#f0c08a"),    # pasztell narancs
}
REGIME_LABELS = {
    "RANGING": "Oldalazó → MeanReversion", "TRENDING": "Trendelő → TrendFollowing",
    "TRANSITIONAL": "Átmeneti → nincs kereskedés", "UNKNOWN": "Bemelegszik / ismeretlen",
}

# PyInstaller-lel becsomagolt .exe-ként futva a `__file__` egy ideiglenes kicsomagolási mappára
# mutatna (--onefile módban), NEM oda, ahol az .exe ténylegesen van -- ilyenkor a `terminals.json`-t
# az .exe MELLETT kell keresni (`sys.executable` könyvtára), különben a felhasználó szerkesztett
# configja sose találná meg a program. `sys.frozen` a szabványos PyInstaller-jelző erre.
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TERMINALS_CONFIG_PATH = os.path.join(_BASE_DIR, "terminals.json")

# --- Vizuális paletta (2026-09-06, "harmonikusabb, szebb felület" kérésre egységesítve) ---
WINDOW_BG = "#f6f8fa"     # halvány szürkéskék háttér
CARD_BG = "#ffffff"       # fehér "kártyák" a szürke háttéren
BORDER = "#d0d7de"
TEXT_MUTED = "#57606a"
TEXT_STRONG = "#1f2328"
GREEN = "#1a7f37"
GREEN_BG = "#e6f4ea"
RED = "#cf222e"
RED_BG = "#fdecea"
AMBER = "#9a6700"
AMBER_BG = "#fff8e6"

STATUS_COLORS = {"OK": GREEN, "STALE": AMBER, "HIBA": RED}
PROFIT_COLORS = {"pos": GREEN, "neg": RED, "zero": TEXT_MUTED}

PERIOD_LABELS = ("Ma", "Ez a hét", "Ez a hónap", "Ez az év")


def load_terminals_config():
    """`terminals.json`-t olvas be, ha létezik -- lásd `terminals.example.json` a formátumért.
    Ha nincs ilyen fájl, egyetlen "alapértelmezett" terminált ad vissza (path=None -> a Python
    MT5 API a gép/telepítés jelenleg elérhető alapértelmezett terminálját használja, ugyanaz a
    viselkedés, mint eddig)."""
    if os.path.isfile(TERMINALS_CONFIG_PATH):
        try:
            with open(TERMINALS_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            terminals = data.get("terminals", [])
            if terminals:
                return [
                    {
                        "name": t.get("name", t.get("path", "?")),
                        "path": t.get("path"),
                        "common_files_dir": t.get("common_files_dir") or DEFAULT_COMMON_FILES_DIR,
                    }
                    for t in terminals
                ]
        except (json.JSONDecodeError, OSError) as exc:
            print(f"⚠️ terminals.json beolvasása sikertelen ({exc}) -- single-terminál módra esik vissza.")
    return [{"name": "alapértelmezett", "path": None, "common_files_dir": DEFAULT_COMMON_FILES_DIR}]


def humanize_age(seconds):
    if seconds < 120:
        return f"{seconds:.0f} mp"
    minutes = seconds / 60
    if minutes < 120:
        return f"{minutes:.0f} perc"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} óra"
    return f"{hours / 24:.1f} nap"


def _lerp_color(c1, c2, t):
    """Két hex szín közti lineáris interpoláció (t=0 -> c1, t=1 -> c2) -- a komponens-kártyák
    "használati gyakoriság szerinti" heatmap-színezéséhez."""
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _rounded_rect_points(x1, y1, x2, y2, r):
    """Pontlista egy lekerekített téglalaphoz -- `create_polygon(..., smooth=True)`-mal együtt
    használva sima sarkú kártyát ad (szabványos Tkinter-trükk, nincs natív rounded-rect primitív)."""
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def period_start_times(now):
    today_start = datetime(now.year, now.month, now.day)
    week_start = today_start - timedelta(days=now.weekday())   # hétfő
    month_start = datetime(now.year, now.month, 1)
    year_start = datetime(now.year, 1, 1)
    return dict(zip(PERIOD_LABELS, (today_start, week_start, month_start, year_start)))


class HeartbeatDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RegimeFramework EA — dashboard")
        self.geometry("1140x760")
        self.configure(bg=WINDOW_BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.terminals = load_terminals_config()
        self.common_files_dirs = sorted({t["common_files_dir"] for t in self.terminals})
        self._mt5_connected_path = "__unset__"   # melyik terminálra vagyunk épp kapcsolódva

        self._setup_style()
        self._build_header()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        tab_status = tk.Frame(notebook, bg=WINDOW_BG)
        tab_summary = tk.Frame(notebook, bg=WINDOW_BG)
        tab_components = tk.Frame(notebook, bg=WINDOW_BG)
        notebook.add(tab_status, text="  Élő állapot  ")
        notebook.add(tab_summary, text="  Összesítés  ")
        notebook.add(tab_components, text="  Rezsim & komponensek  ")

        self._build_status_tab(tab_status)
        self._build_summary_tab(tab_summary)
        self._build_components_tab(tab_components)

        self.refresh_heartbeat()
        self.refresh_trades()
        self.refresh_summary()
        self.refresh_components()

    # ------------------------------------------------------------------ setup

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=WINDOW_BG, borderwidth=0)
        style.configure("TNotebook.Tab", font=("Segoe UI", 10), padding=(14, 8))
        style.configure("Treeview", rowheight=23, font=("Segoe UI", 9),
                         background=CARD_BG, fieldbackground=CARD_BG, borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                         background="#eaeef2", relief="flat")
        style.map("Treeview.Heading", background=[("active", "#dde3e8")])

    def _build_header(self):
        header = tk.Frame(self, bg=WINDOW_BG)
        header.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(header, text="RegimeFramework EA", font=("Segoe UI", 14, "bold"),
                 bg=WINDOW_BG, fg=TEXT_STRONG, anchor="w").pack(anchor="w")

        info_text = f"Terminálok: {', '.join(t['name'] for t in self.terminals)}"
        if len(self.common_files_dirs) > 1:
            info_text += f"  |  Common\\Files mappák: {', '.join(self.common_files_dirs)}"
        else:
            info_text += f"  |  Common\\Files mappa: {self.common_files_dirs[0]}"
        tk.Label(header, text=info_text, font=("Segoe UI", 9), fg=TEXT_MUTED, bg=WINDOW_BG,
                 anchor="w", wraplength=1100, justify="left").pack(anchor="w", pady=(2, 0))

        self.updated_label = tk.Label(header, text="", font=("Segoe UI", 9), fg=TEXT_MUTED,
                                       bg=WINDOW_BG, anchor="w")
        self.updated_label.pack(anchor="w", pady=(2, 0))

    def _card_frame(self, parent):
        outer = tk.Frame(parent, bg=BORDER)
        inner = tk.Frame(outer, bg=CARD_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer, inner

    # ------------------------------------------------------------- tab 1: élő állapot

    def _build_status_tab(self, parent):
        card_outer, card = self._card_frame(parent)
        card_outer.pack(fill="x", pady=(10, 8))
        tk.Label(card, text="EA-példányok állapota", font=("Segoe UI", 11, "bold"),
                 bg=CARD_BG, fg=TEXT_STRONG, anchor="w").pack(fill="x", padx=12, pady=(10, 6))

        hb_columns = ("fajl", "statusz", "kor", "rezsim_kesz", "poziciok",
                      "hibaszam", "utolso_hiba", "equity", "szabad_margin")
        hb_headings = {
            "fajl": "Fájl (szimbólum_magic)", "statusz": "Állapot", "kor": "Utolsó heartbeat kora",
            "rezsim_kesz": "Rezsim kész", "poziciok": "Nyitott poz.", "hibaszam": "Hibák",
            "utolso_hiba": "Utolsó hiba", "equity": "Equity", "szabad_margin": "Szabad margin",
        }
        hb_widths = {
            "fajl": 250, "statusz": 80, "kor": 120, "rezsim_kesz": 75, "poziciok": 75,
            "hibaszam": 55, "utolso_hiba": 200, "equity": 85, "szabad_margin": 95,
        }
        self.hb_tree = ttk.Treeview(card, columns=hb_columns, show="headings", height=7)
        for col in hb_columns:
            self.hb_tree.heading(col, text=hb_headings[col])
            self.hb_tree.column(col, width=hb_widths[col], anchor="w")
        self.hb_tree.pack(fill="x", padx=12, pady=(0, 4))
        for status, color in STATUS_COLORS.items():
            self.hb_tree.tag_configure(status, foreground=color)

        tk.Label(card, text="Hétvégén/piaci zárás idején a STALE állapot VÁRHATÓ, nem feltétlenül hiba.",
                 font=("Segoe UI", 8, "italic"), fg=TEXT_MUTED, bg=CARD_BG, anchor="w"
                 ).pack(fill="x", padx=12, pady=(0, 10))

        trade_card_outer, trade_card = self._card_frame(parent)
        trade_card_outer.pack(fill="both", expand=True, pady=(0, 4))
        trade_header = tk.Frame(trade_card, bg=CARD_BG)
        trade_header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(trade_header, text="Legutóbbi zárt trade-ek", font=("Segoe UI", 11, "bold"),
                 bg=CARD_BG, fg=TEXT_STRONG, anchor="w").pack(side="left")
        self.trade_summary_label = tk.Label(trade_header, text="", font=("Segoe UI", 9),
                                             fg=TEXT_MUTED, bg=CARD_BG, anchor="e")
        self.trade_summary_label.pack(side="right")

        trade_columns = ("terminal", "ido", "szimbolum", "magic", "irany", "volumen", "ar", "profit")
        trade_headings = {
            "terminal": "Terminál", "ido": "Zárás ideje", "szimbolum": "Szimbólum", "magic": "Magic",
            "irany": "Irány", "volumen": "Volumen", "ar": "Ár", "profit": "Profit ($)",
        }
        trade_widths = {
            "terminal": 100, "ido": 140, "szimbolum": 100, "magic": 65, "irany": 65, "volumen": 75,
            "ar": 90, "profit": 90,
        }
        self.trade_tree = ttk.Treeview(trade_card, columns=trade_columns, show="headings", height=13)
        for col in trade_columns:
            self.trade_tree.heading(col, text=trade_headings[col])
            self.trade_tree.column(col, width=trade_widths[col], anchor="w")
        self.trade_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for tag, color in PROFIT_COLORS.items():
            self.trade_tree.tag_configure(tag, foreground=color)

    # ------------------------------------------------------------- tab 2: összesítés

    def _build_summary_tab(self, parent):
        tk.Label(parent, text="Eredmény időszakonként (a jelenlegi teljes egyenleg %-ában)",
                 font=("Segoe UI", 10), fg=TEXT_MUTED, bg=WINDOW_BG, anchor="w"
                 ).pack(fill="x", pady=(10, 8))

        cards_row = tk.Frame(parent, bg=WINDOW_BG)
        cards_row.pack(fill="x")
        self.summary_cards = {}
        for label in PERIOD_LABELS:
            outer, card = self._card_frame(cards_row)
            outer.pack(side="left", fill="both", expand=True, padx=6)
            tk.Label(card, text=label, font=("Segoe UI", 10), fg=TEXT_MUTED, bg=CARD_BG
                     ).pack(pady=(16, 4))
            nominal_lbl = tk.Label(card, text="–", font=("Segoe UI", 22, "bold"),
                                    fg=TEXT_STRONG, bg=CARD_BG)
            nominal_lbl.pack()
            percent_lbl = tk.Label(card, text="–", font=("Segoe UI", 12), fg=TEXT_MUTED, bg=CARD_BG)
            percent_lbl.pack(pady=(2, 16))
            self.summary_cards[label] = (outer, card, nominal_lbl, percent_lbl)

        self.summary_note_label = tk.Label(
            parent, text="", font=("Segoe UI", 8, "italic"), fg=TEXT_MUTED, bg=WINDOW_BG, anchor="w",
        )
        self.summary_note_label.pack(fill="x", pady=(8, 10))

        detail_outer, detail_card = self._card_frame(parent)
        detail_outer.pack(fill="both", expand=True, pady=(0, 4))
        tk.Label(detail_card, text="Terminálonkénti bontás", font=("Segoe UI", 11, "bold"),
                 bg=CARD_BG, fg=TEXT_STRONG, anchor="w").pack(fill="x", padx=12, pady=(10, 6))

        detail_columns = ("terminal", "egyenleg") + tuple(f"nom_{p}" for p in PERIOD_LABELS) \
            + tuple(f"pct_{p}" for p in PERIOD_LABELS)
        self.detail_tree = ttk.Treeview(detail_card, columns=detail_columns, show="headings", height=6)
        self.detail_tree.heading("terminal", text="Terminál")
        self.detail_tree.column("terminal", width=110, anchor="w")
        self.detail_tree.heading("egyenleg", text="Egyenleg")
        self.detail_tree.column("egyenleg", width=90, anchor="w")
        for p in PERIOD_LABELS:
            self.detail_tree.heading(f"nom_{p}", text=f"{p} ($)")
            self.detail_tree.column(f"nom_{p}", width=85, anchor="w")
            self.detail_tree.heading(f"pct_{p}", text=f"{p} (%)")
            self.detail_tree.column(f"pct_{p}", width=70, anchor="w")
        self.detail_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for tag, color in PROFIT_COLORS.items():
            self.detail_tree.tag_configure(tag, foreground=color)

    # ------------------------------------------------------------- tab 3: rezsim & komponensek

    def _build_components_tab(self, parent):
        # --- naptár-figyelmeztető sáv (2026-09-07, "3 nappal előtte" kérés) -- csak akkor
        #     látszik, ha tényleg van közelgő ünnepnap valamelyik ismert szimbólumra ---
        self.calendar_banner = tk.Label(
            parent, font=("Segoe UI", 9, "bold"), anchor="w", padx=12, pady=8,
        )
        # induláskor rejtve -- refresh_components() mutatja meg, ha van mit jelezni

        regime_outer, regime_card = self._card_frame(parent)
        self.regime_card_outer = regime_outer   # referenciapont a naptár-sáv "before=" pakolásához
        regime_outer.pack(fill="x", pady=(10, 8))
        tk.Label(regime_card, text="Aktuális rezsim EA-példányonként", font=("Segoe UI", 11, "bold"),
                 bg=CARD_BG, fg=TEXT_STRONG, anchor="w").pack(fill="x", padx=12, pady=(10, 6))

        regime_columns = ("fajl", "szimbolum", "rezsim", "volatilitas", "kesz")
        regime_headings = {
            "fajl": "Fájl (szimbólum_magic)", "szimbolum": "Szimbólum", "rezsim": "Aktuális rezsim",
            "volatilitas": "Volatilitás", "kesz": "Rezsim-osztályozó kész",
        }
        regime_widths = {"fajl": 130, "szimbolum": 100, "rezsim": 300, "volatilitas": 100, "kesz": 140}
        self.regime_tree = ttk.Treeview(regime_card, columns=regime_columns, show="headings", height=6)
        for col in regime_columns:
            self.regime_tree.heading(col, text=regime_headings[col])
            self.regime_tree.column(col, width=regime_widths[col], anchor="w")
        self.regime_tree.pack(fill="x", padx=12, pady=(0, 12))

        components_outer, components_card = self._card_frame(parent)
        components_outer.pack(fill="both", expand=True, pady=(0, 4))
        comp_header = tk.Frame(components_card, bg=CARD_BG)
        comp_header.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(comp_header, text="Komponensek szerinti bontás — teljes történet",
                 font=("Segoe UI", 11, "bold"), bg=CARD_BG, fg=TEXT_STRONG, anchor="w").pack(side="left")
        self.components_note_label = tk.Label(comp_header, text="", font=("Segoe UI", 9),
                                               fg=TEXT_MUTED, bg=CARD_BG, anchor="e")
        self.components_note_label.pack(side="right")

        tk.Label(components_card,
                 text="A kártyák telítettsége a komponens saját trade-arányát mutatja "
                      "(minél sötétebb, annál gyakrabban kereskedett) -- minden komponens saját "
                      "pasztell-színcsaládban.",
                 font=("Segoe UI", 8, "italic"), fg=TEXT_MUTED, bg=CARD_BG, anchor="w"
                 ).pack(fill="x", padx=12, pady=(0, 6))

        self.components_canvas = tk.Canvas(components_card, bg=CARD_BG, highlightthickness=0, height=190)
        self.components_canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.components_canvas.bind("<Configure>", lambda e: self._draw_component_cards())
        self._last_component_stats = {}   # a legutóbbi lekérdezés eredménye -- resize-kor újrarajzoláshoz

    # ------------------------------------------------------------------ lifecycle

    def _on_close(self):
        try:
            mt5.shutdown()
        except Exception:
            pass
        self.destroy()

    def _connect(self, terminal):
        """Átkapcsol a megadott terminálra -- explicit shutdown+initialize, mert a Python MT5 API
        egyszerre csak EGY kapcsolatot tart. Ha `path` None, az aktuális gép alapértelmezett
        (jelenleg elérhető) terminálját használja."""
        if self._mt5_connected_path != terminal["path"]:
            try:
                mt5.shutdown()
            except Exception:
                pass
            ok = mt5.initialize(path=terminal["path"]) if terminal["path"] else mt5.initialize()
            self._mt5_connected_path = terminal["path"] if ok else "__unset__"
            return ok
        return True

    def _known_magics(self):
        magics = set()
        for d in self.common_files_dirs:
            for path in glob.glob(os.path.join(d, HEARTBEAT_PATTERN)):
                fields = parse_heartbeat(path)
                magic = fields.get("magic")
                if magic and magic.isdigit():
                    magics.add(int(magic))
        return magics

    # ------------------------------------------------------------------ refresh: heartbeat

    def refresh_heartbeat(self):
        self.hb_tree.delete(*self.hb_tree.get_children())

        paths = []
        for d in self.common_files_dirs:
            paths.extend(glob.glob(os.path.join(d, HEARTBEAT_PATTERN)))
        paths = sorted(set(paths))

        if not paths:
            self.hb_tree.insert("", "end", values=(
                "(nincs heartbeat-fájl -- fut-e az EA valamelyik charton?)", "", "", "", "", "", "", "", "",
            ))
        for path in paths:
            result = check_heartbeat(path)
            f = result["fields"]
            status = result["status"]
            tag = "HIBA" if "HIBA" in status else ("STALE" if status.startswith("STALE") else "OK")
            self.hb_tree.insert("", "end", values=(
                result["file"], status, humanize_age(result["age_seconds"]),
                f.get("classifier_ready", "?"), f.get("open_positions", "?"),
                str(result["error_count"]), f.get("last_error_msg", "") or "-",
                f.get("account_equity", "?"), f.get("account_margin_free", "?"),
            ), tags=(tag,))

        self.updated_label.configure(
            text=f"Utolsó frissítés: {time.strftime('%Y-%m-%d %H:%M:%S')}  ·  "
                 f"heartbeat: {HEARTBEAT_REFRESH_MS // 1000}mp  ·  "
                 f"trade-történet: {HISTORY_REFRESH_MS // 1000}mp  ·  "
                 f"összesítés: {SUMMARY_REFRESH_MS // 1000}mp"
        )
        self.after(HEARTBEAT_REFRESH_MS, self.refresh_heartbeat)

    # ------------------------------------------------------------------ refresh: trades

    def refresh_trades(self):
        self.trade_tree.delete(*self.trade_tree.get_children())
        magics = self._known_magics()

        if not magics:
            self.trade_summary_label.configure(text="Nincs ismert magic number (heartbeat-fájl) -- nincs mit szűrni.")
            self.after(HISTORY_REFRESH_MS, self.refresh_trades)
            return

        date_from = datetime.now() - timedelta(days=HISTORY_LOOKBACK_DAYS)
        date_to = datetime.now()

        all_rows = []
        unreachable = []
        for terminal in self.terminals:
            if not self._connect(terminal):
                unreachable.append(terminal["name"])
                continue
            deals = mt5.history_deals_get(date_from, date_to) or ()
            for d in deals:
                if d.entry == mt5.DEAL_ENTRY_OUT and d.magic in magics:
                    all_rows.append((terminal["name"], d))

        all_rows.sort(key=lambda row: row[1].time, reverse=True)
        shown = all_rows[:MAX_TRADES_SHOWN]

        total_profit = 0.0
        for terminal_name, d in shown:
            profit = d.profit + d.swap + d.commission
            total_profit += profit
            tag = "pos" if profit > 0 else ("neg" if profit < 0 else "zero")
            # JAVÍTÁS (2026-09-14) -- lásd dashboard_web.py azonos helyen lévő, részletes
            # magyarázatát: `d` itt a ZÁRÓ deal, aminek típusa a pozíció irányával ELLENTÉTES
            # (LONG záráshoz SELL kell, SHORT záráshoz BUY) -- a korábbi verzió fordítva volt.
            direction = "LONG" if d.type == mt5.DEAL_TYPE_SELL else "SHORT"
            self.trade_tree.insert("", "end", values=(
                terminal_name, datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M"),
                d.symbol, d.magic, direction, f"{d.volume:.2f}", f"{d.price:.2f}",
                f"{profit:+.2f}",
            ), tags=(tag,))

        summary = (f"{len(all_rows)} zárt trade az elmúlt {HISTORY_LOOKBACK_DAYS} napban "
                   f"(max {MAX_TRADES_SHOWN} kiírva)  ·  össz. nettó: {total_profit:+.2f}")
        if unreachable:
            summary += f"  ·  ⚠️ nem elérhető: {', '.join(unreachable)}"
        self.trade_summary_label.configure(text=summary)
        self.after(HISTORY_REFRESH_MS, self.refresh_trades)

    # ------------------------------------------------------------------ refresh: summary

    def _set_card(self, label, nominal, percent, currency="$"):
        _outer, card, nominal_lbl, percent_lbl = self.summary_cards[label]
        if nominal is None:
            nominal_lbl.configure(text="–", fg=TEXT_MUTED)
            percent_lbl.configure(text="nincs adat", fg=TEXT_MUTED)
            card.configure(bg=CARD_BG)
            for w in (nominal_lbl, percent_lbl):
                w.configure(bg=CARD_BG)
            return
        color, bg = (GREEN, GREEN_BG) if nominal > 0 else (RED, RED_BG) if nominal < 0 else (TEXT_MUTED, CARD_BG)
        nominal_lbl.configure(text=f"{nominal:+,.2f} {currency}", fg=color, bg=bg)
        percent_text = f"{percent:+.2f}%" if percent is not None else "n/a"
        percent_lbl.configure(text=percent_text, fg=color, bg=bg)
        card.configure(bg=bg)

    def refresh_summary(self):
        magics = self._known_magics()
        now = datetime.now()
        starts = period_start_times(now)

        if not magics:
            for label in PERIOD_LABELS:
                self._set_card(label, None, None)
            self.summary_note_label.configure(text="Nincs ismert magic number (heartbeat-fájl) -- nincs mit összesíteni.")
            self.detail_tree.delete(*self.detail_tree.get_children())
            self.after(SUMMARY_REFRESH_MS, self.refresh_summary)
            return

        date_from = now - timedelta(days=SUMMARY_LOOKBACK_DAYS)
        per_terminal = []   # (name, balance, {label: nominal})
        unreachable = []

        for terminal in self.terminals:
            if not self._connect(terminal):
                unreachable.append(terminal["name"])
                continue
            info = mt5.account_info()
            balance = info.balance if info else None
            deals = mt5.history_deals_get(date_from, now) or ()
            closing = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT and d.magic in magics]

            nominal_by_period = {}
            for label, start in starts.items():
                start_ts = start.timestamp()
                nominal_by_period[label] = sum(
                    d.profit + d.swap + d.commission for d in closing if d.time >= start_ts
                )
            per_terminal.append((terminal["name"], balance, nominal_by_period))

        # --- kártyák: mindent terminálon átívelő összesítés ---
        total_balance = sum(b for _, b, _ in per_terminal if b is not None) or None
        self.detail_tree.delete(*self.detail_tree.get_children())
        for label in PERIOD_LABELS:
            combined_nominal = sum(n[label] for _, _, n in per_terminal)
            combined_percent = (combined_nominal / total_balance * 100) if total_balance else None
            self._set_card(label, combined_nominal, combined_percent)

        for name, balance, nominal_by_period in per_terminal:
            row_values = [name, f"{balance:,.2f}" if balance is not None else "n/a"]
            for label in PERIOD_LABELS:
                nominal = nominal_by_period[label]
                pct = (nominal / balance * 100) if balance else None
                row_values.append(f"{nominal:+.2f}")
            for label in PERIOD_LABELS:
                nominal = nominal_by_period[label]
                pct = (nominal / balance * 100) if balance else None
                row_values.append(f"{pct:+.2f}%" if pct is not None else "n/a")
            today_nominal = nominal_by_period["Ma"]
            tag = "pos" if today_nominal > 0 else ("neg" if today_nominal < 0 else "zero")
            self.detail_tree.insert("", "end", values=tuple(row_values), tags=(tag,))

        note = (f"A %-ok a jelenlegi teljes egyenleghez viszonyítva ({SUMMARY_LOOKBACK_DAYS} napos "
                f"lekérdezési ablak, hétfői hét-kezdéssel).")
        if unreachable:
            note += f"  ⚠️ nem elérhető: {', '.join(unreachable)}"
        self.summary_note_label.configure(text=note)
        self.after(SUMMARY_REFRESH_MS, self.refresh_summary)

    # ------------------------------------------------------------------ refresh: rezsim & komponensek

    def _component_stats(self, magics, date_from):
        """Komponensenkénti (RF_MR/RF_TF/RF_LHC/RF_FS) trade-statisztika a TELJES elérhető
        történetre. A NYITÓ (DEAL_ENTRY_IN) deal comment-jéből olvassuk a tag-et, position_id
        alapján párosítva a záró (DEAL_ENTRY_OUT) deal-lel -- NEM a záró deal saját comment-jéből,
        mert egy bróker-oldali natív SL/TP-zárás felülírhatja azt (pl. "[sl]"-re) a mi egyedi
        tag-ünk helyett. Ez a párosítás emiatt megbízhatóbb, mint a záró deal comment-jét közvetlenül
        nézni."""
        stats = {}
        unreachable = []
        for terminal in self.terminals:
            if not self._connect(terminal):
                unreachable.append(terminal["name"])
                continue
            deals = mt5.history_deals_get(date_from, datetime.now()) or ()
            entry_tag_by_position = {
                d.position_id: (d.comment or "?") for d in deals
                if d.magic in magics and d.entry == mt5.DEAL_ENTRY_IN
            }
            for d in deals:
                if d.magic not in magics or d.entry != mt5.DEAL_ENTRY_OUT:
                    continue
                tag = entry_tag_by_position.get(d.position_id, d.comment or "?")
                net = d.profit + d.swap + d.commission
                s = stats.setdefault(tag, {"count": 0, "wins": 0, "gross_profit": 0.0,
                                            "gross_loss": 0.0, "net": 0.0})
                s["count"] += 1
                s["net"] += net
                if net > 0:
                    s["wins"] += 1
                    s["gross_profit"] += net
                elif net < 0:
                    s["gross_loss"] += -net
        return stats, unreachable

    def _draw_component_cards(self):
        canvas = self.components_canvas
        canvas.delete("all")
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 40 or height < 40:
            return   # meg nincs layout-olva (pl. első hívás konfiguráció előtt)

        stats = self._last_component_stats
        total_count = sum(s["count"] for s in stats.values()) or 0
        pad = 10
        gap = 10
        n = len(COMPONENT_ORDER)
        card_w = (width - 2 * pad - (n - 1) * gap) / n
        card_h = height - 2 * pad
        y1 = pad
        y2 = pad + card_h
        knob_xs = []   # a szomszédos kártyák közti "összekapcsoló gomb" x-koordinátái -- MÁSODIK
                        # körben rajzoljuk ki, hogy a rákövetkező kártya polygon-ja ne fedje le

        # --- 1. kör: MINDEN kártya-test + szöveg ---
        for i, tag in enumerate(COMPONENT_ORDER):
            x1 = pad + i * (card_w + gap)
            x2 = x1 + card_w

            s = stats.get(tag, {"count": 0, "wins": 0, "gross_profit": 0.0, "gross_loss": 0.0, "net": 0.0})
            share = (s["count"] / total_count) if total_count else 0.0
            pale, rich = COMPONENT_COLORS[tag]
            fill = _lerp_color(pale, rich, share)

            points = _rounded_rect_points(x1, y1, x2, y2, 14)
            canvas.create_polygon(points, smooth=True, fill=fill, outline=BORDER, width=1)

            cx = (x1 + x2) / 2
            label = COMPONENT_LABELS.get(tag, tag)
            canvas.create_text(cx, y1 + 20, text=label, font=("Segoe UI", 10, "bold"), fill=TEXT_STRONG)

            if s["count"] == 0:
                canvas.create_text(cx, y1 + card_h / 2 + 6, text="nincs adat",
                                    font=("Segoe UI", 9, "italic"), fill=TEXT_MUTED)
            else:
                win_rate = s["wins"] / s["count"] * 100
                pf = (s["gross_profit"] / s["gross_loss"]) if s["gross_loss"] > 0 else float("inf")
                pf_text = f"{pf:.2f}" if pf != float("inf") else "∞"
                net_color = GREEN if s["net"] > 0 else (RED if s["net"] < 0 else TEXT_MUTED)
                canvas.create_text(cx, y1 + 46, text=f"{s['count']} trade  ·  {share * 100:.0f}% részesedés",
                                    font=("Segoe UI", 9), fill=TEXT_STRONG)
                canvas.create_text(cx, y1 + 66, text=f"Találat: {win_rate:.0f}%   PF: {pf_text}",
                                    font=("Segoe UI", 9), fill=TEXT_STRONG)
                canvas.create_text(cx, y1 + 90, text=f"Nettó: {s['net']:+,.2f}",
                                    font=("Segoe UI", 11, "bold"), fill=net_color)

            if i < n - 1:
                knob_xs.append(x2 + gap / 2)

        # --- 2. kör: "puzzle-összekapcsoló" gombok a kártyák határain, MINDEN kártya-test FÖLÉ
        #     rajzolva (2026-09-07, felhasználói design-ötlet, egyszerűsítve valódi kirakó-fogazás
        #     helyett) -- ha ez a kör a kártyákkal EGYÜTT futna, a következő kártya polygon-ja
        #     lefedné az előző gomb jobb felét (ezt észrevettük egy próba-screenshoton). ---
        knob_y = (y1 + y2) / 2
        for knob_x in knob_xs:
            canvas.create_oval(knob_x - 9, knob_y - 9, knob_x + 9, knob_y + 9,
                                fill=CARD_BG, outline=BORDER, width=1)

    def refresh_components(self):
        # --- 1. rész: aktuális rezsim heartbeat-fájlokból (olcsó, csak fájlolvasás) ---
        self.regime_tree.delete(*self.regime_tree.get_children())
        symbols_seen = set()
        paths = []
        for d in self.common_files_dirs:
            paths.extend(glob.glob(os.path.join(d, HEARTBEAT_PATTERN)))
        for path in sorted(set(paths)):
            fields = parse_heartbeat(path)
            symbol = fields.get("symbol", "?")
            symbols_seen.add(symbol)
            regime = fields.get("current_regime", "?")
            vol = fields.get("current_vol_band", "?")
            ready = fields.get("classifier_ready", "?")
            regime_text = REGIME_LABELS.get(regime, regime)
            self.regime_tree.insert("", "end", values=(
                os.path.basename(path), symbol, regime_text, vol, ready,
            ))

        # --- 2. rész: naptár-figyelmeztetés a következő N napra (2026-09-07 kérés) ---
        try:
            calendar = load_calendar()
            warnings = []
            today = datetime.now().date()
            for offset in range(0, CALENDAR_WARNING_DAYS_AHEAD + 1):
                check_date = today + timedelta(days=offset)
                for symbol in sorted(symbols_seen):
                    if symbol == "?":
                        continue
                    if is_market_holiday(symbol, check_date, calendar):
                        when = "MA" if offset == 0 else f"{offset} nap múlva ({check_date.isoformat()})"
                        warnings.append(f"{symbol}: piaci ünnepnap {when}")
            if warnings:
                self.calendar_banner.configure(
                    text="⚠️  " + "   ·   ".join(warnings),
                    bg=AMBER_BG, fg=AMBER,
                )
                if not self.calendar_banner.winfo_ismapped():
                    self.calendar_banner.pack(fill="x", pady=(10, 0), before=self.regime_card_outer)
            else:
                self.calendar_banner.pack_forget()
        except Exception as exc:   # a naptár-fájl hiánya/hibája ne akassza meg a teljes dashboard-ot
            self.calendar_banner.configure(text=f"⚠️ Naptár beolvasási hiba: {exc}", bg=AMBER_BG, fg=AMBER)
            if not self.calendar_banner.winfo_ismapped():
                self.calendar_banner.pack(fill="x", pady=(10, 0))

        # --- 3. rész: komponens-bontás (MT5-lekérdezés, "teljes történet") ---
        magics = self._known_magics()
        if magics:
            date_from = datetime.now() - timedelta(days=COMPONENTS_LOOKBACK_DAYS)
            stats, unreachable = self._component_stats(magics, date_from)
            self._last_component_stats = stats
            total = sum(s["count"] for s in stats.values())
            note = f"{total} zárt trade összesen (kb. {COMPONENTS_LOOKBACK_DAYS // 365} éves ablak)"
            if unreachable:
                note += f"  ·  ⚠️ nem elérhető: {', '.join(unreachable)}"
            self.components_note_label.configure(text=note)
        else:
            self._last_component_stats = {}
            self.components_note_label.configure(text="Nincs ismert magic number -- nincs mit összesíteni.")
        self._draw_component_cards()

        self.after(COMPONENTS_REFRESH_MS, self.refresh_components)


def main():
    app = HeartbeatDashboard()
    app.mainloop()


if __name__ == "__main__":
    main()
