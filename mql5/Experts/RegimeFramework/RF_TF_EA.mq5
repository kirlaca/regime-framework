//+------------------------------------------------------------------+
//| RF_TF_EA.mq5 -- TISZTA TrendFollowing EA (v1.00, 2026-09-28)       |
//|                                                                    |
//| A RegimeFramework_EA_M10_10d v2.01 (MQL5-repo f4d2853, kiadva:     |
//| production/releases/ea/RegimeFramework_EA_M10_10d/v2.01_2026-09-22)|
//| csak-TF leszarmazottja. Az elo V2 konfiguracio (MR/LHC/FS = false) |
//| viselkedeset adja 1:1-ben, a tobbi komponens es a routing NELKUL:  |
//|  - TrendFollowing.mqh (VALTOZATLAN), belepes csak TREND_TRENDING-  |
//|    ben (RegimeClassifier_M10_10d.mqh, 1320 bar, VALTOZATLAN);      |
//|  - napi 1 kotes; munkamenet-ellenorzes a lezart bar[1] idejevel     |
//|    (a v2.01 javitas); kenyszerzaras 23:49 + nap-valtas; trailing   |
//|    bar-onkent, csak szigorodhat;                                   |
//|  - MarketHolidays / SpreadAnomalyGuard / tavoli control-fajl /     |
//|    heartbeat (VALTOZATLAN formatum) / SendNotification;            |
//|  - azonos input-nevek, magic (101001) es comment-tag (RF_TF) --    |
//|    a signal copier es a monitor valtozatlanul mukodik.             |
//| KIKERULT: MeanReversion, LastHourContinuation, FridayShort,        |
//| komponens-routing, margin-alapu meretezes. Meretezes: fix          |
//| InpLotSize (felhasznaloi dontes 2026-09-28: negyedeves kezi        |
//| igazitas az arszinthez).                                           |
//|                                                                    |
//| DOKUMENTALT ELTERESEK a v2.01-tol (regime_framework_2/FINDINGS_LOG |
//| „Tiszta TF EA”):                                                   |
//|  C4 -- a napi zaszlo CSAK SIKERES nyitas utan all be (a v2.01 a    |
//|        nyitas ELOTT allitotta -> sikertelen nyitasnal aznap nem     |
//|        probalkozott ujra). Vedohalo: legfeljebb                     |
//|        MAX_OPEN_ATTEMPTS_PER_DAY sikertelen kiserlet naponta.        |
//|  C5 -- OnInit-kor a napi zaszlo az aznapi deal-historybol          |
//|        rekonstrualva (a v2.01 ujrainditaskor false-ra allitotta ->  |
//|        aznap masodik kotes lehetett).                              |
//|  C6 -- OnInit-kor a nyitott TF-pozicio trailing-extremuma          |
//|        rekonstrualva: max(nyitasi ar, high[belepesi bar..bar[1]]) / |
//|        min(..., low[...]) (a v2.01-ben 0 maradt -> SHORT-nal a      |
//|        trailing orokre befagyott).                                 |
//|        J1: nyitott pozicio mellett a zaszlo mindig true (a „hibaval |
//|        jelentett, de kitoltott” megbizas esetere).                 |
//|  C7 -- a bemelegites utan az elso OnTick NEM adja at ujra a mar     |
//|        betoltott bar[1]-et az osztalyozonak (a v2.01-ben minden     |
//|        indulaskor egy bar KETSZER kerult a 1320-as ablakba).        |
//|        A Strategy Tester ELSO ~1320 bar-jan (bemelegites) ezert     |
//|        a v2.01-gyel valo osszevetesbol ki kell hagyni az elejet.    |
//|                                                                    |
//| TESZT-INPUTOK (CSAK Strategy Testerben hatasosak, elesben          |
//| figyelmen kivul maradnak): InpTestFailFirstOpen (C4),              |
//| InpTestReinitAt (C5/C6/C7 -- szimulalt ujrainditas).               |
//+------------------------------------------------------------------+
#property copyright "RF_TF_EA (tiszta TrendFollowing, a RegimeFramework_EA_M10_10d v2.01-bol)"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include "RegimeClassifier_M10_10d.mqh"   // ELSOKENT -- hogy a TrendFollowing.mqh/MeanReversion.mqh
                                           // "#include RegimeClassifier.mqh" sora ne huzza be a 8640-es valtozatot
