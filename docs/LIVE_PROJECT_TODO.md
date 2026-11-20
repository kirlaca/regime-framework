# Élő projekt felé jelzett, még ÁT NEM VEZETETT javítások

Cél: amikor a felhasználó legközelebb megnyitja a `d:\XM\Optuna` élő projektet, ez a fájl gyors
listát ad arról, mit kell onnan is átvezetni. A `optuna_research` workspace SZÁNDÉKOSAN nem nyúl
az élő projekt fájljaihoz — ez a lista csak jelzés, a tényleges átvezetést a felhasználó (vagy egy,
az élő projektben induló munkamenet) végzi el.

## 1. Napvégi kényszerzárás hiba (2026-09-05, megerősítve; 2026-09-16-án ÁTVEZETVE az élesbe)

**A hiba**: `core/engine.py`, `components/trend_following.py` és `components/mean_reversion.py`
napvégi kényszerzárás logikája (`is_last_bar_of_day[idx]`) csak a "pozíció már nyitva" ágban fut —
ha egy belépési jel PONT a nap utolsó bar-ján tüzelt, a pozíció a KÖVETKEZŐ (már másnapi, akár
hétvége utáni) bar-ig nyitva maradhatott, nem modellezett swap-kitettséget okozva. Ez a **LIVE
Engine-ben (`d:\XM\Optuna\regime_framework\core\engine.py`) IS jelen van**, nem csak a
kutatási kódban — bár a jelenlegi éles rendszer M10-es index-CFD-ken fut, ahol a felhasználó
korábban dokumentálta, hogy nincs swap-kitettség (minden ugyanaznap zár) — ELLENŐRIZENDŐ, hogy ez
a garancia a hiba fényében is helytálló-e (lásd lentebb).

**A javítás** (2 réteg, mindhárom fájlban):
1. Belépési kapu: `elif ... and not is_last_bar_of_day[idx]:` — ne engedjen ÚJ belépést a nap
   utolsó bar-ján.
2. Elsődleges védelem (a belépési kapu önmagában NEM elég megbízható — lásd ok lent): a
   "pozíció már nyitva" ágban, MIELŐTT `check_exit()` lefutna, egy explicit dátum-összehasonlítás:
   ```python
   if dates[idx] != entry_date:
       exit_decision = ExitDecision(exit_price=ctx.close, reason="EOD_FORCED")
   else:
       exit_decision = owning_component.check_exit(ctx, position)
       if exit_decision is None and is_last_bar_of_day[idx]:
           exit_decision = ExitDecision(exit_price=ctx.close, reason="EOD_FORCED")
   ```
   Ez a 2. réteg fogja meg azt az esetet is, amikor `is_last_bar_of_day` maga tévesen `False`-t ad
   a nap tényleges utolsó bar-jára (pl. hiányzó/eldobott bar miatt) — a belépés így "átcsúszhatna"
   a kapun, de a napváltás-ellenőrzés a KÖVETKEZŐ bar-on mindenképpen elkapja.

**Ellenőrzés módja** (lásd `research/verify_eod_fix.py`, futtatás:
`python -m regime_framework.research.verify_eod_fix` a `optuna_research` gyökérből): 7 IC Markets
részvény-CFD-n, teljes 2020-2026 M10-es adaton, a javítás után **0/8055 trade nyúlik át
napváltáson** (korábban, javítás előtt: 108/8153).

**✅ (a) ÁTVEZETVE (2026-09-16)**: a 2 réteg bekerült a live `core/engine.py`,
`components/mean_reversion.py` és `components/trend_following.py` fájlokba (mindhárom helyen a
`validate()`/`Engine.run()` saját ciklusában) — szintaktikailag ellenőrizve (`py_compile`, 0 hiba),
a `dst_aware`/DST-kapcsolódó változtatások (amik ugyanezekben a fájlokban, de KÜLÖN, még nyitott
kérdésként élnek a research-oldalon) SZÁNDÉKOSAN NEM lettek átvezetve.

