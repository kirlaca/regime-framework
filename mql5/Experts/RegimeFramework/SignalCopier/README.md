# RegimeFramework Signal Copier (master → slave)

## Miért

2026-09-23-án ugyanaz az EA és `.set` az IC Markets USTEC-en belépett (MR LONG, 20:10), a Pepperstone
NAS100-on nem. Az ok nem hiba, hanem feed-eltérés: a 20:00-s bár ADX-rangja Pepperstone-on 0,339 volt,
a RANGING-határ 0,33 (részletek: `optuna_research/regime_framework/docs/SESSION_LOG.md`, 2026-09-24).
**Döntés (felhasználó, 2026-09-24): az IC Markets a referencia, erre hangoltunk. A Pepperstone ezt
kövesse, ne hozzon saját döntést.**

## Felépítés

```
IC Markets terminál                        Common\Files                   Pepperstone terminál
RegimeFramework_EA (master, VÁLTOZATLAN)                                  RF_SignalSlave
RF_SignalPublisher (külön charton)  ──▶  RF_signal_USTEC_101001.txt  ──▶  (a régi EA HELYETT)
```

- **`RF_SignalPublisher.mq5`** (master terminál, külön chart): nem kereskedik. A master
  (`InpMasterSymbol` + `InpMasterMagic`) nyitott pozíciójáról pillanatképet ír eseményre
  (`OnTradeTransaction`) és másodpercenként. Az írás atomikus: `.tmp` fájl → `FileMove`, `end=OK` zárósor.
- **`RF_SignalSlave.mq5`** (követő terminál, a régi `RegimeFramework_EA` helyett): 100 ms-onként olvas.
  - Új master-pozíció → nyit (saját lot, a master SL/TP-je a pillanatnyi inter-bróker különbséggel
    eltolva, a master kommentjével: `RF_MR`/`RF_TF`/`RF_LHC`/`RF_FS`, így a dashboard
    komponens-bontása változatlan).
  - Master SL-módosítás (TF trailing) → SL követése, csak szigorító irányba.
  - Master zárt → zár.

## Tervezési döntések (2026-09-24)

1. **Külön Publisher**, nem a master EA-ba építve: az élő, validált master érintetlen marad. Ára kb.
   +100 ms slave-késés (a master teljesülése után értesül). Várható teljes slave-késés: 0,2–0,5 mp.
2. **A TF trailing stopot is követi a slave.**
3. **Pillanatkép (állapot), nem eseménynapló**: újraindulás vagy kimaradt esemény után a következő
   pillanatképből magától helyreáll.

## Biztonsági szabályok

| Szabály | Input |
|---|---|
| Minden slave-pozíción natív, brókeroldali SL (és TP, ha a masternek van) | — |
| Elavult pillanatképre nem nyit és nem zár (a nyitott pozíciót a natív SL/TP védi) | `InpMaxSignalAgeMs=5000` |
| Túl régi master-pozícióra nem nyit (pl. slave-újraindítás közben nyílt) | `InpMaxEntryDelaySec=10` |
| A „kezelt ticket” jelző csak sikeres nyitás után vagy az ablak lejártakor áll be | — |
| Újrapróbálás legfeljebb 1/mp | — |
| Saját napvégi kényszerzárás | `InpForceCloseHour/Minute=23:49` |
| Saját spread-anomália-védelem (az ablakon belül újrapróbál) | `InpUseSpreadGuard=true` |
| Saját távoli leállítás (dashboard) | `RegimeFramework_control_<SYM>_<magic>.txt` |
| A dashboard-kompatibilis heartbeat (+ `mode=slave`, `signal_age_ms`, `mirrored_master_ticket`) | — |

A slave állapota (`RFS_<SYM>_<magic>_mirrored` / `_handled`) terminál-globális változóban van, így
újraindítást is túlél.

## ⚠️ Átállás a VPS-en (csak a felhasználó engedélyével)

1. **Csak akkor**, amikor a Pepperstone-számlán NINCS nyitott 101001-es pozíció: a slave ugyanazt a
   magicet használja, és egy általa nem ismert pozíciót zárna, ha a masternek nincs pozíciója.
