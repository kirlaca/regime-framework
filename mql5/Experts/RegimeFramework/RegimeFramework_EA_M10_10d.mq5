//+------------------------------------------------------------------+
//| RegimeFramework_EA_M10_10d.mq5                                    |
//| A RegimeFramework_EA.mq5 (egyseges, standard M10) MASOLATA, EGYETLEN|
//| strukturalis kulonbseggel: a RegimeClassifier_M10_10d.mqh-t hasznalja|
//| (REGIME_ROLLING_WINDOW_BARS=1320, 10 kereskedesi nap) a standard    |
//| 8640 (60 nap) helyett -- lasd RegimeClassifier_M10_10d.mqh fejlecet.|
//| A default inputok a timeframe_deepdive vegleges, validalt USTEC M10 |
//| konfiguraciojara vannak allitva (timeframe_deepdive/FINDINGS_LOG.md |
//| 4-6. bejegyzes, nettó PF=2,08, 2026-09-17) -- de a normal konvenciot |
//| (MINDIG .set-bol tolteni) EZ A VALTOZAT IS koveti, ezek csak         |
//| biztonsagi alapertekek.                                             |
//|                                                                    |
//| EGYSÉGES, MINDEN BRÓKERRE KÖZÖS VÁLTOZAT (2026-09-11-i döntés) --  |
//| ez a fájl VÁLTJA FEL mind a korábbi RegimeFramework_EA.mq5 (XM),   |
//| mind a RegimeFramework_EA_ICMarkets.mq5 (IC Markets teszt-        |
//| valtozat) fájlokat. A ket fajl kozotti EGYETLEN funkcionalis       |
//| elteres a napvegi kenyszerzaras hibajavitasa volt (lasd lent,      |
//| "NAPVALTAS-ALAPU ELSODLEGES napvegi kenyszerzaras-vedelem") -- ez  |
//| a javitas MOST MAR minden brokeren/szimbolumon egysegesen aktiv.   |
//| Minden broker/szimbolum-specifikus parameter (Optuna-hangolt       |
//| ertekek, magic number, lot meret) KIZAROLAG a hozza tartozo .set   |
//| fajlbol jon -- a lenti input-alapertekek csak egy PELDA/BIZTONSAGI |
//| ALAPERTEK (IC Markets USTEC-re hangolva), SOSEM szabad .set fajl   |
//| betoltese nelkul elesben hasznalni.                                |
//|                                                                    |
//| ELOZMENY: a ket fajl 2026-09-06-ban vált szét, amikor az IC        |
//| Markets migraciot elkulonitett masolatkent kezdtuk el tesztelni,   |
//| hogy az elo (XM-re futo) fajlt ne erintse a kiserletezes. Miutan a |
//| migracio bevalt es mindket broker ugyanazt a logikat futtatja,     |
//| ket kulon forrasfajl fenntartasa csak felesleges divergencia-      |
//| kockazatot jelentett (2026-09-11-i code review pontosan egy ilyen, |
//| 5 napja eszrevetlen maradt divergenciat talalt -- lasd             |
//| optuna_research SESSION_LOG.md 2026-09-11 bejegyzeset), ezert      |
//| egyesitettuk EGY forrasra.                                         |
//|                                                                    |
//| ÚJ, NAPVALTAS-ALAPU ELSODLEGES napvegi kenyszerzaras-vedelem       |
//| (eredetileg 2026-09-06, IC Markets teszt-valtozat) -- a Python      |
//| regime_framework-ben talalt es javitott hiba (lasd optuna_research |
//| repo SESSION_LOG.md 2026-09-05, "Napvegi kenyszerzaras hiba") analog|
//| MQL5-re szabott verzioja. A regi (InpForceCloseHour ORA-kuszobos)   |
//| mechanizmus ELMELETBEN nem zarna idoben, ha a piac aznap MAR a      |
//| kuszob-ora ELOTT leallna (session-zaras) - a pozicio ekkor a        |
//| KOVETKEZO nap nyitasaig (vagy tovabb) nyitva maradhatna. Az uj      |
//| ellenorzes a MT5-ben natívan tarolt POSITION_TIME-ot hasznalja: ha  |
//| a pozicio nyitasi napja mar NEM a mai nap, AZONNAL zarunk,          |
//| fuggetlenul az orától. A FridayShort-ot EZ A JAVITAS NEM ERINTI --  |
//| annak MAR van sajat, kulon (IsFsHoldEnd()/IsFsSafetyCloseTime())    |
//| vedelme, azt a valtoztatas valtozatlanul hagyja (lasd az OnTick()-  |
//| beli `ownerTag != OWNER_TAG_FS` kizarast, mind a regi, mind az uj   |
//| agban).                                                            |
//|                                                                    |
//| A regime_framework Python Engine XOR-dispatch logikajanak MQL5    |
//| portja: MeanReversion (RANGING) + TrendFollowing (TRENDING),      |
//| a CMarketConditionClassifier elo, streaming rezsim-besorolasa      |
//| alapjan valasztva - lasd core/engine.py.                          |
//|                                                                    |
//| FONTOS ELTERESEK a Python Engine-hez kepest (lasd PLAN.md 0.1):    |
//|  - A MeanReversion SL/TP-je natic broker stop-megbizaskent megy at,|
//|    NEM a Python resolve_fixed_exit() pesszimista feloldasaval.     |
//|  - A TrendFollowing trailing stopja PositionModify()-val frissul   |
//|    minden uj baron, valodi elo mechanizmuskent (nem backtest-csak).|
//|  - SessionPhaseClassifier meg nincs bekotve (a Python oldalon is   |
//|    nyitott pont - minden bar CORE_SESSION-nek szamit).             |
//|  - Nincs koltseg-modellezes (spread/szlippazs elo, valos adat).    |
//|                                                                    |
//| FIGYELEM: a CMarketConditionClassifier ~1320 baron at "bemelegszik"|
//| (10 kereskedesi nap M10-en, EBBEN A VALTOZATBAN -- lasd            |
//| RegimeClassifier_M10_10d.mqh), mielott ervenyes trend_band/        |
//| vol_band besorolast ad - addig az EA nem nyit poziciot.            |
//|                                                                    |
//| Az EA-t arra az idosikra (chart period) illeszd, amelyiken a       |
//| Python walk-forward validacio futott (M10).                        |
//|                                                                    |
//| MINDEN ÉLŐ PÉLDÁNYHOZ SAJÁT .set FÁJLT TÖLTS BE (lásd presets/     |
//| mappa) -- a Python oldali Optuna-hangolas eredmenyet (regime_      |
//| framework/optimization/run_study.py vagy a warmstart_retune        |
//| szkriptek kimenete) a .set fajl hordozza, NEM a forraskod. A lenti  |
//| input-alapertekek CSAK arra az esetre valo biztonsagi halo, ha      |
//| valaki veletlenul .set nelkul inditana - lasd PLAN.md 0.1, 4.       |
//| szabaly: a keresesi folyamat maga nem portolodik, csak az eredmenye.|
//+------------------------------------------------------------------+
#property copyright "Regime Framework EA (egységes, minden bróker)"
#property version   "2.01"
#property strict

#include <Trade\Trade.mqh>
#include "RegimeClassifier_M10_10d.mqh"   // 1320 bar (10 nap) -- lasd fenti fejlec; ELSOKENT includeolva,
                                           // hogy a MeanReversion.mqh/TrendFollowing.mqh sajat
                                           // "#include RegimeClassifier.mqh" sora ne huzza be masodszor
                                           // az EREDETI (8640-es) valtozatot -- ugyanaz a trukk, mint
                                           // RegimeClassifier_M30.mqh-nal.
