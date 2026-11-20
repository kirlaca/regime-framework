"""
Közös adatosztályok, amikre a rezsim-osztályozók és a stratégia-komponensek egyaránt támaszkodnak.

Szándékosan minimálisak — csak azt tartalmazzák, amire a session-fázis empirikus méréséhez és az
első osztályozó/komponens megírásához ténylegesen szükség lesz. Bővül, ahogy a build sorrend (lásd
PLAN.md 6. pont) előrehalad; nem előre teljes, "kitalált" interfész.
"""

from dataclasses import dataclass, field
from datetime import date as date_type


@dataclass
class RegimeState:
    """Egy bar besorolása a kétrétegű piaci-állapot rácsba.
    trend_band/vol_band None, ha a session_phase eleve nem kereskedhető (pl. OFF_HOURS) —
    ilyenkor a 2. réteg (MarketConditionClassifier) nem is fut le arra a bar-ra."""
    session_phase: str            # "OFF_HOURS" | "OPENING_RANGE" | "CORE_SESSION" | "PRE_CLOSE" | "ROLLOVER"
    trend_band: str | None = None   # "RANGING" | "TRANSITIONAL" | "TRENDING"
    vol_band: str | None = None     # "LOW" | "HIGH"


@dataclass
class BarContext:
    """Egy feldolgozott bar minden adata, amit egy komponens vagy osztályozó igényelhet."""
    time: object            # pandas.Timestamp — nem importáljuk ide a pandas-t típusfüggőség miatt
    open: float
    high: float
    low: float
    close: float
    hour: int
    minute: int
    day_of_week: int
    date: date_type
    regime: RegimeState | None = None
    indicators: dict = field(default_factory=dict)   # pl. {'atr': ..., 'ema_center': ..., 'adx': ...}
    # — komponensenként eltérő indikátor-igény, ezért általános dict, nem fix mezők.


@dataclass
class Signal:
    """Egy komponens belépési döntése."""
    direction: str                  # "LONG" | "SHORT"
    sl_price: float
    tp_price: float | None = None    # None = trailing-stop jellegű, nincs fix TP


@dataclass
class Position:
    """Egy nyitott pozíció állapota — ezt adja át a motor (később) vagy a saját validate() a
    check_exit()-nek."""
    pos_type: str            # "LONG" | "SHORT"
    entry_price: float
    entry_date: date_type
    sl_price: float
    tp_price: float | None = None
    extra: dict = field(default_factory=dict)   # komponensenként eltérő mutálható állapot,
    # pl. trailing-stop "trend_extreme" — lásd BarContext.indicators ugyanerről a mintáról.


@dataclass
class ExitDecision:
    """Egy komponens kilépési döntése — check_exit() adja vissza, ha a pozíciót zárni kell."""
    exit_price: float
    reason: str               # "SL" | "TP" | ...


@dataclass
class ValidationReport:
    """Minden komponens/osztályozó validate() hívásának egységes kimeneti formátuma —
    így a validation/report.py egy közös módon tudja megjeleníteni bármelyiket."""
    component_name: str
    trade_count: int = 0
    win_rate: float = 0.0
    profit_factor: float = float("nan")
    total_pnl: float = 0.0
    warnings: list[str] = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def is_reliable(self, min_trades: int = 30) -> bool:
        """A projekt korábbi tanulsága (MIN_TRADES_FOR_VALID_SCORE): 30 trade alatt a mérés
        statisztikailag nem megbízható — lásd a Turnaround Tuesday validáció esetét."""
        return self.trade_count >= min_trades

    def summary_line(self) -> str:
        reliability = "megbízható" if self.is_reliable() else "KEVÉS MINTA — óvatosan kezelendő"
        return (f"{self.component_name}: {self.trade_count} trade | win-rate {self.win_rate:.1f}% | "
                f"profit factor {self.profit_factor:.2f} | össz. PnL {self.total_pnl:.2f} | {reliability}")