2. IC Markets terminál: `RF_SignalPublisher` egy ÚJ chartra (bármelyik szimbólum), `InpMasterSymbol=USTEC`,
   `InpMasterMagic=101001`. A master EA-hoz nem kell nyúlni.
3. Pepperstone terminál: a NAS100 chartról a `RegimeFramework_EA_M10_10d`-t LEVENNI, helyette
   `RF_SignalSlave`, `InpMagicNumber=101001`, `InpLotSize` = a korábbi `.set` lotja.
4. Mindkét terminálban engedélyezni az algo tradinget; a Journalban ellenőrizni az indulási üzeneteket.
5. `Common\Files\RF_signal_USTEC_101001.txt`: `end=OK`, a `publish_tick_ms` másodpercenként frissül.

## Demo-teszt ellenőrzőlista (élesítés ELŐTT)

Két terminál kell ugyanazon a Windows-felhasználón (a Common mappa közös): IC Markets DEMO + Pepperstone DEMO.

**A) Gyors funkcionális teszt kézi pozíciókkal — ✅ KÉSZ, 2026-09-24** (IC demo `D:\MT5` + Pepperstone
demo `D:\MT5_ICDemo` portable; Publisher `InpMasterMagic=0`, Slave `InpSignalFile=RF_signal_USTEC_0.txt`):
- [x] Nyitás: a master teljesülése után 60–230 ms-mal, eltolt SL/TP-vel (basis ≈ 17,6–19,3 pont)
- [x] SL szigorítása → követi pontosan (+86 ms); lazítása → NEM követi
- [x] Master zárása → slave zár; TP → mindkettő a saját TP-jén
- [x] SELL irány
- [x] 10 mp-nél régebbi master-pozíció → „kihagyva”
- [x] A slave saját SL-jén kiesik, a master még 6,5 mp-ig nyitva → NEM nyit újra
- [x] Publisher leállítva → 5 mp után „elavult”, a nyitott slave-pozíció marad (a saját TP-jén zárt)
- [x] Távoli leállító fájl → nem nyit; az ablak lejártával „kihagyva”, a fájl törlése után sem pótolja

**A teszt közben talált és JAVÍTOTT hiba**: az első verzió minden ciklusban újraszámolta a basis-t, és
a tickenkénti zaj (±0,5–1 pont) a „csak szigorító” szabállyal felfelé „racsnizta” a slave SL-jét
(6 mp alatt 4 módosítás, master-változás nélkül). Javítás: a basis a NYITÁSKOR rögzül
(`RFS_<SYM>_<magic>_basis`), az `InpSlSyncTolerancePoints` alapértéke 5 → 1. Utána az SL 25 mp-ig nem
mozdult, a master-módosítást pontosan követte. Kiegészítés: „master-jel helyreállt” naplósor.

**Tanulságok**: (1) a `.ex5` bemásolása után az EA-t le kell venni és újra fel kell tenni a chartra (a
terminál csak a saját MetaEditorával fordítottat tölti újra magától); (2) újrafelrakáskor az inputok az
alapértékre állnak vissza (a demón `InpMasterMagic`/`InpSignalFile` átírása kell, élesben az alapérték
a helyes).

**B) Valós jelzésekkel** (Publisher `InpMasterMagic=101001`, a master EA az IC demón fut): legalább egy
hétig, a két napló időbélyegeiből mérve a slave-késést és a belépési ár-eltérést.

## v1.10 (2026-09-25): SHADOW mód és éles EA védelem

**Felhasználói kérés**: a master–slave láncot az ÉLES rendszeren is ki kell tudni próbálni az átállás előtt,
külön tesztkörnyezet nélkül. A slave ilyenkor csak naplózhat, és ha a slave oldalon már fut egy éles EA,
akkor sem vezérelhet.