#include "MeanReversion.mqh"
#include "TrendFollowing.mqh"
#include "LastHourContinuation.mqh"
#include "FridayShort.mqh"
#include "MarketHolidays.mqh"
#include "SpreadAnomalyGuard.mqh"

CTrade trade;

// FIGYELEM: az alabbi ertekek CSAK PELDA/BIZTONSAGI ALAPERTEKEK (IC Markets USTEC-re
// meleginditott Optuna-hangolas, regime_framework/research/icmarkets_ustec_warmstart_retune.py,
// optuna_research repo, 2026-09-05, kockazat-korrigalt pontszam: 91.03) -- MINDEN egyes elo
// peldanyhoz (broker+szimbolum) SAJAT .set fajlt KELL betolteni a presets/ mappabol, lasd
// 2026-09-11_ea_unification/CHECKLIST.md. Ha egy chart .set nelkul, csak ezekkel az
// alapertekekkel indulna el, az CSENDBEN a rossz (nem az adott szimbolumra hangolt) parameterekkel
// kereskedne.
input group "=== Komponens-routing (2026-09-15, M30 production-integracio -- lasd regime_deepdive/FINDINGS_LOG.md 32-33. bejegyzes) ==="
input bool   InpEnableMeanReversion  = true;   // false = ez a peldany SOSEM nyit MeanReversion-poziciot (RANGING regimeben sem)
input bool   InpEnableTrendFollowing = true;   // false = ez a peldany SOSEM nyit TrendFollowing-poziciot (TRENDING regimeben sem)
input bool   InpEnableLastHourContinuation = true;   // false = ez a peldany SOSEM nyit LastHourContinuation-poziciot
input bool   InpEnableFridayShort          = true;   // false = ez a peldany SOSEM nyit FridayShort-poziciot
// Mind a negy alapertek 'true' -- a jelenlegi, MEGLEVO elo M10-es .set-fajlok (amikben ezek az
// inputok meg nem leteznek) ezert VALTOZATLAN viselkedest kapnak ujrafordítás/EA-ujratoltes utan
// is. A M30 MeanReversion-only instanciak (routing_m30.json) mind a harom masik kapcsolot
// false-ra allitjak -- a LastHourContinuation/FridayShort SOHA nem lett validalva M30-on/IC
// Markets hosszu tortenelmen, tehat itt nem futhatnak, amig ez meg nem tortenik.

input group "=== MeanReversion parameterek (PÉLDA-ÉRTÉK -- .set fájllal felülírandó) ==="
input int    InpMrEmaPeriod        = 120;              // EMA periodus (csatorna kozepe)
input double InpMrMultiplier       = 3.016810099237794;   // Csatorna szelesseg (ATR-szorzo)
input double InpMrSlMultiplier     = 0.5019957737381252;  // SL tavolsag (ATR-szorzo)
input double InpMrRiskRewardRatio  = 5.998892385646057;   // TP/SL arany

input group "=== TrendFollowing parameterek (PÉLDA-ÉRTÉK -- .set fájllal felülírandó) ==="
input double InpTfFastEmaDays        = 1.4213259014544624;   // Gyors EMA (napokban, lasd BARS_PER_DAY konverzio)
input double InpTfSlowEmaDays        = 2.2214437598322476;   // Lassu EMA (napokban)
input double InpTfSlAtrMultiplier    = 2.8097032156200794;   // Kezdeti SL tavolsag (ATR-szorzo)
input double InpTfTrailAtrMultiplier = 3.388832537439072;    // Trailing stop tavolsag (ATR-szorzo)
input double InpTfRsiLongMin         = 76.66752227906817;    // LONG csak ha RSI >= ez az ertek
input double InpTfRsiShortMax        = 57.88696992297191;    // SHORT csak ha RSI <= ez az ertek
input int    InpTfRsiPeriod          = 14;    // RSI periodus (egyszeru, nem Wilder-simitott) -- NEM hangolt
// Bollinger-kitores megerosites (hozzaadva 2026-08-20, most mar Optuna-hangolva IC Markets USTEC-re).
input int    InpTfBollingerPeriod    = 39;                // Bollinger-szalag periodusa
input double InpTfBollingerK         = 2.8713829985073884; // Bollinger-szalag szelesseg (szoras-szorzo)
// ⚠️ HIBAJAVITAS (2026-09-15, a teljes modszertani atvizsgalas soran talalva -- lasd
// regime_deepdive/FINDINGS_LOG.md 30. bejegyzes, a PYTHON-oldali megfelelojerol): a
// fast/slow_ema_days -> bar-szam konverziohoz hasznalt BARS_PER_DAY korabban a konstruktor-
// hivasban KOZVETLENUL, HARDKODOLTAN 144-kent (M10-re kalibralva) volt atadva -- egy M30-on futo
// peldany (lasd routing_m30.json) enelkul az input nelkul HELYTELEN EMA-tavokkal futott volna,
// UGYANAZ a hibaosztaly, mint amit ma a Python-oldalon talaltunk es javitottunk.
input int    InpTfBarsPerDay         = 144;   // M10=144, M30=44 (lasd PLAN.md/FINDINGS_LOG.md) -- .set-bol allitando

input group "=== LastHourContinuation parameterek (PÉLDA-ÉRTÉK -- .set fájllal felülírandó) ==="
input double InpLhcSlAtrMultiplier  = 3.547856495599582; // SL tavolsag (ATR-szorzo)
input int    InpLhcFinalHourStart   = 20;     // A napi "utolso ora" ablak kezdete (ora, szerveridő) -- NEM hangolt
input int    InpLhcSessionEndHour   = 21;     // Kenyszerzaras hatarideje (ora) - ez az OVE sajat, a
                                               // tobbi komponensnel korabbi zarasi hatarideje -- NEM hangolt
input int    InpLhcMinTrendBars     = 20;     // Min. bar-szam a napi trend-ablakban ervenyesseghez (irrelevans -- lasd timeframe_deepdive/FINDINGS_LOG.md 6. bejegyzes, bit-azonos eredmeny 5-20 kozott)
input bool   InpLhcDstAware         = false;  // DST-igazitas -- SZANDEKOSAN false ebben a valtozatban is,
                                               // lasd dst_contradiction_unresolved memoria: a fix
                                               // UTC+3 feltetelezes ELLENTMOND egy hivatalos brokerdok-
                                               // umentumnak, novemberi ujramereses fugg tole (HOLD)

input group "=== FridayShort parameterek (PÉLDA-ÉRTÉK -- .set fájllal felülírandó) ==="
input int    InpFsTargetDayOfWeek  = 4;       // Cel-nap, pandas-konvencio (0=Hetfo...4=Pentek) -- NEM hangolt
input int    InpFsTargetHour       = 23;      // Cel-ora (szerveridő) -- NEM hangolt
input double InpFsSlAtrMultiplier  = 1.1558558016169869; // SL tavolsag (ATR-szorzo)
input int    InpFsHoldBars         = 11;      // Tartasi ido bar-okban (1 bar = PERIOD_CURRENT)
// Biztonsagi zaras a hold_bars/nap-hatar logikatol FUGGETLENUL, MINDEN ticken ellenorizve (nem
// csak uj baron) -- lasd IsFsSafetyCloseTime() fejlec-kommentjet: a bróker Trade session pénteken
// korabban zar, mint ahogy a hold_bars/nap-hatar logika a hetvegi quote-szunet miatt egyaltalan
// eszlelni tudna a nap valtasat. ✅ ELLENORIZVE mindket brokerre (IC Markets/XM): mindharom
// vizsgalt szimbolumon KONZISZTENSEN 23:50:00-kor erkezik az utolso penteki bar.
input int    InpFsSafetyCloseHour   = 23;      // Biztonsagi zaras oraja (ora, szerveridő)
input int    InpFsSafetyCloseMinute = 49;      // Biztonsagi zaras perce -- a broker Trade-cutoff elott legalabb 1 perccel