**⚠️ (b) MÉG HÁTRAVAN**: lefuttatni a live rendszer jelenlegi (US100Cash#/US500Cash#/US30Cash#
index-CFD) paraméterein a `verify_eod_fix.py` mintájára egy ellenőrzést, hogy VOLT-e ténylegesen
bármilyen — akár csak elméleti — napváltáson-átnyúló eset a live szimbólumokon is (a korábbi
"nincs swap-kitettség" dokumentáció ezt implicit feltételezte, de sose tesztelte KIFEJEZETTEN erre
a konkrét hibára). Ez a lépés NEM történt meg — a kódjavítás átvezetése önmagában nem bizonyítja,
hogy a hiba valaha ténylegesen elsült volna élesben, csak hogy a KOCKÁZAT immár ki van zárva.

## 2. FONTOS ÜZEMELTETÉSI CSAPDA: stale editable-install pointer

A `D:\XM\Optuna\venv`-be telepített `regime_framework` editable install
(`__editable___regime_framework_0_1_0_finder.py`) a csomagot **explicit `D:\XM\Optuna\regime_framework`-re** térképezi (`MAPPING = {'regime_framework': 'D:\\XM\\Optuna\\regime_framework'}`).

Ha egy Python script/fájl a `D:\XM\optuna_research` könyvtáron KÍVÜLRŐL (pl. egy scratchpad/temp
mappából) fut le közvetlen fájlként (`python valami.py`, NEM `python -m` és NEM `-c`), a cwd nem
kerül a `sys.path` elejére úgy, ahogy `-m`/`-c` esetén — ilyenkor Python CSENDBEN visszaesik erre a
régi, editable-install-lal telepített `D:\XM\Optuna` másolatra, akkor is, ha a `optuna_research`
másolatot szerkesztettük. Ez okozott egy ~2 órás, megtévesztő debug-kört ebben a munkamenetben (a
javítás "látszólag semmit nem változtatott", mert a debug script valójában a RÉGI kódot futtatta).

**Szabály innentől**: minden `optuna_research`-beli scriptet `python -m regime_framework.xxx.yyy`
alakban, a `D:\XM\optuna_research` könyvtárból kell futtatni — SOSE közvetlen fájlútvonalként egy
a projekten kívüli mappából. Érdemes lenne az élő projektben is ellenőrizni, nem áll-e fenn
ugyanez fordítva (bár ott nincs második editable-install, úgyhogy ott valószínűleg nem probléma).

## 3. PROJEKTSZABÁLY: Optuna trial-szám minimum 200, sose 60 (2026-09-05; a `regime_framework/
optimization/run_study.py` 2026-09-16-án ÁTVEZETVE az élesbe -- a `main_optuna.py`/
`main_optuna_orb.py` gyökér-szintű, régebbi scriptek MÉG NEM lettek átvezetve, lásd lentebb)

Az IC Markets US30 melegindítás bebizonyította: egy NEM melegindított, 60 trial-os Optuna-keresés
ebben a ~15-20 dimenziós paraméctérben NEM megbízható — friss 60 trial-os keresés US30-on 11.78-at
adott, ROSSZABBAT, mint a puszta paraméter-transzfer (21.62), miközben UGYANAZ a keresési tér
200 trial-lal (vagy melegindítással) 40.89-et ér el. Részletek: `PLAN.md` 2.5 szakasz.

**✅ `D:\XM\Optuna\regime_framework\optimization\run_study.py` ÁTVEZETVE (2026-09-16)**:
`DEFAULT_N_TRIALS = 60` → `200`, a magyarázó kommentekkel együtt — a fájl mostantól bájt-pontosan
megegyezik a `optuna_research`-beli verzióval.

**⚠️ MÉG HÁTRAVAN**: a `D:\XM\Optuna` GYÖKERÉBEN lévő, régebbi (nem `regime_framework`-beli)
scriptek MÉG NEM lettek ellenőrizve/javítva — a 2026-09-15-i módszertani átvizsgálás (lásd
`d--XM-optuna-research` memória, `feedback_optuna_trial_minimum.md`) megtalálta, hogy
`main_optuna.py`-ban `n_trials=150`, `main_optuna_orb.py`-ban `n_trials=100` van HARDKÓDOLVA (nem
is alapérték, hanem a hívásba égetve) — ezeket még NEM javítottuk, sem itt, sem élesben.