#include "TrendFollowing.mqh"             // (a MeanReversion.mqh-t csak az SSignal struct miatt huzza be)
#include "MarketHolidays.mqh"
#include "SpreadAnomalyGuard.mqh"

CTrade trade;

input group "=== TrendFollowing parameterek (az elo V2 ertekei -- .set-bol felulirhato) ==="
input double InpTfFastEmaDays        = 1.4213259014544624;
input double InpTfSlowEmaDays        = 2.2214437598322476;
input double InpTfSlAtrMultiplier    = 2.8097032156200794;
input double InpTfTrailAtrMultiplier = 3.388832537439072;
input double InpTfRsiLongMin         = 76.66752227906817;
input double InpTfRsiShortMax        = 57.88696992297191;
input int    InpTfRsiPeriod          = 14;
input int    InpTfBollingerPeriod    = 39;
input double InpTfBollingerK         = 2.8713829985073884;
input int    InpTfBarsPerDay         = 144;

input group "=== Session / kockazatkezeles (az elo V2 ertekei) ==="
input int    InpSessionStartHour   = 16;
input int    InpSessionStartMinute = 30;
input int    InpSessionEndHour     = 21;
input int    InpForceCloseHour     = 23;
input int    InpForceCloseMinute   = 49;
input double InpLotSize            = 0.3;     // negyedevente kezzel igazitva az arszinthez (FINDINGS_LOG 2026-09-28)
input int    InpSlippagePoints     = 20;
input int    InpMagicNumber        = 101001;

input group "=== TESZT (csak Strategy Testerben hatasos) ==="
input bool     InpTestFailFirstOpen = false;   // C4-teszt: az elso nyitasi kiserlet szandekosan sikertelen
input datetime InpTestReinitAt      = 0;       // C5/C6/C7-teszt: az ezutani elso uj baron szimulalt ujrainditas (0 = ki)

#define OWNER_TAG_TF               "RF_TF"
#define MAX_OPEN_ATTEMPTS_PER_DAY  3

//--- globalis allapot
CMarketConditionClassifier *g_classifier  = NULL;
CTrendFollowingComponent   *g_tfComponent = NULL;
CSpreadAnomalyGuard        *g_spreadGuard = NULL;

string   g_controlFileName          = "";
datetime g_lastBarTime              = 0;
datetime g_lastClassifiedBarTime    = 0;     // C7: az osztalyozonak utoljara atadott bar ideje
datetime g_currentTradingDay        = 0;
bool     g_tradeTakenToday          = false;
int      g_failedOpenAttemptsToday  = 0;     // C4 vedohalo
double   g_trendExtreme             = 0.0;
bool     g_entryBlockNotifiedToday  = false;
bool     g_testFailUsed             = false;
bool     g_testReinitDone           = false;

long     g_heartbeatCounter = 0;
int      g_tradeErrorCount  = 0;
string   g_lastErrorMsg     = "";

//+------------------------------------------------------------------+
datetime DayStart(datetime t) { return t - (t % 86400); }

bool IsTester() { return (bool)MQLInfoInteger(MQL_TESTER); }

//+------------------------------------------------------------------+
//| Osztalyozo bemelegitese a chart historikus adataibol (v2.01-gyel   |
//| azonos) + C7: az utolso betoltott bar idejet megjegyezzuk.        |
//+------------------------------------------------------------------+
bool BackfillClassifier()
  {
   int needed = REGIME_ROLLING_WINDOW_BARS + REGIME_TR_DM_PERIOD * 2 + 5;
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(_Symbol, PERIOD_CURRENT, 1, needed, rates);
   if(copied <= 0)
     {
      PrintFormat("⚠️ Nem sikerult historikus adatot lekerni a bemelegiteshez (hiba: %d).", GetLastError());
      return false;
     }
   for(int i = 0; i < copied; i++)
      g_classifier.OnNewBar(rates[i].high, rates[i].low, rates[i].close);
   g_lastClassifiedBarTime = rates[copied - 1].time;
   PrintFormat("Rezsim-osztalyozo bemelegitve %d historikus baron (kert: %d) -- keszen all: %s",
               copied, needed, g_classifier.IsReady() ? "IGEN" : "NEM");
   return true;
  }

