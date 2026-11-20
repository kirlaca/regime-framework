"""
2. RÉTEG — MarketConditionClassifier: trend x volatilitás rács, gördülő percentilis-rangon alapulva.

Ellentétben a SessionPhaseClassifier-rel (instrumentum-csoportos konfig), ez UNIVERZÁLIS — a
gördülő percentilis-rang transzformáció eredendően instrumentum-független, amit a
research/market_condition_exploration.py mérése mind az 5 jelölt indexen megerősített: egyik
cella sem ritka (min. 12.3%), a perzisztencia (medián 8 bar) és a stabilitás (félidők közötti
eltérés <=2.2 pont) gyakorlatilag azonos volt mindenhol.

FONTOS, MÉG NYITOTT PONT (lásd PLAN.md 0.1, MT5 portolhatóság): a `classify_series()` batch
(pandas .rolling()) implementáció — backteszthez/validációhoz jó, de élő kereskedéshez egy
gördülő puffer alapú, bar-onkénti streaming verzió kell majd. Ezt SZÁNDÉKOSAN nem építjük meg
most, amíg nincs kész `core/engine.py`, ami ténylegesen igényelné (build-sorrend 6. lépése).
"""

import numpy as np
import pandas as pd

from regime_framework.core.indicators import compute_adx, compute_simple_atr
from regime_framework.core.types import ValidationReport

# lásd PLAN.md 2.2 — a research script ugyanezekkel az értékekkel mérte be a rácsot
ROLLING_WINDOW_BARS = 60 * 144   # ~60 kereskedési nap M10-en (144 bar/nap)
TREND_CUTS = (0.33, 0.67)
MIN_CELL_FREQUENCY_PCT = 5.0
MIN_MEDIAN_RUN_LENGTH = 3


class MarketConditionClassifier:
    def __init__(self, rolling_window_bars=ROLLING_WINDOW_BARS, trend_cuts=TREND_CUTS):
        self.rolling_window_bars = rolling_window_bars
        self.trend_cuts = trend_cuts

    def classify_series(self, df):
        """A teljes df-hez hozzáadja a 'trend_band'/'vol_band' oszlopokat (gördülő, look-ahead-
        mentes percentilis-rang alapján — csak a bar-ig visszamenő adatot használja). Az első
        rolling_window_bars sor kiesik (nincs elég historikus adat a rangsoroláshoz)."""
        df = df.copy()
        df['atr'] = compute_simple_atr(df)
        df['adx'] = compute_adx(df)
        df.dropna(subset=['atr', 'adx'], inplace=True)
        df.reset_index(drop=True, inplace=True)

        df['vol_percentile'] = df['atr'].rolling(
            window=self.rolling_window_bars, min_periods=self.rolling_window_bars).rank(pct=True)
        df['trend_percentile'] = df['adx'].rolling(
            window=self.rolling_window_bars, min_periods=self.rolling_window_bars).rank(pct=True)
        df.dropna(subset=['vol_percentile', 'trend_percentile'], inplace=True)
        df.reset_index(drop=True, inplace=True)

        df['trend_band'] = pd.cut(
            df['trend_percentile'],
            bins=[-0.01, self.trend_cuts[0], self.trend_cuts[1], 1.01],
            labels=['RANGING', 'TRANSITIONAL', 'TRENDING'],
        )
        df['vol_band'] = np.where(df['vol_percentile'] < 0.5, 'LOW', 'HIGH')
        return df

    def validate(self, df):
        """Cella-gyakoriság + perzisztencia ellenőrzés — lásd PLAN.md 0. Cél 1-2. pontja: a
        rezsim-osztályozó önállóan tesztelhető, a validáció a szerves része, nem külső script."""
        classified = self.classify_series(df)
        report = ValidationReport(component_name="MarketConditionClassifier")
        report.notes['n_bars'] = len(classified)

        if len(classified) < 1000:
            report.warnings.append(f"Túl kevés bar maradt a gördülő ablak után ({len(classified)}).")
            return report

        total = len(classified)
        cell_counts = classified.groupby(['trend_band', 'vol_band'], observed=True).size()
        report.notes['cell_frequency_pct'] = {
            f"{t}/{v}": round(c / total * 100, 1) for (t, v), c in cell_counts.items()
        }
        rare_cells = [k for k, v in report.notes['cell_frequency_pct'].items() if v < MIN_CELL_FREQUENCY_PCT]
        if rare_cells:
            report.warnings.append(f"Ritka cellák (<{MIN_CELL_FREQUENCY_PCT}%): {rare_cells}")

        run_id = (classified['trend_band'] != classified['trend_band'].shift()).cumsum()
        run_lengths = classified.groupby(run_id).size()
        median_run = float(run_lengths.median())
        report.notes['trend_band_median_run_length'] = median_run
        if median_run < MIN_MEDIAN_RUN_LENGTH:
            report.warnings.append(
                f"Rövid futamhossz (medián {median_run:.0f} bar < {MIN_MEDIAN_RUN_LENGTH}) — "
                f"a trend-sáv túl gyakran vált, hiszterézis/simítás kellhet."
            )

        return report
