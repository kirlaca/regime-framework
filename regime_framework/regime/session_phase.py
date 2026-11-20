"""
1. RÉTEG — SessionPhaseClassifier: naptár-vezérelt, ár-független session-fázis besorolás.

A határok KÉZZEL karbantartott, instrumentum-csoportos konfigban élnek (lásd PLAN.md 2.1 és a
"7. Nyitott kérdések" DÖNTÉS pontja) — a `research/session_phase_exploration.py` mérés + két-félidős
stabilitás-ellenőrzés eredménye alapján feltöltve. Csak azokat a fázisokat definiáljuk, amikre van
tényleges empirikus alapunk (OPENING_RANGE mindhárom csoportnál, ROLLOVER csak az EU csoportnál,
ahol valós spread-tágulást mértünk) — nem találgatunk PRE_CLOSE/OFF_HOURS határt evidencia nélkül;
minden más óra alapértelmezetten CORE_SESSION.

A "core" órák mindkét félidőben megjelentek a stabilitás-vizsgálatban (a fázis biztos része), a
"buffer" órák csak az egyikben (bizonytalanabb szél) — mindkettő OPENING_RANGE-nek számít, csak
megkülönböztetve dokumentálva, hogy tudjuk, melyik mennyire megbízható.
"""

import numpy as np

from regime_framework.core.indicators import compute_simple_atr
from regime_framework.core.types import ValidationReport

# lásd PLAN.md 2.1 táblázatait (session-alakok + stabilitás-eredmények)
GROUPS = {
    "US": {
        # US30Cash#/US400Cash#/US2000Cash# hozzáadva 2026-08-19 (felhasználói kör-bővítés) — ezekre
        # MÉG NEM futott le a research/session_phase_exploration.py mérés+stabilitás-ellenőrzés,
        # az óra-határok itt az US100/US500 mérésének ÁTVÉTELE (feltételezés: ugyanaz a tőzsdei
        # nyitás/session-szerkezet, mivel mind US-index). Ha valaha újra bekötnénk a
        # SessionPhaseClassifier-t komponens-kapuzásra, ezt előbb önállóan validálni kellene rájuk.
        "symbols": {"US100Cash#", "US500Cash#", "US30Cash#", "US400Cash#", "US2000Cash#"},
        "opening_range_core": {17, 18, 19, 20},
        "opening_range_buffer": {21, 22},
        "rollover": set(),   # nincs rá empirikus bizonyíték a havi átlagban
    },
    "JP": {
        "symbols": {"JP225Cash#"},
        "opening_range_core": {3, 4},
        "opening_range_buffer": {5, 18},
        "rollover": set(),
    },
    "EU": {
        "symbols": {"GER40Cash#", "EU50Cash#"},
        "opening_range_core": {11, 12, 17, 18},
        "opening_range_buffer": set(),   # tökéletes stabilitás, nincs bizonytalan szél
        "rollover": {23},   # GER40: 2.06->8.08, EU50: 1.65->5.66 — valós, mért spread-ugrás
    },
}


class SessionPhaseClassifier:
    """Egy adott szimbólumhoz tartozó session-fázis besorolás. `classify()` a hot path-on fut
    (bar-onként), `validate()` a kutatási/ellenőrzési oldalon — lásd PLAN.md 0. Cél 1-2. pontja:
    mindkettő önállóan tesztelhető, a validáció a komponens/osztályozó szerves része."""

    def __init__(self, symbol):
        self.symbol = symbol
        self.group_name, self._group = self._resolve_group(symbol)

    @staticmethod
    def _resolve_group(symbol):
        for name, group in GROUPS.items():
            if symbol in group["symbols"]:
                return name, group
        known = ", ".join(sorted(s for g in GROUPS.values() for s in g["symbols"]))
        raise ValueError(
            f"Nincs session-fázis konfig ehhez a szimbólumhoz: {symbol!r}. "
            f"Ismert szimbólumok: {known}. Bővítsd a GROUPS szótárat, miután lefuttattad rá a "
            f"research/session_phase_exploration.py mérést."
        )

    def classify(self, hour, minute=0):
        """hour: 0-23 (szerveridő). minute egyelőre nincs használva — a mérésünk óra-felbontású
        volt, a perc-szintű finomítás egy jövőbeli, célzottabb mérés után kerülhet be."""
        if hour in self._group["rollover"]:
            return "ROLLOVER"
        if hour in self._group["opening_range_core"] or hour in self._group["opening_range_buffer"]:
            return "OPENING_RANGE"
        return "CORE_SESSION"

    def validate(self, df):
        """Visszaméri a saját df-en: az OPENING_RANGE-nek besorolt órák ATR-je ténylegesen
        magasabb-e, mint a CORE_SESSION óráké — ha nem, a konfig nem illik erre az adatsorra
        (pl. rossz szimbólumhoz társítottuk, vagy a mintázat időközben megváltozott)."""
        df = df.copy()
        df['hour'] = df['time'].dt.hour
        df['atr'] = compute_simple_atr(df)
        df.dropna(subset=['atr'], inplace=True)
        df['phase'] = df['hour'].apply(self.classify)

        report = ValidationReport(component_name=f"SessionPhaseClassifier[{self.group_name}/{self.symbol}]")
        report.notes['n_bars'] = len(df)

        phase_avg = df.groupby('phase')['atr'].mean()
        report.notes['phase_avg_atr'] = phase_avg.to_dict()

        opening_avg = phase_avg.get("OPENING_RANGE", float("nan"))
        core_avg = phase_avg.get("CORE_SESSION", float("nan"))

        if np.isnan(opening_avg) or np.isnan(core_avg):
            report.warnings.append(
                "Hiányzó fázis-adat — nem volt elég bar mindkét fázisban az összevetéshez."
            )
        elif opening_avg <= core_avg:
            report.warnings.append(
                f"Az OPENING_RANGE átlagos ATR-je ({opening_avg:.4f}) NEM magasabb a CORE_SESSION-"
                f"nél ({core_avg:.4f}) ezen az adatsoron — a klasszifikáció nem tükrözi a várt "
                f"mintázatot, a konfigot felül kellene vizsgálni."
            )
        else:
            report.notes['opening_vs_core_ratio'] = opening_avg / core_avg

        if self._group["rollover"]:
            rollover_avg_spread = df.loc[df['phase'] == 'ROLLOVER', 'spread_price'].mean()
            core_avg_spread = df.loc[df['phase'] == 'CORE_SESSION', 'spread_price'].mean()
            if not np.isnan(rollover_avg_spread) and not np.isnan(core_avg_spread):
                report.notes['rollover_vs_core_spread_ratio'] = rollover_avg_spread / core_avg_spread
                if rollover_avg_spread <= core_avg_spread:
                    report.warnings.append(
                        f"A ROLLOVER átlagos spread-je ({rollover_avg_spread:.4f}) NEM magasabb a "
                        f"CORE_SESSION-nél ({core_avg_spread:.4f}) — a rollover-feltételezés nem "
                        f"igazolódott ezen az adatsoron."
                    )

        return report