input group "=== Session / kockazatkezeles (PÉLDA-ÉRTÉK -- .set fájllal felülírandó) ==="
input int    InpSessionStartHour   = 16;      // Session kezdete (ora, szerveridő)
input int    InpSessionStartMinute = 30;
input int    InpSessionEndHour     = 21;      // Belepesi ablak vege (ora)
// JAVITAS (2026-09-11, MT5-port bit-pontos validacioja talalta, lasd optuna_research repo
// SESSION_LOG.md): a batch Python Engine.run()-nak NINCS force-close-hour fogalma -- a nap
// TENYLEGES utolso bar-jaig (~23:50) futni hagyja a poziciot, csak akkor kenyszerzar, ha addig
// sem zart SL/TP/trailing. A regi InpForceCloseHour=23 (perc nelkul, tehat gyakorlatilag 23:00-tol)
// EZ ELÉ, akar 50 perccel korabban zar -- ez elveszthetett kedvezo SL/TP-fordulatokat, amiket a
// validalt backtest-szamok (win-rate/PF) mar beleszamoltak. Kideritve: a broker mindket oldalon
// (IC Markets, XM) 00:00 SZERVERIDOKOR szamolja a swapot (hivatalos brokerdokumentacio szerint),
// NEM 23:00-kor -- tehat az eredeti cel (overnight-dij elkerulese) 23:50 korul is teljesen
// biztonsagosan teljesul, a validalt modellel majdnem azonos hatarido mellett. Az InpForceCloseHour
// MOSTANTOL perc-pontossagu (lasd InpForceCloseMinute), alapertek 23:49 -- ugyanaz a percertek,
// mint a mar bevalt FridayShort biztonsagi zarasnal (InpFsSafetyCloseMinute).
input int    InpForceCloseHour     = 23;      // Ettol az orától (es perctol) kenyszerzaras, ha meg nyitva (masodlagos vedelem -- lasd fent az elsodleges, nap-valtas-alapu vedelmet)
input int    InpForceCloseMinute   = 49;      // Kenyszerzaras perce -- a swap-hatarido (00:00 szerveridő) elott biztonsagosan, de a nap tenyleges vegehez (~23:50) kozel
input double InpLotSize            = 0.3;     // Fix lot (ha InpUseMarginBasedSizing=false) -- MINDIG .set-bol!
                                               // 0.3 @ $2000 tőke: biztonsagos max (25% margin-kihasznaltsag),
                                               // lasd timeframe_deepdive/FINDINGS_LOG.md 7. bejegyzes.
input int    InpSlippagePoints     = 20;
input int    InpMagicNumber        = 101001;  // KULON magic ettol a 10-napos-ablakos valtozattol -- NEM
                                               // azonos a standard M10 EA elo USTEC peldanyaval (202609),
                                               // mert a klasszifikator-ablak (1320 vs 8640) mas viselkedest
                                               // ad -- ez tenylegesen egy MASIK strategia, nem csak egy
                                               // parameter-frissites. MINDIG .set-bol -- lasd CHECKLIST.md

// Margin-alapu poziciomeretezes (hozzaadva 2026-08-23, PRODUCTION_READINESS.md P1 #3. pont --
// lasd core/position_sizing.py MarginBasedSizer Python-oldali megfeleloje). Alapertek false =
// VALTOZATLAN, fix-lotos viselkedes -- csak explicit bekapcsolassal aktivalodik.
//
// EGYETLEN lathato dial (2026-08-30, egyszerusites): a felhasznalonak csak azt kell eldontenie,
// a szabad margin maximum hany szazalekat koti le egyetlen trade-hez. A ket korabbi "vedokorlat"
// (elgepeles elleni felso plafon, illetve a margin-call-tol valo biztonsagos tavolsag) mostantol
// NEM kulon input, hanem a lenti fix konstans - ezek soha nem strategiai valasztas kerdesei,
// csak vedohalok, ezert nem is kell a felhasznalonak latnia/hangolnia oket.
//
// FONTOS - kalibraciora vonatkozo tapasztalat (2026-08-23/26, lasd PRODUCTION_READINESS.md P1 #3
// es a presets/ mappa .set-fajljainak kommentjeit): a margin-alapu meretezes megbizhatosaga
// SZIMBOLUMONKENT ELTERO, es erosen fugg attol, hogy a marginPerLot-becsles a VALOS broker-adatot
// tukrozi-e. US500Cash-en a modellt a VALOS elo-szamla margin/lot ertekevel ujrakalibralva a
// mechanizmus megbizhatoan mukodik (azonos max DD mellett jobb hozam/PF). US100Cash-en viszont
// a modell-becsles es a valosag eltert, a teny leges DD a becsultnel 61%-kal nagyobb lett -- ott
// ezert marad KIKAPCSOLVA (InpUseMarginBasedSizing=false), es a lenti alapertek csak PELDA, NEM
// egy altalanosan validalt ertek. Bekapcsolas elott MINDIG sajat, valos szamla-adaton (nem csak
// modellezett marginPerLot-tal) kell ujrakalibralni - lasd a .set fajlok reszletes kommentjeit.
input group "=== Margin-alapu meretezes (opcionalis, alapbol KIKAPCSOLVA) ==="
input bool   InpUseMarginBasedSizing    = false;   // true = margin-alapu meretezes InpLotSize helyett
input double InpMarginAllocPct          = 5.348;   // Szabad margin hanyada/trade, SZAZALEKBAN megadva (pl. 5.348 = a szabad margin 5.348%-a). Csak PELDA-ertek - szimbolumonkent ujrakalibralando, lasd fenti megjegyzes.

// Ket rogzitett, NEM felhasznaloi input vedokorlat (soha nem strategiai dontes, csak biztonsagi halo):
#define MARGIN_ALLOC_SANITY_CEILING_PCT 50.0    // "elgepeles elleni" jozan-esz-plafon SZAZALEKBAN (pl. 500 beirasa 5.0 helyett) - NEM egy hangolhato strategiai hatar
#define MIN_SAFE_MARGIN_LEVEL_PCT       200.0   // a VALODI, dinamikus biztonsagi kuszob - ha meg a min. lot is e ala vinne a margin-szintet, KIHAGYJUK a belepest

#define OWNER_TAG_MR  "RF_MR"
#define OWNER_TAG_TF  "RF_TF"
#define OWNER_TAG_LHC "RF_LHC"
#define OWNER_TAG_FS  "RF_FS"

//--- globalis allapot
CMarketConditionClassifier      *g_classifier   = NULL;
CMeanReversionComponent         *g_mrComponent  = NULL;
CTrendFollowingComponent        *g_tfComponent  = NULL;
CLastHourContinuationComponent  *g_lhcComponent = NULL;
CFridayShortComponent           *g_fsComponent  = NULL;
CSpreadAnomalyGuard             *g_spreadGuard  = NULL;