//+------------------------------------------------------------------+
//| C5: volt-e ma mar (szerver-napkezdettol) belepo deal ezen a        |
//| szimbolumon/magic-en.                                              |
//+------------------------------------------------------------------+
bool TradeTakenTodayFromHistory(datetime dayStart)
  {
   if(!HistorySelect(dayStart, TimeCurrent() + 60))
      return false;
   int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
     {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
         continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber)
         continue;
      if(HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_IN)
         continue;
      if((datetime)HistoryDealGetInteger(deal, DEAL_TIME) >= dayStart)
         return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| C6: a nyitott TF-pozicio trailing-extremumanak rekonstrukcioja.   |
//| A zavartalan futas: nyitaskor extremum = nyitasi ar, majd minden  |
//| uj baron a lezart bar[1] high/low-javal frissul -- ebbe a belepesi |
//| bar is beletartozik. Itt ugyanez visszamenoleg.                    |
//+------------------------------------------------------------------+
void RestoreTrendExtreme()
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;
      if(PositionGetString(POSITION_COMMENT) != OWNER_TAG_TF)
         continue;
      bool isLong = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double extreme = PositionGetDouble(POSITION_PRICE_OPEN);
      int entryShift = iBarShift(_Symbol, PERIOD_CURRENT, (datetime)PositionGetInteger(POSITION_TIME), false);
      if(entryShift < 0)
         PrintFormat("⚠️ C6: a belepesi bar nem talalhato (iBarShift=-1) -- a trailing-extremum csak a nyitasi arbol indul.");
      for(int s = entryShift; s >= 1; s--)
         extreme = isLong ? MathMax(extreme, iHigh(_Symbol, PERIOD_CURRENT, s))
                          : MathMin(extreme, iLow(_Symbol, PERIOD_CURRENT, s));
      g_trendExtreme = extreme;
      PrintFormat("TF-pozicio orokbefogadva (%s): trailing-extremum = %.2f (belepesi bar shift %d)",
                  isLong ? "LONG" : "SHORT", extreme, entryShift);
      return;
     }
  }

//+------------------------------------------------------------------+
//| Az indulaskori allapot felepitese -- OnInit es a szimulalt         |
//| ujrainditas (InpTestReinitAt) UGYANEZT az utat hasznalja.          |
//+------------------------------------------------------------------+
void InitState()
  {
   if(CheckPointer(g_classifier) == POINTER_DYNAMIC)
      delete g_classifier;
   g_classifier = new CMarketConditionClassifier();
   BackfillClassifier();
   if(CheckPointer(g_spreadGuard) == POINTER_DYNAMIC)   // J2: a spread-guard is az ujrainditasi uton epul fel
      delete g_spreadGuard;
   g_spreadGuard = new CSpreadAnomalyGuard();
   g_spreadGuard.Backfill(_Symbol, PERIOD_CURRENT);

   g_lastBarTime = 0;
   g_trendExtreme = 0.0;
   g_failedOpenAttemptsToday = 0;
   g_entryBlockNotifiedToday = false;
   g_currentTradingDay = DayStart(TimeCurrent());
   g_tradeTakenToday = TradeTakenTodayFromHistory(g_currentTradingDay);   // C5
   RestoreTrendExtreme();                                                  // C6
   PrintFormat("Allapot felepitve: nap=%s, mai kotes volt: %s",
               TimeToString(g_currentTradingDay, TIME_DATE), g_tradeTakenToday ? "IGEN" : "NEM");
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);

   g_tfComponent = new CTrendFollowingComponent(InpTfFastEmaDays, InpTfSlowEmaDays, InpTfSlAtrMultiplier,
                                                InpTfTrailAtrMultiplier, InpTfRsiLongMin, InpTfRsiShortMax,
                                                InpTfBarsPerDay, InpTfRsiPeriod, InpTfBollingerPeriod, InpTfBollingerK,
                                                InpSessionStartHour, InpSessionStartMinute, InpSessionEndHour);
   g_controlFileName = StringFormat("RegimeFramework_control_%s_%d.txt", _Symbol, InpMagicNumber);

   InitState();

   PrintFormat("RF_TF_EA v1.00 elindult. Symbol=%s, Period=%s, Magic=%d, Lot=%.2f",
               _Symbol, EnumToString((ENUM_TIMEFRAMES)Period()), InpMagicNumber, InpLotSize);
   if(!g_classifier.IsReady())
      PrintFormat("FIGYELEM: a rezsim-osztalyozo a bemelegites utan sem kesz (kb. %d bar kell). Addig NEM kereskedik.",
                  REGIME_ROLLING_WINDOW_BARS);
   if(!IsTester() && (InpTestFailFirstOpen || InpTestReinitAt > 0))
      Print("FIGYELEM: teszt-input beallitva, de elesben HATASTALAN (csak Strategy Testerben mukodik).");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(CheckPointer(g_classifier) == POINTER_DYNAMIC)
      delete g_classifier;
   if(CheckPointer(g_tfComponent) == POINTER_DYNAMIC)
      delete g_tfComponent;
   if(CheckPointer(g_spreadGuard) == POINTER_DYNAMIC)
      delete g_spreadGuard;
  }

