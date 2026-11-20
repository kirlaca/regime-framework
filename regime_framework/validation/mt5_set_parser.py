"""
validation/mt5_set_parser.py -- MT5 `.set` preset fájlok beolvasása Optuna trial-paraméter dict-té.

Azért kellett, mert a `generate_live_baseline.py` (1. fázis, lásd PLAN.md 7. pont) eredetileg
KÉZZEL átmásolt Python dict-tel indult (`USTEC_LIVE_PARAMS`) -- ez a modul-docstringben explicit
"tudatosan el nem hárított korlátként" volt dokumentálva ("ha a .set később változik, ezt a
dict-et is kézzel frissíteni kell"). Ez a parser megszünteti azt a korlátot: a baseline-generátor
mostantól KÖZVETLENÜL a terminál `.set` fájljából olvassa a paramétereket, minden futtatáskor --
nincs elavulás-kockázat, nincs elgépelés-kockázat.

Formátum: KÉT eltérő kódolással is találkoztunk élesben, ugyanabban a projektben --
- BOM-mal (0xFF 0xFE) jelzett UTF-16LE (a `USTEC.set`/`US500.set`/`US30.set`/`DE40.set`/
  `AUS200.set`/`SA40.set` -- mind a Python `.set`-generátor scriptek termékei, lásd
  `docs/BROKER_MIGRATION_DECISION.md` 4.2 pont).
- BOM NÉLKÜLI sima UTF-8 (a régebbi, MetaEditor "Save as .set" úton keletkezett fájlok, pl.
  `RegimeFramework_EA_US100Cash.set`/`..._US500Cash.set`/`..._US30Cash.set` -- ezeket ELSŐRE
  UTF-16LE-ként próbáltam beolvasni, ami csendben értelmetlen, CJK-tartományba eső karaktereket
  adott vissza -- NEM hibát dobott, csak rossz adatot -- ezért itt explicit BOM-detektálás
  szükséges, nem szabad egyetlen kódolást feltételezni).

A `;`-vel kezdődő sorok kommentek, a többi `InpXxx=érték` alakú. Hangosan hibázunk, ha egyik
ismert kódolás sem illeszkedik -- inkább álljon meg a script, mint hogy csendben rossz
paramétereket adjon vissza egy ÉLŐ kereskedési EA referencia-generálásához.

Az `Inp*` -> Optuna trial-kulcs fordítás (`SET_KEY_TO_TRIAL_KEY`) STATIKUS, mert az EA `Inp*`
input-nevei (`RegimeFramework_EA.mq5`/`RegimeFramework_EA_ICMarkets.mq5`) és a Python trial-kulcsok
(`components/*.py` `suggest_params()`) egymástól függetlenül, kézzel elnevezett, stabil azonosítók
-- nincs belőlük programmatikusan levezethető megfeleltetés, ezért a 16 bejegyzés explicit fel van
sorolva, keresztellenőrizve `components/*.py` `suggest_params()`-ával (típus: int vagy float).
"""

from pathlib import Path

# Inp* (MQL5, .set fájl) -> (trial-kulcs, típus) -- forrás: components/*.py suggest_params()
# int: mr_ema_period, tf_bollinger_period, lhc_min_trend_bars, fs_hold_bars (trial.suggest_int)
# float: minden más (trial.suggest_float)
SET_KEY_TO_TRIAL_KEY = {
    "InpMrEmaPeriod": ("mr_ema_period", int),
    "InpMrMultiplier": ("mr_mr_multiplier", float),
    "InpMrSlMultiplier": ("mr_sl_multiplier", float),
    "InpMrRiskRewardRatio": ("mr_risk_reward_ratio", float),
    "InpTfFastEmaDays": ("tf_fast_ema_days", float),
    "InpTfSlowEmaDays": ("tf_slow_ema_days", float),
    "InpTfSlAtrMultiplier": ("tf_sl_atr_multiplier", float),
    "InpTfTrailAtrMultiplier": ("tf_trail_atr_multiplier", float),
    "InpTfRsiLongMin": ("tf_rsi_long_min", float),
    "InpTfRsiShortMax": ("tf_rsi_short_max", float),
    "InpTfBollingerPeriod": ("tf_bollinger_period", int),
    "InpTfBollingerK": ("tf_bollinger_k", float),
    "InpLhcSlAtrMultiplier": ("lhc_sl_atr_multiplier", float),
    "InpLhcMinTrendBars": ("lhc_min_trend_bars", int),
    "InpFsSlAtrMultiplier": ("fs_sl_atr_multiplier", float),
    "InpFsHoldBars": ("fs_hold_bars", int),
}


def _decode_set_file_bytes(path, raw_bytes):
    """Két ismert kódolás közül választ -- lásd modul-docstring. BOM-mal egyértelmű az UTF-16;
    BOM nélkül UTF-8-at próbálunk (`errors="strict"`, hogy egy véletlenül tényleg UTF-16 fájl ne
    csússzon át hibásan dekódolva -- egy valódi UTF-16LE szöveg tele van null-bájtokkal, amik
    UTF-8-ként azonnal `UnicodeDecodeError`-t dobnak)."""
    if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw_bytes.decode("utf-16")
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{path}: nincs UTF-16 BOM a fájl elején, és UTF-8-ként sem dekódolható -- "
            f"ismeretlen/sérült kódolás, nem olvasom be csendben (lásd modul-docstring). "
            f"Eredeti hiba: {exc}"
        ) from exc


def parse_set_file_raw(path):
    """Beolvassa a `.set` fájlt, visszaadja a NYERS (`Inp* -> string érték`) dict-et -- minden
    sort, nem csak a trial-paramétereket (pl. `InpMagicNumber`, `InpLotSize` is benne marad, hogy
    a hívó fél ezeket is kinyerhesse, ha kell)."""
    path = Path(path)
    raw_bytes = path.read_bytes()
    text = _decode_set_file_bytes(path, raw_bytes)

    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip()
    return fields


def set_file_to_trial_params(path):
    """A NYERS mezőkből felépíti a `FixedTrial(...)`-nak átadható trial-paraméter dict-et --
    csak a `SET_KEY_TO_TRIAL_KEY`-ben szereplő 16 kulcsot veszi át, típuskényszerítve. Hangosan
    hibázik, ha egy elvárt kulcs hiányzik a fájlból (pl. régi/hiányos preset) -- ez itt SOSEM
    lehet csendes 0/None, mert a baseline téves lenne."""
    raw = parse_set_file_raw(path)
    trial_params = {}
    missing = []
    for set_key, (trial_key, cast) in SET_KEY_TO_TRIAL_KEY.items():
        if set_key not in raw:
            missing.append(set_key)
            continue
        trial_params[trial_key] = cast(raw[set_key])
    if missing:
        raise ValueError(f"{path}: hiányzó Inp*-kulcsok a .set fájlban: {missing}")
    return trial_params