// TAVOLI LE/FEL-KAPCSOLO (2026-09-09, felhasznaloi keres: web-dashboardrol/telefonrol is
// indithato/leallithato legyen) -- egy vezerlo-fajl LETEZESE tiltja az UJ belepeseket, ugyanugy,
// mint a naptar-/spread-guard (lasd OnTick() "UJ BELEPES-KAPU" resze). A fajl HIANYA = normal
// mukodes (fail-open, ugyanaz a konvencio, mint IsMarketHoliday()-nel) -- ha a dashboard sosem
// nyult hozza, vagy a fajl torlodik, a kereskedes valtozatlanul folytatodik, nem all le csendben.
// Az EA a fajl TARTALMAT nem ertelmezi, csak a letezeset (FileIsExist), a dashboard a "Leallitas"
// gombra letrehozza, "Inditas"-ra torli.
string   g_controlFileName   = "";

datetime g_lastBarTime       = 0;
datetime g_currentTradingDay = 0;
bool     g_tradeTakenToday   = false;
bool     g_fsExceptionUsedToday = false;   // lasd core/engine.py quota_exempt_time_gated_components
datetime g_fsEntryTime       = 0;          // a FridayShort-pozicio nyitasanak bar-ideje
datetime g_fsEntryDay        = 0;          // ... es a napja (nap-hatar-korlatozashoz)
double   g_trendExtreme      = 0.0;   // csak a TrendFollowing altal nyitott poziciora ertelmezett
bool     g_entryBlockNotifiedToday = false;   // csak naponta egyszer push-oljon a belepes-blokkolasrol

//--- uzemeltetesi monitoring (hozzaadva 2026-08-26, PRODUCTION_READINESS.md P3 #9. pont) ---
long     g_heartbeatCounter  = 0;     // minden OnTick "uj bar" agban nő -- a watchdog ebbol latja, hogy nem "fagyott le" a szamlalas
int      g_tradeErrorCount   = 0;     // OrderSend/PositionModify/PositionClose sikertelensegek szama inditas ota
string   g_lastErrorMsg      = "";

//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| A rezsim-osztalyozo bemelegitese a CHARTON MAR ELERHETO historikus|
//| adatbol (hozzaadva 2026-08-26, PRODUCTION_READINESS.md P3 #8/#9   |
//| kapcsan felmerult felismeres) -- az OnNewBar() enelkul KIZAROLAG   |
//| elo, egyenkenti bar-okon at melegedne be, ami EBBEN A VALTOZATBAN |
//| ~1320 M10 bar = ~10 kereskedesi nap VALOS VARAKOZAST jelentene    |
//| barmilyen mennyisegu mar meglevo historikus adat ellenere -- ez   |
//| a teljes tervezett forward-teszt ablakot (P3 #8, 1-3 honap)       |
//| feleslegesen csokkentette volna. A CopyRates() a chart mar        |
//| letoltott/lekerheto historikus soraibol AZONNAL bemelegit.        |
//+------------------------------------------------------------------+
bool BackfillClassifier()
  {
   int needed = REGIME_ROLLING_WINDOW_BARS + REGIME_TR_DM_PERIOD * 2 + 5;   // biztonsagi tartalek
   MqlRates rates[];
   ArraySetAsSeries(rates, false);   // 0=legregebbi, [copied-1]=legujabb -- kronologikus sorrend kell
   int copied = CopyRates(_Symbol, PERIOD_CURRENT, 1, needed, rates);
   if(copied <= 0)
     {
      PrintFormat("⚠️ Nem sikerult historikus adatot lekerni a bemelegiteshez (hiba: %d) -- valos "
                  "idejű bemelegites lesz (~10 kereskedesi nap M10-en, lasd REGIME_ROLLING_WINDOW_BARS).",
                  GetLastError());
      return false;
     }
   for(int i = 0; i < copied; i++)
      g_classifier.OnNewBar(rates[i].high, rates[i].low, rates[i].close);
   PrintFormat("Rezsim-osztalyozo bemelegitve %d historikus baron (kert: %d) -- keszen all: %s",
               copied, needed, g_classifier.IsReady() ? "IGEN" : "NEM (tovabbi/hosszabb historikus adat kellene)");
   return true;
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);

   g_classifier = new CMarketConditionClassifier();
   BackfillClassifier();
   g_mrComponent = new CMeanReversionComponent(InpMrEmaPeriod, InpMrMultiplier, InpMrSlMultiplier,
                                                InpMrRiskRewardRatio, InpSessionStartHour,
                                                InpSessionStartMinute, InpSessionEndHour);
   g_tfComponent = new CTrendFollowingComponent(InpTfFastEmaDays, InpTfSlowEmaDays, InpTfSlAtrMultiplier,
                                                 InpTfTrailAtrMultiplier, InpTfRsiLongMin, InpTfRsiShortMax,
                                                 InpTfBarsPerDay, InpTfRsiPeriod, InpTfBollingerPeriod, InpTfBollingerK,
                                                 InpSessionStartHour, InpSessionStartMinute, InpSessionEndHour);
   g_lhcComponent = new CLastHourContinuationComponent(InpLhcSlAtrMultiplier, InpSessionStartHour,
                                                        InpSessionStartMinute, InpLhcFinalHourStart,
                                                        InpLhcSessionEndHour, InpLhcMinTrendBars,
                                                        InpLhcDstAware);
   g_fsComponent = new CFridayShortComponent(InpFsTargetDayOfWeek, InpFsTargetHour, InpFsSlAtrMultiplier);

   g_spreadGuard = new CSpreadAnomalyGuard();
   g_spreadGuard.Backfill(_Symbol, PERIOD_CURRENT);

   g_controlFileName = StringFormat("RegimeFramework_control_%s_%d.txt", _Symbol, InpMagicNumber);

   g_currentTradingDay = DayStart(TimeCurrent());

   PrintFormat("RegimeFramework_EA elindult. Symbol=%s, Period=%s, Magic=%d",
               _Symbol, EnumToString((ENUM_TIMEFRAMES)Period()), InpMagicNumber);
   if(!g_classifier.IsReady())
      PrintFormat("FIGYELEM: a rezsim-osztalyozo a historikus bemelegites UTAN sem keszen (kb. %d "
                  "bar kellene, lasd fenti Print sor) -- ELLENORIZD, hogy a brokernel/charton van-e "
                  "eleg historikus adat (kb. 60 kereskedesi nap M10-en). Addig NEM fog kereskedni.",
                  REGIME_ROLLING_WINDOW_BARS);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(CheckPointer(g_classifier) == POINTER_DYNAMIC)
      delete g_classifier;
   if(CheckPointer(g_mrComponent) == POINTER_DYNAMIC)
      delete g_mrComponent;
   if(CheckPointer(g_tfComponent) == POINTER_DYNAMIC)
      delete g_tfComponent;
   if(CheckPointer(g_lhcComponent) == POINTER_DYNAMIC)
      delete g_lhcComponent;
   if(CheckPointer(g_fsComponent) == POINTER_DYNAMIC)
      delete g_fsComponent;
   if(CheckPointer(g_spreadGuard) == POINTER_DYNAMIC)
      delete g_spreadGuard;
  }

//+------------------------------------------------------------------+
datetime DayStart(datetime t)
  {
   return t - (t % 86400);
  }