- **`InpExecutionMode`**: `EXEC_SHADOW` (**alapértelmezett**) vagy `EXEC_LIVE`.
- **SHADOW**: soha nem küld megbízást. Virtuális pozíciót vezet: nyitás a saját aktuális áron, SL-követés
  (rögzített basis), SL/TP-figyelés a saját bid/ask-on, zárás a masterrel, napvégi zárás. A virtuális PnL-t
  `OrderCalcProfit()` adja. Heartbeat SAJÁT néven (`RF_SignalSlave_shadow_<SYM>_<magic>.txt`), hogy a
  dashboard továbbra is az éles EA-t lássa.
- **A TÉNYLEGES mód csak akkor LIVE**, ha (1) `InpExecutionMode=EXEC_LIVE`, ÉS (2) a terminálban nem fut
  más EA ugyanazon a szimbólumon, és sehol nem fut `RegimeFramework*` nevű EA (chart-bejárás), ÉS (3) nincs
  idegen pozíció ugyanazzal a szimbólummal/magic-kel. Bármelyik sérül → **kényszerített SHADOW**, naplózva
  és push-értesítéssel, másodpercenként ellenőrizve. Módváltáskor a folyamatban lévő követést egyik mód
  sem viszi tovább.
- **Pozíció-tulajdonjog ticket alapján** (`RFS_<SYM>_<magic>_mypos`): a slave csak a saját nyitott
  pozícióját kezeli. Egy levett éles EA által nyitva hagyott, azonos magic számú pozíciót soha nem tekint
  sajátjának.
- **CSV-napló** mindkét módban (`Common\Files\RF_SignalSlave_<SYM>_<magic>.csv`), eseményei: `MODE`,
  `OPEN`, `SL_MODIFY`, `CLOSE_*`, `SKIP_LATE`, `BLOCKED`, `STALE`, `RECOVERED`, `CLOSED_BY_BROKER`, `DEINIT`.

**C) Demo-teszt — ✅ KÉSZ, 2026-09-25** (Slave v1.11, Publisher v1.01; próba-EA:
`test/RegimeFramework_EA_GuardTestDummy.mq5`, CSAK demóra):
- [x] C1: SHADOW (alapérték) → virtuális `OPEN`/`SL_MODIFY`/`CLOSE_MASTER_CLOSE` a CSV-ben (+78 ms), a
      Pepperstone-számlán NINCS valódi megbízás, a heartbeat `RF_SignalSlave_shadow_…` néven
- [x] C2: `EXEC_LIVE` + dummy egy másik NAS100 charton → TÉNYLEGES SHADOW, oka a dummy nevével naplózva;
      a kötésre csak virtuális nyitás, SL/TP-követés (+13,6 basis) és zárás
- [x] C3: a dummy nélkül, EA nélküli második charttal → TÉNYLEGES LIVE; valódi BUY (+130 ms), az SL+TP
      egyetlen módosítással (+88 ms), valódi zárás a masterrel; a heartbeat az éles fájlnéven
- [x] C4: a dummy nyitott egy 101001-es pozíciót, majd levéve → SHADOW maradt „idegen pozíció” okkal; két
      master-kötést csak virtuálisan követett, az idegen pozícióhoz nem nyúlt; a pozíció kézi zárása után
      1 mp-en belül LIVE

**A C-teszt közben talált és JAVÍTOTT hibák**:
1. EA nélküli charton a `ChartGetString(…, CHART_EXPERT_NAME)` **NULL**-t ad, ami MQL5-ben nem egyenlő
   `""`-vel → minden üres chart „futó EA”-nak számított (óvatos irányba tévedett, de LIVE-ra soha nem váltott
   volna). Javítás: `StringLen(ea) > 0`.
2. A master TP-módosítását nem követte (csak nyitáskor vette át) → v1.11: TP-követés mindkét módban.
3. Publisher: `FileMove` 5004 (a slave épp olvasta a fájlt) → azonnali újrapróbálás, legfeljebb 5×.
4. A rövid (1–10 mp-es) kiesések push-áradatot okoztak volna → push csak `InpStalePushAfterSec`
   (30 mp) folyamatos kiesés után; a napló és a CSV továbbra is mindent rögzít.
5. A dummy 0,01-es lotja „Invalid volume” volt (a NAS100 minimuma 0,1) → a bróker minimumát használja.
