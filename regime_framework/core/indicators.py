"""
Egyszerű, a repo eddigi konvenciójával konzisztens (NEM Wilder-simított) indikátor-segédek,
amikre több modul is támaszkodik — hogy ne legyen duplikált, egymástól idővel eltérő
implementáció a research/ és a regime/ oldalon.
"""

import numpy as np
import pandas as pd


def compute_simple_atr(df, period=14):
    """True Range egyszerű mozgóátlaga — ugyanaz a módszer, mint a main_optuna_anomaly.py-ban.
    Szándékosan NEM a Wilder-simítás (mint pl. MQL5 iATR()), mert az más eredményt adna —
    lásd PLAN.md 0.1 (MT5 portolhatóság) 2. szabálya: az indikátor-számítási módot dokumentálni
    kell, mert az MQL5 beépített függvényei eltérhetnek."""
    tr = np.maximum(
        df['high'] - df['low'],
        np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1)))
    )
    return tr.rolling(window=period).mean()


def compute_adx(df, period=14):
    """Egyszerűsített ADX — a main_optuna_anomaly.py-ban már egyszer megtalált és javított
    index-illesztési hibát elkerülve: kizárólag numpy tömbökön dolgozik, sima np.ndarray-t ad
    vissza (nem pandas Series-t), hogy ne forduljon elő a korábbi NaN-bug nem 0-tól induló
    (pl. fold-szelet) DataFrame-eken. Szándékosan egyszerű mozgóátlag, nem Wilder-simítás —
    lásd compute_simple_atr docstringje ugyanerről."""
    high = df['high'].to_numpy()
    low = df['low'].to_numpy()
    close = df['close'].to_numpy()

    up_move = np.diff(high, prepend=np.nan)
    down_move = -np.diff(low, prepend=np.nan)

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = np.roll(close, 1)
    prev_close[0] = np.nan
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))

    tr_avg = pd.Series(tr).rolling(period).mean().to_numpy()
    plus_di = 100 * (pd.Series(plus_dm).rolling(period).mean().to_numpy() / tr_avg)
    minus_di = 100 * (pd.Series(minus_dm).rolling(period).mean().to_numpy() / tr_avg)

    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = pd.Series(dx).rolling(period).mean().to_numpy()
    return adx


def compute_rsi(df, period=14):
    """Egyszerű (NEM Wilder-simított) RSI — ugyanaz a konvenció, mint a compute_simple_atr/
    compute_adx-nél: az MQL5 iRSI() Wilder-simítást használ, ami más eredményt adna, ezért ezt
    dokumentálni kell portoláskor (lásd PLAN.md 0.1, MT5 portolhatóság 2. szabálya)."""
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