//+------------------------------------------------------------------+
//| Uzemeltetesi monitoring (PRODUCTION_READINESS.md P3 #9. pont):    |
//| kozos (terminal-fuggetlen) fajlba irt "heartbeat", amit egy KULSO |
//| (nem MQL5-beli) figyelo -- pl. egy periodikusan futtatott Python  |
//| script -- olvashat, hogy eszrevegye, ha az EA leallt/lefagyott.   |
//| A FILE_COMMON flag miatt a fajl a MINDEN terminal altal lathato   |
//| kozos mappaba kerul                                               |
//| (%APPDATA%\MetaQuotes\Terminal\Common\Files\), NEM a konkret      |
//| terminal-peldany sajat MQL5\Files mappajaba -- igy egy kulso      |
//| Python watchdog EGYETLEN, fix helyrol tudja mind a tobb           |
//| szimbolumon futo EA-peldany allapotat olvasni. FONTOS a monitorral|
//| valo kompatibilitashoz: a mezonevek/formatum VALTOZATLAN maradt a |
//| ket korabbi (XM/IC Markets) fajlhoz kepest -- lasd optuna_research|
//| regime_framework/monitoring/dashboard_web.py, semmi mast nem kell |
//| ott modositani ezen egysegesites miatt.                            |
//+------------------------------------------------------------------+
void WriteHeartbeat()
  {
   string fname = StringFormat("RegimeFramework_heartbeat_%s_%d.txt", _Symbol, InpMagicNumber);
   int handle = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(handle == INVALID_HANDLE)
     {
      Print("⚠️ Heartbeat fajl irasa sikertelen: ", GetLastError());
      return;
     }
   FileWrite(handle, "symbol=" + _Symbol);
   FileWrite(handle, "magic=" + IntegerToString(InpMagicNumber));
   FileWrite(handle, "server_time=" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS));
   FileWrite(handle, "last_bar_time=" + TimeToString(g_lastBarTime, TIME_DATE | TIME_SECONDS));
   FileWrite(handle, "heartbeat_counter=" + IntegerToString((int)g_heartbeatCounter));
   FileWrite(handle, "classifier_ready=" + (CheckPointer(g_classifier) != POINTER_INVALID && g_classifier.IsReady() ? "true" : "false"));
   FileWrite(handle, "open_positions=" + IntegerToString(PositionsTotal()));
   FileWrite(handle, "trade_error_count=" + IntegerToString(g_tradeErrorCount));
   FileWrite(handle, "last_error_msg=" + g_lastErrorMsg);
   FileWrite(handle, "account_equity=" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2));
   FileWrite(handle, "account_margin_free=" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2));
   FileWrite(handle, "market_holiday_today=" + (IsMarketHoliday(_Symbol, DateToYyyymmdd(g_lastBarTime)) ? "true" : "false"));
   FileWrite(handle, "spread_guard_baseline_days=" + IntegerToString(CheckPointer(g_spreadGuard) != POINTER_INVALID ? g_spreadGuard.BaselineDayCount() : 0));
   FileWrite(handle, "current_regime=" + (CheckPointer(g_classifier) != POINTER_INVALID ? g_classifier.TrendBandStr() : "?"));
   FileWrite(handle, "current_vol_band=" + (CheckPointer(g_classifier) != POINTER_INVALID ? g_classifier.VolBandStr() : "?"));
   FileClose(handle);
  }

//+------------------------------------------------------------------+
//| Kereskedesi hiba egyseges kezelese: log + szamlalo + push (ha a   |
//| felhasznalo bekapcsolta a Terminal > Eszkozok > Beallitasok >     |
//| Ertesitesek fulon, es parositva van a MetaTrader mobil appal --   |
//| enelkul a SendNotification() csendben, hiba nelkul nem csinal     |
//| semmit, ezert NEM eleg csak erre tamaszkodni, lasd heartbeat-et). |
//+------------------------------------------------------------------+
void NotifyTradeError(string context, int retcode, string description)
  {
   g_tradeErrorCount++;
   g_lastErrorMsg = context + ": " + IntegerToString(retcode) + " (" + description + ")";
   PrintFormat("⚠️ %s", g_lastErrorMsg);
   SendNotification(StringFormat("RegimeFramework %s: %s hiba (%d)", _Symbol, context, retcode));
  }

//+------------------------------------------------------------------+
//| Ugyanaz, mint NotifyTradeError(), de PUSH ERTESITES NELKUL -- a   |
//| trailing stop modositas (UpdateTrailingStop()) minden baron       |
//| megprobalkozhat, es atmeneti/broker-oldali okokbol (pl. "nincs    |
//| valtozas", "tul kozeli stop") gyakran, artalmatlanul hibazhat --  |
//| ezt push-szal jelezni telefon-spam lenne. A heartbeat fajlban     |
//| (g_tradeErrorCount/g_lastErrorMsg) igy is lathato marad.          |
//+------------------------------------------------------------------+
void LogTradeError(string context, int retcode, string description)
  {
   g_tradeErrorCount++;
   g_lastErrorMsg = context + ": " + IntegerToString(retcode) + " (" + description + ")";
   PrintFormat("⚠️ %s", g_lastErrorMsg);
  }

//+------------------------------------------------------------------+
double NormalizeLot(double lot)
  {
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lot = MathRound(lot / lotStep) * lotStep;
   return MathMax(minLot, MathMin(maxLot, lot));
  }

//+------------------------------------------------------------------+
//| Margin-alapu lot (core/position_sizing.py MarginBasedSizer MQL5   |
//| megfeleloje, 2026-08-23, PRODUCTION_READINESS.md P1 #3):          |
//| a lot a VALOS szabad marginhoz igazodik (AccountInfoDouble         |
//| ACCOUNT_MARGIN_FREE -- NEM equity-kozelites, mint a Python-oldali  |
//| backtest-modell, lasd core/position_sizing.py MarginBasedSizer     |
//| docstring-je), FUGGETLENUL az SL-tavolsagtol. Tobb, parhuzamosan   |
//| futo szimbolum eseten ez ONMAGATOL, koordinacio NELKUL is helyesen |
//| viselkedik: ha egy masik szimbolumnak mar van nyitott pozicioja,   |
//| az ACCOUNT_MARGIN_FREE mar tukrozi az O lekotott marginjat, tehat  |
//| ez a szimbolum automatikusan kisebb lotot szamol.                  |
//|                                                                    |
//| VEDOHALOK (felhasznaloi kovetelmeny: "ne lehessen margin call") -  |
//| ket fix konstans, NEM felhasznaloi input, mert soha nem strategiai |
//| valasztas kerdesei, csak biztonsagi hatarok (lasd a MARGIN_ALLOC_  |
//| SANITY_CEILING_PCT / MIN_SAFE_MARGIN_LEVEL_PCT definicioit fent):  |
//|  1. effectivePct = min(InpMarginAllocPct, MARGIN_ALLOC_SANITY_     |
//|     CEILING_PCT) / 100.0 -- a MathMin csak elgepeles elleni         |
//|     jozan-esz-plafon (mindket ertek szazalekban ertendo), a         |
//|     /100.0 alakitja tortre; a tenyleges "sose lehessen margin call" |
//|     garanciat a 3. pont adja.                                       |
//|  2. Lefele kerekites (FLOOR, nem MathRound!) a lot-lepeskozre --    |
//|     igy a tenyleges margin-igeny SOSEM lepheti at a budget-et a     |
//|     kerekites miatt.                                                |
//|  3. Vegso ellenorzes: ha meg a broker minimum lotja is a            |
//|     MIN_SAFE_MARGIN_LEVEL_PCT ala vinne a margin-szintet, a         |
//|     fuggveny 0.0-t ad vissza -- ez azt jelzi a hivonak, hogy        |
//|     KIHAGYJA a belepest, nem eroltet egy tul kockazatos meretet.    |
//|     FONTOS: ez a margin-call-tol vedi meg a szamlat, de NEM azonos  |
//|     az equity-drawdown korlatozasaval - InpMarginAllocPct-et a      |
//|     sajat, valos szamla-adaton kalibralt ertek fole emelve a DD     |
//|     erdemben nohet, meg akkor is, ha ez a vedohalo tovabbra is      |
//|     aktivan mukodik.                                                |
//+------------------------------------------------------------------+
double CalcMarginBasedLot()
  {
   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double marginPerLot = 0.0;
   if(!OrderCalcMargin(ORDER_TYPE_BUY, _Symbol, 1.0, price, marginPerLot) || marginPerLot <= 0.0)
     {
      Print("⚠️ OrderCalcMargin hiba a margin-alapu meretezesnel -- fix lotra esunk vissza.");
      return NormalizeLot(InpLotSize);
     }

   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double effectivePct = MathMin(InpMarginAllocPct, MARGIN_ALLOC_SANITY_CEILING_PCT) / 100.0;   // % -> tort
   double budget = freeMargin * effectivePct;

   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);

   double rawLot = budget / marginPerLot;
   double lot = MathFloor(rawLot / lotStep) * lotStep;   // FLOOR, sose kerekitsen felfele a budget fole
   lot = MathMax(minLot, MathMin(maxLot, lot));

   double marginNeeded = lot * marginPerLot;
   double marginLevelAfter = (freeMargin > 0.0) ? (freeMargin / marginNeeded * 100.0) : 0.0;
   if(marginNeeded <= 0.0 || marginLevelAfter < MIN_SAFE_MARGIN_LEVEL_PCT)
     {
      PrintFormat("⚠️ Margin-alapu meretezes: meg a min. lot (%.2f) is %.0f%%-os margin-szintet adna "
                  "(kuszob: %.0f%%) -- belepes KIHAGYVA a biztonsag erdekeben.",
                  minLot, marginLevelAfter, MIN_SAFE_MARGIN_LEVEL_PCT);
      return 0.0;
     }
   return lot;
  }