//+------------------------------------------------------------------+
//| Heartbeat -- a v2.01-gyel AZONOS fajlnev es mezok (a dashboard     |
//| ezt olvassa, lasd regime_framework/monitoring/dashboard_web.py).   |
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
void NotifyTradeError(string context, int retcode, string description)
  {
   g_tradeErrorCount++;
   g_lastErrorMsg = context + ": " + IntegerToString(retcode) + " (" + description + ")";
   PrintFormat("⚠️ %s", g_lastErrorMsg);
   SendNotification(StringFormat("RF_TF_EA %s: %s hiba (%d)", _Symbol, context, retcode));
  }

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

void CloseMyPositions()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket)
         && PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
        {
         if(!trade.PositionClose(ticket))
            NotifyTradeError("Zaras", trade.ResultRetcode(), trade.ResultRetcodeDescription());
        }
     }
  }

//+------------------------------------------------------------------+
//| Nyitas -- SL a ZARO oldalhoz (Bid LONG / Ask SHORT), mint a v2.01. |
//| true = sikeres nyitas (C4: a hivo csak ekkor allitja a zaszlot).   |
//+------------------------------------------------------------------+
bool OpenPosition(SSignal &sig)
  {
   if(IsTester() && InpTestFailFirstOpen && !g_testFailUsed)
     {
      g_testFailUsed = true;
      NotifyTradeError("Nyitas (" + OWNER_TAG_TF + ") [TESZT: szandekos hiba]", 0, "C4 teszt");
      return false;
     }
   double lot = NormalizeLot(InpLotSize);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   double price, sl;
   bool ok;
   if(sig.isLong)
     {
      price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      sl = NormalizeDouble(bid - MathMax(sig.slDistance, minDist), digits);
      ok = trade.Buy(lot, _Symbol, price, sl, 0.0, OWNER_TAG_TF);
     }
   else
     {
      price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      sl = NormalizeDouble(ask + MathMax(sig.slDistance, minDist), digits);
      ok = trade.Sell(lot, _Symbol, price, sl, 0.0, OWNER_TAG_TF);
     }
   if(!ok)
     {
      NotifyTradeError("Nyitas (" + OWNER_TAG_TF + ")", trade.ResultRetcode(), trade.ResultRetcodeDescription());
      return false;
     }
   g_trendExtreme = price;   // a trailing kezdeti extremuma (v2.01-gyel azonos)
   return true;
  }