//+------------------------------------------------------------------+
//| true, ha van nyitott poziciónk ezen a szimbolumon/magic-en -      |
//| az ownerTag kimeneti parameterben a POSITION_COMMENT-et adja      |
//| vissza (OWNER_TAG_MR / OWNER_TAG_TF), hogy a hivo eldonthesse,     |
//| melyik komponens "birtokolja" a pozíciot.                          |
//+------------------------------------------------------------------+
bool HasOpenPosition(string &ownerTag)
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;
      ownerTag = PositionGetString(POSITION_COMMENT);
      return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| a mi (szimbolum+magic szerint azonositott) nyitott poziciónk       |
//| MT5-natívan tarolt nyitasi ideje (POSITION_TIME). Ez adja az       |
//| alapot a napvaltas-alapu elsodleges napvegi kenyszerzaras-         |
//| ellenorzeshez -- lasd OnTick() es a fejlec-komment reszletes       |
//| indoklasat. 0-t ad vissza, ha nincs nyitott sajat pozicio.         |
//+------------------------------------------------------------------+
datetime GetMyPositionEntryTime()
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;
      return (datetime)PositionGetInteger(POSITION_TIME);
     }
   return 0;
  }

//+------------------------------------------------------------------+
void CloseMyPositions()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
        {
         if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
           {
            if(!trade.PositionClose(ticket))
               NotifyTradeError("Zaras", trade.ResultRetcode(), trade.ResultRetcodeDescription());
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Poziciónyitas - a sig.slDistance/tpDistance TAVOLSAGOKAT az ELO   |
//| ask/bid-hez keptest alkalmazzuk, NEM a dontesi bazisul hasznalt    |
//| lezart bar close-ahoz kepest (lasd MeanReversion.mqh SSignal       |
//| fejlec-kommentjet).                                                |
//+------------------------------------------------------------------+
void OpenPosition(SSignal &sig, string ownerTag)
  {
   double lot = InpUseMarginBasedSizing ? CalcMarginBasedLot() : NormalizeLot(InpLotSize);
   if(lot <= 0.0)
      return;   // CalcMarginBasedLot() mar logolta az okot -- lasd fuggveny fejlece
   double price, sl, tp;
   bool ok;

   //--- KRITIKUS JAVITAS (2026-09-02, kutatasi EA-k Strategy Tester-es diagnosztikajabol
   //    kiderult hiba): a SL/TP-t a ZARO oldalhoz kell viszonyitani (Bid LONG-nal, mert a
   //    poziciozaras SELL-lel Bid-en tortenik; Ask SHORT-nal), NEM a belepesi oldalhoz -- ha a
   //    spread tagabb, mint a slDistance, a regi szamitas a SL-t a zaro-ar ROSSZ OLDALARA
   //    tehette, amit a szerver "Invalid stops"-szal elutasitott, NEM nyitva meg a megbizast --
   //    ez CSENDBEN kimaradt trade-eket okozott minden komponensnel (MR/TF/LHC/FS egyarant, mert
   //    mind ezt az OpenPosition()-t hivja).
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;

   if(sig.isLong)
     {
      price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double slDist = MathMax(sig.slDistance, minDist);
      sl = NormalizeDouble(bid - slDist, digits);
      tp = (sig.tpDistance > 0.0) ? NormalizeDouble(bid + MathMax(sig.tpDistance, minDist), digits) : 0.0;
      ok = trade.Buy(lot, _Symbol, price, sl, tp, ownerTag);
     }
   else
     {
      price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double slDist = MathMax(sig.slDistance, minDist);
      sl = NormalizeDouble(ask + slDist, digits);
      tp = (sig.tpDistance > 0.0) ? NormalizeDouble(ask - MathMax(sig.tpDistance, minDist), digits) : 0.0;
      ok = trade.Sell(lot, _Symbol, price, sl, tp, ownerTag);
     }

   if(!ok)
      NotifyTradeError("Nyitas (" + ownerTag + ")", trade.ResultRetcode(), trade.ResultRetcodeDescription());
   else if(ownerTag == OWNER_TAG_TF)
      g_trendExtreme = price;   // a trailing stop kezdeti "trend_extreme"-je, lasd check_exit()
   else if(ok && ownerTag == OWNER_TAG_FS)
     {
      g_fsEntryTime = g_lastBarTime;
      g_fsEntryDay = DayStart(g_lastBarTime);
     }
  }

//+------------------------------------------------------------------+
//| true, ha a FridayShort-pozicio tartasi ideje (InpFsHoldBars) mar  |
//| eltelt, VAGY a naptari nap valtozott az entry ota - a KORABBI     |
//| felteteleket vesszuk (lasd FridayShort.mqh fejlec-kommentjet:     |
//| ugyanaz a nap-hatar-korlatozas, mint a Python komponensben).      |
//+------------------------------------------------------------------+
bool IsFsHoldEnd(datetime barTime)
  {
   long barsElapsed = (long)((barTime - g_fsEntryTime) / PeriodSeconds());
   bool dayChanged = (DayStart(barTime) != g_fsEntryDay);
   return (barsElapsed >= InpFsHoldBars) || dayChanged;
  }

//+------------------------------------------------------------------+
//| true, ha elertuk/tulleptuk az InpFsSafetyCloseHour:Minute idot    |
//| (szerveridő) -- a TimeCurrent()-et hasznalja, NEM a bar-idot,      |
//| hogy MINDEN ticken kiertekelheto legyen, ne csak uj baron.        |
//| SZUKSEGES, mert a pénteki bróker Trade session korabban zar, mint |
//| ahogy a nagy InpFsHoldBars vagy a nap-hatar-ellenorzes egyaltalan  |
//| eszlelhetne a valtast -- hetvegen nincs quote, tehat nincs uj bar |
//| es nincs OnTick-hivas sem, amíg a piac hetfon ujra nem nyit.       |
//+------------------------------------------------------------------+
bool IsFsSafetyCloseTime()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.hour > InpFsSafetyCloseHour)
      return true;
   return (dt.hour == InpFsSafetyCloseHour && dt.min >= InpFsSafetyCloseMinute);
  }

//+------------------------------------------------------------------+
//| Trailing stop frissitese a TrendFollowing altal nyitott pozicion  |
//| - a stop CSAK szigorulhet (sosem lazul), ugyanaz a szabaly, mint  |
//| a Python check_exit()-ben (TrendFollowingComponent.check_exit()). |
//+------------------------------------------------------------------+
void UpdateTrailingStop(double atr)
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;
      if(PositionGetString(POSITION_COMMENT) != OWNER_TAG_TF)
         continue;   // csak a TrendFollowing-poziciora vonatkozik

      bool isLong = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double currentSl = PositionGetDouble(POSITION_SL);
      double high1 = iHigh(_Symbol, PERIOD_CURRENT, 1);
      double low1  = iLow(_Symbol, PERIOD_CURRENT, 1);

      //--- [Invalid stops] vedelem (2026-09-02, lasd OpenPosition() fejlec-kommentjet a teljes
      //    indoklasert): normalizalas + min. stop-tavolsag ellenorzese a modositas elott, hogy a
      //    szerver-oldali kerekites vagy a broker minimalis tavolsaga ne dobjon csendes hibat.
      int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
      double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
      double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;

      if(isLong)
        {
         g_trendExtreme = MathMax(g_trendExtreme, high1);
         double trailSl = NormalizeDouble(g_tfComponent.ComputeTrailSl(true, g_trendExtreme, atr), digits);
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         if(trailSl > currentSl && (bid - trailSl) >= minDist
            && !trade.PositionModify(ticket, trailSl, PositionGetDouble(POSITION_TP)))
            LogTradeError("Trailing modositas", trade.ResultRetcode(), trade.ResultRetcodeDescription());
        }
      else
        {
         g_trendExtreme = MathMin(g_trendExtreme, low1);
         double trailSl = NormalizeDouble(g_tfComponent.ComputeTrailSl(false, g_trendExtreme, atr), digits);
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         if(trailSl < currentSl && (trailSl - ask) >= minDist
            && !trade.PositionModify(ticket, trailSl, PositionGetDouble(POSITION_TP)))
            LogTradeError("Trailing modositas", trade.ResultRetcode(), trade.ResultRetcodeDescription());
        }
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   //--- FridayShort biztonsagi zaras -- EZ MINDEN ticken fut, MEG a "csak uj baron dontunk" kapu
   //    ELOTT, mert a bar-only kapu heten hetvegen (nincs quote -> nincs uj bar -> nincs OnTick-
   //    logika) nem tudna idoben eszlelni a bróker Trade-session-veget -- lasd IsFsSafetyCloseTime()
   //    fejlec-kommentjet ---
   string fsOwnerTag = "";
   if(HasOpenPosition(fsOwnerTag) && fsOwnerTag == OWNER_TAG_FS && IsFsSafetyCloseTime())
     {
      CloseMyPositions();
      return;
     }

   //--- csak uj gyertya nyitasakor dontunk, ne minden tick-en ---
   datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(barTime == g_lastBarTime)
      return;
   g_lastBarTime = barTime;
   g_heartbeatCounter++;
   WriteHeartbeat();   // minden uj baron irjuk -- meg bemelegedes alatt is (lasd fuggveny fejlece)

   //--- spread-anomalia bazis frissitese MINDEN uj baron, meg a rezsim-osztalyozo bemelegedese
   //    alatt is (lasd SpreadAnomalyGuard.mqh) -- fuggetlen a lenti regimeReady kaputol.
   double currentSpread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   g_spreadGuard.OnNewBar(currentSpread, barTime);

   datetime today = DayStart(barTime);
   if(today != g_currentTradingDay)
     {
      g_currentTradingDay = today;
      g_tradeTakenToday = false;
      g_fsExceptionUsedToday = false;
      g_entryBlockNotifiedToday = false;
     }

   //--- rezsim-besorolas a MAR LEZART (elozo) bar-on - a klasszifikator sajat maga tartja a
   //    gordulo allapotat, csak az uj OHLC-t kell atadni neki minden lezart baron ---
   double high1  = iHigh(_Symbol, PERIOD_CURRENT, 1);
   double low1   = iLow(_Symbol, PERIOD_CURRENT, 1);
   double close1 = iClose(_Symbol, PERIOD_CURRENT, 1);

   bool regimeReady = g_classifier.OnNewBar(high1, low1, close1);
   if(!regimeReady)
      return;   // meg bemelegszik a ~8640-baros gordulo ablak

   MqlDateTime dt;
   TimeToStruct(barTime, dt);
   int h = dt.hour;
   int m = dt.min;
   // MQL5 day_of_week: 0=Vasarnap...6=Szombat -- pandas-konvenciora (0=Hetfo...6=Vasarnap)
   // atvaltva, hogy a FridayShort alapertekei (targetDayOfWeek=4) mindket oldalon Pentek-et
   // jelentsenek -- lasd FridayShort.mqh fejlec-kommentjet.
   int dow = (dt.day_of_week + 6) % 7;

   //--- HIBAJAVITAS (2026-09-22, Python-parity audit): a MeanReversion/TrendFollowing
   //    IsSessionHour()-je a Python check_entry()-vel egyezoen a DONTES BAZISAUL hasznalt bar
   //    (a mar lezart bar[1], amelynek close-at `close1`-kent atadjuk) SAJAT nyitasi idejet varja,
   //    NEM a most-indulo bar[0] idejet (`h`/`m` fent) -- a Python `ctx.hour/minute` mindig
   //    ugyanannak a sornak (bar-nak) a sajat "time" oszlopabol jon, mint amelyiknek a close-at
   //    teszteli (lasd components/mean_reversion.py prepare_indicators()/validate()). Eddig `h`/`m`
   //    (bar[0] ideje) ment at `close1`-gyel (bar[1] close-a) parban, ami a session-ablakot bar-ral
   //    (M10-en 10 perccel) korabbra tolta el a validalt Python viselkedeshez kepest -- a nap elso
   //    bar-ja igy tulzottan korabban vult beengedve, az utolso pedig kimaradt. A tobbi hivo (LHC/
   //    FridayShort/EOD-kenyszerzaras) SZANDEKOSAN a bar[0]-idot hasznalja (hatarido-jellegu
   //    ellenorzesek, lasd LastHourContinuation.mqh fejlec-kommentjet), azokat ez nem erinti.
   datetime closedBarTime = iTime(_Symbol, PERIOD_CURRENT, 1);
   MqlDateTime dt1;
   TimeToStruct(closedBarTime, dt1);
   int h1 = dt1.hour;
   int m1 = dt1.min;

   double atr = g_classifier.LastAtr();
   ETrendBand trendBand = g_classifier.TrendBand();

   string ownerTag = "";
   bool inPosition = HasOpenPosition(ownerTag);

   //--- a LastHourContinuation SAJAT, a tobbi komponensnel korabbi zarasi hatarideje (lasd
   //    LastHourContinuation.mqh IsSessionEndBar()) - EZ ELOBB fut le, mint az altalanos
   //    napvegi kenyszerzaras, mert ez egy szukebb, komponens-specifikus szabaly ---
   if(inPosition && ownerTag == OWNER_TAG_LHC && g_lhcComponent.IsSessionEndBar(h, m))
     {
      CloseMyPositions();
      return;
     }

   //--- a FridayShort SAJAT, hold_bars/nap-hatar-alapu zarasi szabalya - ELOBB fut le, mint az
   //    altalanos napvegi kenyszerzaras, mert az entry (InpFsTargetHour=23) egybeeshet az
   //    altalanos InpForceCloseHour kuszobbel, es akkor a pozicio egyetlen bar utan zarna -
   //    lasd IsFsHoldEnd() fejlec-kommentjet ---
   if(inPosition && ownerTag == OWNER_TAG_FS && IsFsHoldEnd(barTime))
     {
      CloseMyPositions();
      return;
     }

   //--- napvegi kenyszerzaras (MR/TF/LHC-re; a FridayShort-ot a sajat, fenti szabalya kezeli) ---
   //| ELSODLEGES vedelem: a pozicio tenyleges (MT5-natívan tarolt) nyitasi NAPJAT hasonlitjuk a  |
   //| mai naphoz -- ha eltero, AZONNAL zarunk, fuggetlenul az orától (lasd fajl fejlec-komment,  |
   //| miert nem eleg onmagaban a masodlagos `h >= InpForceCloseHour` ora-kuszob). A FridayShort-ot|
   //| ez NEM erinti (lasd `ownerTag != OWNER_TAG_FS`, valtozatlan).                               |
   datetime myEntryTime = GetMyPositionEntryTime();
   bool dayChanged = (myEntryTime > 0 && DayStart(myEntryTime) != today);
   // perc-pontos ora-kuszob (lasd InpForceCloseMinute fejlec-kommentjet) -- ugyanaz a minta, mint
   // az IsFsSafetyCloseTime()-nal.
   bool forceCloseTimeReached = (h > InpForceCloseHour) ||
                                 (h == InpForceCloseHour && m >= InpForceCloseMinute);
   if(inPosition && ownerTag != OWNER_TAG_FS && (dayChanged || forceCloseTimeReached))
     {
      CloseMyPositions();
      return;
     }

   if(inPosition)
     {
      if(ownerTag == OWNER_TAG_TF)
         UpdateTrailingStop(atr);
      return;   // mar van pozicio - a MeanReversion/LastHourContinuation SL-jet innentol a
                // broker natívan kezeli
     }

   //--- ÚJ BELEPES-KAPU: naptari unnepnap (MarketHolidays.mqh) VAGY rendellenesen szeles spread
   //    (SpreadAnomalyGuard.mqh) VAGY tavoli (dashboard) leallitas eseten ÚJ pozíciot NEM nyitunk
   //    -- lasd a ket .mqh fajl fejlec-kommentjet, illetve g_controlFileName fejlec-kommentjet a
   //    tavoli-leallitas indoklasaert. A MEGLEVO poziciok kezelese (fentebb, UpdateTrailingStop/
   //    kenyszerzaras) EZT A KAPUT NEM erinti, azon mar tulment a fuggveny. ---
   bool isHoliday        = IsMarketHoliday(_Symbol, DateToYyyymmdd(barTime));
   bool isSpreadAnomaly   = g_spreadGuard.IsAnomalous(currentSpread);
   bool isRemoteDisabled  = FileIsExist(g_controlFileName, FILE_COMMON);
   bool entriesBlocked    = isHoliday || isSpreadAnomaly || isRemoteDisabled;

   if(entriesBlocked)
     {
      if(!g_entryBlockNotifiedToday)
        {
         g_entryBlockNotifiedToday = true;
         string reason = isHoliday ? "piaci unnepnap" :
                          isRemoteDisabled ? "tavoli leallitas (dashboard)" :
                          StringFormat("rendellenes spread (aktualis=%.1f pont, bazis-median=%.1f pont, %d napos bazison)",
                                       currentSpread, g_spreadGuard.BaselineMedian(), g_spreadGuard.BaselineDayCount());
         PrintFormat("⏸️ %s: ÚJ belepesek kihagyva ma -- %s.", _Symbol, reason);
         SendNotification(StringFormat("RegimeFramework %s: belepesek kihagyva ma (%s)", _Symbol, reason));
        }
     }
   else if(!g_tradeTakenToday)
     {
      //--- XOR-dispatch a trend_band alapjan, ugyanaz a mintazat, mint a Python
      //    Engine._select_component()-je (core/engine.py) ---
      SSignal sig;
      sig.hasSignal = false;

      if(trendBand == TREND_RANGING && InpEnableMeanReversion)
        {
         sig = g_mrComponent.CheckEntry(h1, m1, trendBand, close1, atr);
         if(sig.hasSignal)
           {
            g_tradeTakenToday = true;
            OpenPosition(sig, OWNER_TAG_MR);
           }
        }
      else if(trendBand == TREND_TRENDING && InpEnableTrendFollowing)
        {
         sig = g_tfComponent.CheckEntry(h1, m1, trendBand, close1, atr);
         if(sig.hasSignal)
           {
            g_tradeTakenToday = true;
            OpenPosition(sig, OWNER_TAG_TF);
           }
        }
      //--- InpEnableMeanReversion/InpEnableTrendFollowing = false -- lasd fenti input-csoport --
      //    eseten a megfelelo ag egyszeruen kimarad, `sig.hasSignal` false marad, es a lentebbi
      //    time_gated (LastHourContinuation) dispatch ugyanugy esely kap, mintha a rendes
      //    trend_band-komponens NEM jelzett volna ezen a baron (lasd core/engine.py Python-oldali
      //    megfeleloje: `_select_component()` None-t ad vissza, ha nincs aktiv komponens).
      //--- TREND_TRANSITIONAL: szandekosan "ne kereskedj" zona a rendes komponenseknek (lasd
      //    PLAN.md 2.2, a whipsaw-zona tudatos kihagyasa) ---

      //--- time_gated dispatch: CSAK akkor probalkozik, ha a rendes trend_band-komponens ezen a
      //    baron NEM jelzett (barmilyen okbol - nincs is ilyen komponens az adott trend_band-hez,
      //    vagy volt, de a sajat feltetele nem teljesult) - lasd core/engine.py modul-docstringjet,
      //    ugyanaz az elsobbsegi sorrend, mint a Python Engine.run()-ban ---
      if(!sig.hasSignal && InpEnableLastHourContinuation)
        {
         sig = g_lhcComponent.CheckEntry(h, m, atr);
         if(sig.hasSignal)
           {
            g_tradeTakenToday = true;
            OpenPosition(sig, OWNER_TAG_LHC);
           }
        }
     }
   else if(!g_fsExceptionUsedToday && InpEnableFridayShort)
     {
      //--- a normal napi kvota MAR elfogyott ezen a napon -- csak a FridayShort kvota-KIVETEL
      //    probalkozhat, legfeljebb egyszer naponta - lasd core/engine.py
      //    quota_exempt_time_gated_components dokumentaciojat ---
      SSignal fsSig = g_fsComponent.CheckEntry(dow, h, m, atr);
      if(fsSig.hasSignal)
        {
         g_fsExceptionUsedToday = true;
         OpenPosition(fsSig, OWNER_TAG_FS);
        }
     }
  }
//+------------------------------------------------------------------+