//+------------------------------------------------------------------+
//| Trailing stop -- csak szigorodhat (v2.01-gyel azonos).            |
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
         continue;

      bool isLong = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double currentSl = PositionGetDouble(POSITION_SL);
      double high1 = iHigh(_Symbol, PERIOD_CURRENT, 1);
      double low1  = iLow(_Symbol, PERIOD_CURRENT, 1);
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
   datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(barTime == g_lastBarTime)
      return;

   //--- C5/C6/C7-teszt: szimulalt ujrainditas (CSAK Testerben) -- ugyanaz az InitState(), mint OnInit-kor
   if(IsTester() && InpTestReinitAt > 0 && !g_testReinitDone && barTime >= InpTestReinitAt)
     {
      g_testReinitDone = true;
      PrintFormat("[TESZT] szimulalt ujrainditas a %s baron", TimeToString(barTime));
      InitState();
     }

   g_lastBarTime = barTime;
   g_heartbeatCounter++;
   WriteHeartbeat();

   double currentSpread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   g_spreadGuard.OnNewBar(currentSpread, barTime);

   datetime today = DayStart(barTime);
   if(today != g_currentTradingDay)
     {
      g_currentTradingDay = today;
      g_tradeTakenToday = false;
      g_failedOpenAttemptsToday = 0;
      g_entryBlockNotifiedToday = false;
     }

   //--- rezsim-besorolas a lezart bar[1]-en; C7: egy bar csak egyszer kerulhet az ablakba
   datetime closedBarTime = iTime(_Symbol, PERIOD_CURRENT, 1);
   double high1  = iHigh(_Symbol, PERIOD_CURRENT, 1);
   double low1   = iLow(_Symbol, PERIOD_CURRENT, 1);
   double close1 = iClose(_Symbol, PERIOD_CURRENT, 1);
   if(closedBarTime > g_lastClassifiedBarTime)
     {
      g_classifier.OnNewBar(high1, low1, close1);
      g_lastClassifiedBarTime = closedBarTime;
     }
   if(!g_classifier.IsReady())
      return;

   MqlDateTime dt;
   TimeToStruct(barTime, dt);
   int h = dt.hour;
   int m = dt.min;
   MqlDateTime dt1;
   TimeToStruct(closedBarTime, dt1);   // a munkamenet-ellenorzes a dontesi bar SAJAT idejevel (v2.01)

   double atr = g_classifier.LastAtr();
   ETrendBand trendBand = g_classifier.TrendBand();

   string ownerTag = "";
   bool inPosition = HasOpenPosition(ownerTag);

   //--- napvegi kenyszerzaras: nap-valtas (elsodleges) VAGY InpForceCloseHour:Minute (masodlagos)
   datetime myEntryTime = GetMyPositionEntryTime();
   bool dayChanged = (myEntryTime > 0 && DayStart(myEntryTime) != today);
   bool forceCloseTimeReached = (h > InpForceCloseHour) || (h == InpForceCloseHour && m >= InpForceCloseMinute);
   if(inPosition && (dayChanged || forceCloseTimeReached))
     {
      CloseMyPositions();
      return;
     }

   if(inPosition)
     {
      g_tradeTakenToday = true;   // J1: ha a nyitas „sikertelennek” jelentve, de valojaban kitoltodott, a zaszlo itt all be
      if(ownerTag == OWNER_TAG_TF)
         UpdateTrailingStop(atr);
      return;
     }

   //--- belepes-kapu: unnepnap / spread-anomalia / tavoli leallitas (v2.01-gyel azonos)
   bool isHoliday       = IsMarketHoliday(_Symbol, DateToYyyymmdd(barTime));
   bool isSpreadAnomaly = g_spreadGuard.IsAnomalous(currentSpread);
   bool isRemoteDisabled = FileIsExist(g_controlFileName, FILE_COMMON);
   if(isHoliday || isSpreadAnomaly || isRemoteDisabled)
     {
      if(!g_entryBlockNotifiedToday)
        {
         g_entryBlockNotifiedToday = true;
         string reason = isHoliday ? "piaci unnepnap" :
                         isRemoteDisabled ? "tavoli leallitas (dashboard)" :
                         StringFormat("rendellenes spread (aktualis=%.1f pont, bazis-median=%.1f pont, %d napos bazison)",
                                      currentSpread, g_spreadGuard.BaselineMedian(), g_spreadGuard.BaselineDayCount());
         PrintFormat("⏸️ %s: ÚJ belepesek kihagyva ma -- %s.", _Symbol, reason);
         SendNotification(StringFormat("RF_TF_EA %s: belepesek kihagyva ma (%s)", _Symbol, reason));
        }
      return;
     }

   if(g_tradeTakenToday || g_failedOpenAttemptsToday >= MAX_OPEN_ATTEMPTS_PER_DAY)
      return;

   SSignal sig = g_tfComponent.CheckEntry(dt1.hour, dt1.min, trendBand, close1, atr);
   if(!sig.hasSignal)
      return;
   if(OpenPosition(sig))
      g_tradeTakenToday = true;          // C4: csak SIKERES nyitas utan
   else
      g_failedOpenAttemptsToday++;
  }
//+------------------------------------------------------------------+
