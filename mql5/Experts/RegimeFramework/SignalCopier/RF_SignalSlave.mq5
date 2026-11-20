//+------------------------------------------------------------------+
//| RF_SignalSlave.mq5                                     v1.11      |
//| A KOVETO (slave) terminalban fut. NEM hoz sajat kereskedesi       |
//| dontest: a referencia (master) terminal RF_SignalPublisher-e      |
//| altal a kozos (FILE_COMMON) mappaba irt pillanatkepet koveti:     |
//|   - uj master-pozicio  -> nyit (sajat lot, sajat arhoz igazitott  |
//|     SL/TP, a master pozicio komment-jevel = RF_MR/RF_TF/...);      |
//|   - master SL-modositas (pl. TF trailing) -> SL kovetese;          |
//|   - master zart -> zar.                                            |
//| Lasd README.md (tervezesi dontesek, 2026-09-24/25).                |
//|                                                                    |
//| KET UZEMMOD (v1.10, 2026-09-25, felhasznaloi keres):               |
//|   - SHADOW (ALAPERTELMEZETT): SOHA nem kuld megbizast. Egy         |
//|     memoriaban tartott VIRTUALIS poziciot vezet (nyitas a sajat    |
//|     aktualis aron, SL-kovetes, SL/TP-figyeles a sajat bid/ask-on,  |
//|     zaras), es minden esemenyt CSV-be naplooz, virtualis PnL-lel.  |
//|     Celja: az ELES rendszeren, valos jelzeseken ellenorizni a      |
//|     teljes lancot az eles atallas ELOTT, kulon tesztkornyezet      |
//|     nelkul, a mellette futo eles EA zavarasa nelkul.               |
//|   - LIVE: valodi megbizasok (a 2026-09-24-i demo-teszten atment    |
//|     logika, valtozatlanul).                                         |
//|                                                                    |
//| ELES EA VEDELEM: a TENYLEGES mod CSAK AKKOR LIVE, ha               |
//|   (1) InpExecutionMode = EXEC_LIVE, ES                             |
//|   (2) ebben a terminalban NEM fut mas EA ugyanezen a szimbolumon,  |
//|       es sehol nem fut "RegimeFramework" nevu EA (chart-bejaras:   |
//|       ChartFirst/ChartNext + CHART_EXPERT_NAME), ES                |
//|   (3) nincs olyan pozicio ugyanezzel a szimbolummal/magic-kel,    |
//|       amit NEM ez a slave nyitott.                                 |
//| Barmelyik sertul -> KENYSZERITETT SHADOW (a beallitastol           |
//| fuggetlenul), jol lathatoan naplozva. Masodpercenkent ellenorizve. |
//|                                                                    |
//| SHADOW modban a slave NEM ir az eles EA fajljaiba: a heartbeat     |
//| sajat neven megy (RF_SignalSlave_shadow_<SYM>_<magic>.txt), igy a  |
//| dashboard tovabbra is az eles EA-t latja.                          |
//|                                                                    |
//| AR-ATSZAMITAS: a master SL/TP-szintjeit a NYITASKOR rogzitett      |
//| inter-bróker kulonbseggel (basis = slave mid - master mid) toljuk  |
//| el (2026-09-24-i javitas: a folyamatosan ujraszamolt basis zaja    |
//| felfele "racsnizta" az SL-t).                                      |
//|                                                                    |
//| BIZTONSAG: nativ SL/TP; elavult jelre nem nyit/zar; 10 mp-es       |
//| belepesi ablak; a "kezelt" jelzo CSAK sikeres nyitas utan (XAUUSD- |
//| tanulsag); ujraprobalas max 1/mp; sajat napvegi zaras, spread-     |
//| vedelem, tavoli leallitas.                                          |
//+------------------------------------------------------------------+
#property strict
#property copyright "regime_framework signal copier"
#property version   "1.11"

#include <Trade\Trade.mqh>
#include "../SpreadAnomalyGuard.mqh"

enum EExecMode
  {
   EXEC_SHADOW = 0,   // SHADOW: csak naplooz (virtualis pozicio), SOHA nem kereskedik
   EXEC_LIVE   = 1    // LIVE: valodi megbizasok (ha nem fut mas EA a terminalban)
  };

input group "=== Uzemmod ==="
input EExecMode InpExecutionMode     = EXEC_SHADOW;   // ALAPBOL SHADOW -- LIVE csak tudatos atallitassal

input group "=== Jelzesforras ==="
input string InpSignalFile           = "RF_signal_USTEC_101001.txt";  // A publisher pillanatkep-fajlja (Common\Files)
input int    InpPollMs               = 100;     // Pillanatkep olvasasi gyakorisag (ms)
input int    InpMaxSignalAgeMs       = 5000;    // Ennel regebbi pillanatkep = elavult (publisher heartbeat: 1000 ms)
input int    InpMaxEntryDelaySec     = 10;      // A master-pozicio megjelenese utan legfeljebb ennyi mp-ig nyitunk

input group "=== Kereskedes ==="
input long   InpMagicNumber          = 101001;  // LIVE: ugyanaz, mint a korabbi EA-e -- a dashboard/baseline kulcsa
input double InpLotSize              = 0.1;     // Fix lot (SHADOW-ban a virtualis PnL-hez is ez)
input int    InpSlippagePoints       = 50;
input int    InpSlSyncTolerancePoints = 1;      // Ennyi pontnal kisebb SL-elteres nem modositas

input group "=== Vedelem ==="
input int    InpForceCloseHour       = 23;      // Napvegi kenyszerzaras (szerverido) -- ugyanaz, mint a masteren
input int    InpForceCloseMinute     = 49;
input bool   InpUseSpreadGuard       = true;    // Sajat bróker spread-anomalia eseten nem nyit (az ablakon belul ujraprobalja)
input int    InpStalePushAfterSec    = 30;      // Elavult master-jel eseten push-ertesites csak ennyi mp folyamatos kieses utan

struct SSnapshot
  {
   bool     valid;
   long     seq;
   long     publishTickMs;
   double   masterBid;
   double   masterAsk;
   string   masterRegime;
   string   masterVolBand;
   bool     hasPosition;
   ulong    ticket;
   int      direction;
   string   tag;
   long     seenGmt;
   double   sl;
   double   tp;
  };

//--- SHADOW mod virtualis pozicioja
struct SVirtualPos
  {
   bool     active;
   ulong    masterTicket;
   bool     isLong;
   string   tag;
   double   openPrice;
   double   sl;
   double   tp;
   double   basis;
   datetime openTime;
  };

CTrade               trade;
CSpreadAnomalyGuard *g_spreadGuard = NULL;
string   g_controlFileName   = "";
string   g_gvMirrored        = "";   // LIVE: az aktualisan tukrozott master-ticket (terminal global variable)
string   g_gvHandled         = "";   // LIVE: az utolso kezelt (nyitott VAGY kihagyott) master-ticket
string   g_gvBasis           = "";   // LIVE: a NYITASKOR rogzitett inter-bróker basis
string   g_gvMyPos           = "";   // LIVE: a slave SAJAT poziciojanak ticketje (csak ezt kezeli sajatkent)
string   g_csvFile           = "";
datetime g_lastBarTime       = 0;
long     g_heartbeatCounter  = 0;
int      g_tradeErrorCount   = 0;
string   g_lastErrorMsg      = "";
bool     g_staleNotified     = false;
ulong    g_staleSinceMs      = 0;
bool     g_stalePushed       = false;
ulong    g_lastAttemptMs     = 0;
SSnapshot g_last;

//--- tenyleges uzemmod
bool     g_effLive           = false;
bool     g_modeInitialized   = false;
string   g_blockReason       = "";
ulong    g_lastModeCheckMs   = 0;

//--- SHADOW allapot
SVirtualPos g_v;
ulong    g_shadowHandled     = 0;
ulong    g_shadowBlockLogged = 0;   // melyik master-ticketnel naplooztuk mar a blokkolast (egyszer / ticket)

//+------------------------------------------------------------------+
ulong GvGet(string name)       { return GlobalVariableCheck(name) ? (ulong)GlobalVariableGet(name) : 0; }
void  GvSet(string name, ulong v) { GlobalVariableSet(name, (double)v); }

string ModeStr() { return g_effLive ? "LIVE" : "SHADOW"; }

void NotifyError(string context, int retcode, string description)
  {
   g_tradeErrorCount++;
   g_lastErrorMsg = context + ": " + IntegerToString(retcode) + " (" + description + ")";
   PrintFormat("⚠️ %s", g_lastErrorMsg);
   SendNotification(StringFormat("RF Slave %s: %s hiba (%d)", _Symbol, context, retcode));
  }

//+------------------------------------------------------------------+
//| CSV-naplo (Common\Files) -- mindket modban, minden esemenyrol.     |
//+------------------------------------------------------------------+
void CsvLog(string ev, ulong masterTicket, string tag, int dir, double price, double sl, double tp,
            double basis, long signalAgeMs, double pnlPoints, double pnlMoney, string note)
  {
   int h = FileOpen(g_csvFile, FILE_READ | FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI | FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("⚠️ CSV-naplo irasa sikertelen: %d", GetLastError());
      return;
     }
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(FileSize(h) == 0)
      FileWriteString(h, "local_time;server_time;mode;event;master_ticket;tag;dir;slave_bid;slave_ask;price;sl;tp;basis;signal_age_ms;pnl_points;pnl_money;note\r\n");
   FileSeek(h, 0, SEEK_END);
   string line = StringFormat("%s;%s;%s;%s;%I64u;%s;%s;%s;%s;%s;%s;%s;%s;%I64d;%s;%s;%s\r\n",
                              TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS),
                              TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
                              ModeStr(), ev, masterTicket, tag,
                              dir == 1 ? "BUY" : (dir == -1 ? "SELL" : ""),
                              DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_BID), digits),
                              DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_ASK), digits),
                              DoubleToString(price, digits), DoubleToString(sl, digits), DoubleToString(tp, digits),
                              DoubleToString(basis, 2), signalAgeMs,
                              DoubleToString(pnlPoints, digits), DoubleToString(pnlMoney, 2), note);
   FileWriteString(h, line);
   FileClose(h);
  }

//+------------------------------------------------------------------+
//| Pillanatkep beolvasasa -- csak teljes (end=OK) fajlt fogadunk el. |
//+------------------------------------------------------------------+
bool ReadSnapshot(SSnapshot &s)
  {
   s.valid = false;
   int h = FileOpen(InpSignalFile, FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return false;
   bool endOk = false;
   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      int eq = StringFind(line, "=");
      if(eq <= 0)
         continue;
      string k = StringSubstr(line, 0, eq);
      string v = StringSubstr(line, eq + 1);
      if(k == "seq")                  s.seq = StringToInteger(v);
      else if(k == "publish_tick_ms") s.publishTickMs = StringToInteger(v);
      else if(k == "master_bid")      s.masterBid = StringToDouble(v);
      else if(k == "master_ask")      s.masterAsk = StringToDouble(v);
      else if(k == "master_regime")   s.masterRegime = v;
      else if(k == "master_vol_band") s.masterVolBand = v;
      else if(k == "has_position")    s.hasPosition = (v == "1");
      else if(k == "ticket")          s.ticket = (ulong)StringToInteger(v);
      else if(k == "direction")       s.direction = (int)StringToInteger(v);
      else if(k == "tag")             s.tag = v;
      else if(k == "seen_gmt")        s.seenGmt = StringToInteger(v);
      else if(k == "sl")              s.sl = StringToDouble(v);
      else if(k == "tp")              s.tp = StringToDouble(v);
      else if(k == "end")             endOk = (v == "OK");
     }
   FileClose(h);
   s.valid = endOk && s.masterBid > 0.0 && s.masterAsk > 0.0;
   return s.valid;
  }

long SignalAgeMs(const SSnapshot &s) { return s.valid ? (long)GetTickCount64() - s.publishTickMs : -1; }

bool IsFresh(const SSnapshot &s)
  {
   //--- GetTickCount64() rendszerszintu (a gep indulasa ota eltelt ms) -- ugyanazon a gepen futo ket
   //    terminal kozott osszehasonlithato, masodperc alatti pontossaggal.
   long age = SignalAgeMs(s);
   return s.valid && age >= 0 && age <= InpMaxSignalAgeMs;
  }

//+------------------------------------------------------------------+
//| ELES EA VEDELEM -- (2) fut-e mas EA ebben a terminalban?           |
//+------------------------------------------------------------------+
bool OtherExpertRunning(string &who)
  {
   long me = ChartID();
   long id = ChartFirst();
   while(id >= 0)
     {
      if(id != me)
        {
         //--- JAVITAS (2026-09-25, demo-teszt C3): EA nelkuli charton a ChartGetString() NULL-t ad
         //    vissza, ami MQL5-ben NEM egyenlo ""-vel -- a regi `ea != ""` feltetel minden ures chartot
         //    "futo EA"-nak vett (ovatos iranyba tevedett, de LIVE-ra soha nem valtott volna)
         string ea = ChartGetString(id, CHART_EXPERT_NAME);
         if(StringLen(ea) > 0)
           {
            string sym = ChartSymbol(id);
            if(sym == _Symbol || StringFind(ea, "RegimeFramework") >= 0)
              {
               who = ea + " @ " + sym;
               return true;
              }
           }
        }
      id = ChartNext(id);
     }
   return false;
  }

//--- (3) van-e olyan pozicio ezzel a szimbolummal/magic-kel, amit NEM ez a slave nyitott?
//    A tulajdonjog TICKET-alapu (g_gvMyPos), nem magic-alapu: egy levett eles EA altal nyitva hagyott,
//    azonos magic-u poziciot a slave SOHA nem tekint sajatjanak (nem kezeli, nem zarja).
bool ForeignPositionExists(ulong &foreignTicket)
  {
   ulong mine = GvGet(g_gvMyPos);
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong t = PositionGetTicket(i);
      if(!PositionSelectByTicket(t))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;
      if(t != mine)
        {
         foreignTicket = t;
         return true;
        }
     }
   return false;
  }

//+------------------------------------------------------------------+
//| A tenyleges uzemmod megallapitasa (1 mp-enkent). Modvaltaskor     |
//| minden folyamatban levo kovetest lezarunk/kezeltnek jelolunk, hogy |
//| egyik mod se lepjen be egy mar futo master-pozicioba.              |
//+------------------------------------------------------------------+
void UpdateEffectiveMode(bool force)
  {
   ulong now = GetTickCount64();
   if(!force && now - g_lastModeCheckMs < 1000)
      return;
   g_lastModeCheckMs = now;

   string reason = "";
   bool live = false;
   if(InpExecutionMode != EXEC_LIVE)
      reason = "InpExecutionMode=SHADOW";
   else
     {
      string who = "";
      ulong foreign = 0;
      if(OtherExpertRunning(who))
         reason = "mas EA fut a terminalban: " + who;
      else if(ForeignPositionExists(foreign))
         reason = StringFormat("idegen %s/%I64d pozicio van a szamlan (#%I64u)", _Symbol, InpMagicNumber, foreign);
      else
         live = true;
     }

   if(g_modeInitialized && live == g_effLive && reason == g_blockReason)
      return;

   bool changed = g_modeInitialized && (live != g_effLive);
   g_effLive = live;
   g_blockReason = reason;
   g_modeInitialized = true;

   string msg = StringFormat("Uzemmod: beallitott=%s, TENYLEGES=%s%s",
                             InpExecutionMode == EXEC_LIVE ? "LIVE" : "SHADOW", ModeStr(),
                             reason != "" ? " (" + reason + ")" : "");
   PrintFormat("%s %s", live ? "🟢" : "🔵", msg);
   CsvLog("MODE", 0, "", 0, 0, 0, 0, 0, SignalAgeMs(g_last), 0, 0, msg);
   if(changed)
     {
      SendNotification(StringFormat("RF Slave %s: %s", _Symbol, msg));
      //--- modvaltas: a folyamatban levo kovetest nem visszuk at a masik modba
      if(g_v.active)
         VirtualClose("MODE_SWITCH", SymbolInfoDouble(_Symbol, g_v.isLong ? SYMBOL_BID : SYMBOL_ASK));
      if(g_last.valid && g_last.hasPosition)
        {
         g_shadowHandled = g_last.ticket;
         GvSet(g_gvHandled, g_last.ticket);
        }
     }
  }

//+------------------------------------------------------------------+
//| Kozos szamitasok                                                   |
//+------------------------------------------------------------------+
//--- inter-bróker ar-kulonbseg: slave mid - master mid
double Basis(const SSnapshot &s)
  {
   double myMid = (SymbolInfoDouble(_Symbol, SYMBOL_BID) + SymbolInfoDouble(_Symbol, SYMBOL_ASK)) / 2.0;
   return myMid - (s.masterBid + s.masterAsk) / 2.0;
  }

bool ForceCloseTimeReached()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return (dt.hour > InpForceCloseHour) || (dt.hour == InpForceCloseHour && dt.min >= InpForceCloseMinute);
  }

//--- a master SL/TP-szintjei eltolva a basis-szal; a zaro oldalhoz (LONG: Bid, SHORT: Ask) kepest
//    ellenorizve (ugyanaz az elv, mint a fo EA OpenPosition()-jeben)
void EntryLevels(const SSnapshot &s, double basis, double &sl, double &tp)
  {
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   sl = (s.sl > 0.0) ? s.sl + basis : 0.0;
   tp = (s.tp > 0.0) ? s.tp + basis : 0.0;
   if(s.direction == 1)
     {
      if(sl > 0.0 && sl > bid - minDist) sl = bid - MathMax(minDist, point);
      if(tp > 0.0 && tp < bid + minDist) tp = bid + MathMax(minDist, point);
     }
   else
     {
      if(sl > 0.0 && sl < ask + minDist) sl = ask + MathMax(minDist, point);
      if(tp > 0.0 && tp > ask - minDist) tp = ask - MathMax(minDist, point);
     }
   if(sl > 0.0) sl = NormalizeDouble(sl, digits);
   if(tp > 0.0) tp = NormalizeDouble(tp, digits);
  }

//--- SL-kovetes celszintje: a master SL-je a ROGZITETT basis-szal, CSAK szigorito iranyba
bool StopLossTarget(bool isLong, double curSl, double basis, const SSnapshot &s, double &target)
  {
   if(s.sl <= 0.0)
      return false;
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   double tol = InpSlSyncTolerancePoints * point;
   target = NormalizeDouble(s.sl + basis, digits);
   bool better, valid;
   if(isLong)
     {
      better = (curSl <= 0.0) || (target > curSl + tol);
      valid  = target < SymbolInfoDouble(_Symbol, SYMBOL_BID) - minDist;
     }
   else
     {
      better = (curSl <= 0.0) || (target < curSl - tol);
      valid  = target > SymbolInfoDouble(_Symbol, SYMBOL_ASK) + minDist;
     }
   return better && valid;
  }

//--- TP-kovetes celszintje (v1.11): a master TP-je a ROGZITETT basis-szal, BARMELY iranyu valtozasnal
//    (a master EA a TP-t nyitaskor adja meg es nem modositja, de kezi/jovobeli modositast is kovetunk)
bool TakeProfitTarget(bool isLong, double curTp, double basis, const SSnapshot &s, double &target)
  {
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   double tol = InpSlSyncTolerancePoints * point;
   target = (s.tp > 0.0) ? NormalizeDouble(s.tp + basis, digits) : 0.0;
   if(MathAbs(target - curTp) <= tol)
      return false;
   if(target > 0.0)
     {
      if(isLong && target <= SymbolInfoDouble(_Symbol, SYMBOL_BID) + minDist)
         return false;
      if(!isLong && target >= SymbolInfoDouble(_Symbol, SYMBOL_ASK) - minDist)
         return false;
     }
   return true;
  }

//--- kozos belepesi elofeltetelek. Igaz = mehet; hamis + reason = most ne (az ablakon belul ujraprobaljuk)
bool EntryAllowedNow(string &reason)
  {
   if(ForceCloseTimeReached())
     { reason = "napvegi zarasi ido"; return false; }
   if(FileIsExist(g_controlFileName, FILE_COMMON))
     { reason = "tavoli leallitas (dashboard)"; return false; }
   double spread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(InpUseSpreadGuard && g_spreadGuard.IsAnomalous(spread))
     { reason = StringFormat("rendellenes spread (%.0f pont)", spread); return false; }
   return true;
  }

//+------------------------------------------------------------------+
//| SHADOW: virtualis pozicio                                          |
//+------------------------------------------------------------------+
void VirtualOpen(const SSnapshot &s)
  {
   double basis = Basis(s);
   double sl, tp;
   EntryLevels(s, basis, sl, tp);
   bool isLong = (s.direction == 1);
   g_v.active = true;
   g_v.masterTicket = s.ticket;
   g_v.isLong = isLong;
   g_v.tag = s.tag;
   g_v.openPrice = SymbolInfoDouble(_Symbol, isLong ? SYMBOL_ASK : SYMBOL_BID);
   g_v.sl = sl;
   g_v.tp = tp;
   g_v.basis = basis;
   g_v.openTime = TimeCurrent();
   PrintFormat("🔵 SHADOW nyitas: %s %s master #%I64u @%.2f, basis=%.2f, sl=%.2f, tp=%.2f",
               isLong ? "BUY" : "SELL", s.tag, s.ticket, g_v.openPrice, basis, sl, tp);
   CsvLog("OPEN", s.ticket, s.tag, s.direction, g_v.openPrice, sl, tp, basis, SignalAgeMs(s), 0, 0, "virtualis");
  }

void VirtualClose(string reason, double price)
  {
   if(!g_v.active)
      return;
   double pts = (g_v.isLong ? price - g_v.openPrice : g_v.openPrice - price);
   double money = 0.0;
   if(!OrderCalcProfit(g_v.isLong ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, _Symbol, InpLotSize, g_v.openPrice, price, money))
      money = 0.0;
   PrintFormat("🔵 SHADOW zaras (%s): master #%I64u @%.2f, %.1f pont, %.2f %s",
               reason, g_v.masterTicket, price, pts, money, AccountInfoString(ACCOUNT_CURRENCY));
   CsvLog("CLOSE_" + reason, g_v.masterTicket, g_v.tag, g_v.isLong ? 1 : -1, price, g_v.sl, g_v.tp, g_v.basis,
          SignalAgeMs(g_last), pts, money, "virtualis");
   g_v.active = false;
  }

void ShadowStep(bool fresh)
  {
   if(g_v.active)
     {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      //--- napvegi zaras
      if(ForceCloseTimeReached())
        { VirtualClose("EOD", g_v.isLong ? bid : ask); return; }
      //--- a nativ SL/TP emulalasa a sajat bid/ask-on (LONG a Bid-en zar, SHORT az Ask-on)
      if(g_v.isLong)
        {
         if(g_v.sl > 0.0 && bid <= g_v.sl) { VirtualClose("SL", g_v.sl); return; }
         if(g_v.tp > 0.0 && bid >= g_v.tp) { VirtualClose("TP", g_v.tp); return; }
        }
      else
        {
         if(g_v.sl > 0.0 && ask >= g_v.sl) { VirtualClose("SL", g_v.sl); return; }
         if(g_v.tp > 0.0 && ask <= g_v.tp) { VirtualClose("TP", g_v.tp); return; }
        }
      if(!fresh)
         return;   // elavult jelre nem zarunk
      if(!g_last.hasPosition || g_last.ticket != g_v.masterTicket)
        { VirtualClose("MASTER_CLOSE", g_v.isLong ? bid : ask); return; }
      double target;
      if(StopLossTarget(g_v.isLong, g_v.sl, g_v.basis, g_last, target))
        {
         PrintFormat("🔵 SHADOW SL-kovetes: master #%I64u %.2f -> %.2f", g_v.masterTicket, g_v.sl, target);
         CsvLog("SL_MODIFY", g_v.masterTicket, g_v.tag, g_v.isLong ? 1 : -1, 0, target, g_v.tp, g_v.basis,
                SignalAgeMs(g_last), 0, 0, StringFormat("elozo sl=%.2f", g_v.sl));
         g_v.sl = target;
        }
      double tpTarget;
      if(TakeProfitTarget(g_v.isLong, g_v.tp, g_v.basis, g_last, tpTarget))
        {
         PrintFormat("🔵 SHADOW TP-kovetes: master #%I64u %.2f -> %.2f", g_v.masterTicket, g_v.tp, tpTarget);
         CsvLog("TP_MODIFY", g_v.masterTicket, g_v.tag, g_v.isLong ? 1 : -1, 0, g_v.sl, tpTarget, g_v.basis,
                SignalAgeMs(g_last), 0, 0, StringFormat("elozo tp=%.2f", g_v.tp));
         g_v.tp = tpTarget;
        }
      return;
     }

   if(!fresh || !g_last.hasPosition || g_last.ticket == g_shadowHandled)
      return;

   long delay = (long)TimeGMT() - g_last.seenGmt;
   if(delay > InpMaxEntryDelaySec)
     {
      g_shadowHandled = g_last.ticket;
      CsvLog("SKIP_LATE", g_last.ticket, g_last.tag, g_last.direction, 0, 0, 0, 0, SignalAgeMs(g_last), 0, 0,
             StringFormat("%I64d mp-e nyilt (ablak: %d mp)", delay, InpMaxEntryDelaySec));
      return;
     }
   string reason;
   if(!EntryAllowedNow(reason))
     {
      if(g_shadowBlockLogged != g_last.ticket)
        {
         g_shadowBlockLogged = g_last.ticket;
         CsvLog("BLOCKED", g_last.ticket, g_last.tag, g_last.direction, 0, 0, 0, 0, SignalAgeMs(g_last), 0, 0, reason);
        }
      return;
     }
   VirtualOpen(g_last);
   g_shadowHandled = g_last.ticket;
  }

//+------------------------------------------------------------------+
//| LIVE: valodi megbizasok (a 2026-09-24-i demo-teszten atment logika)|
//+------------------------------------------------------------------+
bool FindMyPosition(ulong &ticket, bool &isLong, double &sl, double &tp)
  {
   ulong mine = GvGet(g_gvMyPos);
   if(mine == 0 || !PositionSelectByTicket(mine))
      return false;
   ticket = mine;
   isLong = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   sl = PositionGetDouble(POSITION_SL);
   tp = PositionGetDouble(POSITION_TP);
   return true;
  }

void CloseMyPosition(ulong ticket, bool isLong, string reason)
  {
   if(!g_effLive)
      return;   // vedelem: SHADOW-ban soha
   double price = SymbolInfoDouble(_Symbol, isLong ? SYMBOL_BID : SYMBOL_ASK);
   if(trade.PositionClose(ticket))
     {
      PrintFormat("Slave zaras (%s): #%I64u", reason, ticket);
      GvSet(g_gvMyPos, 0);
      CsvLog("CLOSE_" + reason, GvGet(g_gvMirrored), "", isLong ? 1 : -1, price, 0, 0, 0, SignalAgeMs(g_last), 0, 0,
             StringFormat("#%I64u", ticket));
     }
   else
      NotifyError("Zaras (" + reason + ")", (int)trade.ResultRetcode(), trade.ResultRetcodeDescription());
  }

bool OpenMirror(const SSnapshot &s, double &usedBasis)
  {
   if(!g_effLive)
      return false;   // vedelem: SHADOW-ban soha
   double basis = Basis(s);
   usedBasis = basis;
   double sl, tp;
   EntryLevels(s, basis, sl, tp);
   bool isLong = (s.direction == 1);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   bool ok = isLong ? trade.Buy(InpLotSize, _Symbol, ask, sl, tp, s.tag)
                    : trade.Sell(InpLotSize, _Symbol, bid, sl, tp, s.tag);
   if(!ok || (trade.ResultRetcode() != TRADE_RETCODE_DONE && trade.ResultRetcode() != TRADE_RETCODE_PLACED))
     {
      NotifyError("Nyitas (" + s.tag + ")", (int)trade.ResultRetcode(), trade.ResultRetcodeDescription());
      return false;
     }
   PrintFormat("Slave nyitas: %s %s master #%I64u, basis=%.2f, sl=%.2f, tp=%.2f",
               isLong ? "BUY" : "SELL", s.tag, s.ticket, basis, sl, tp);
   CsvLog("OPEN", s.ticket, s.tag, s.direction, trade.ResultPrice(), sl, tp, basis, SignalAgeMs(s), 0, 0,
          StringFormat("#%I64u", trade.ResultOrder()));
   return true;
  }

void SyncStopLoss(ulong ticket, bool isLong, double curSl, double curTp, const SSnapshot &s)
  {
   if(!g_effLive)
      return;   // vedelem: SHADOW-ban soha
   double basis = GlobalVariableCheck(g_gvBasis) ? GlobalVariableGet(g_gvBasis) : Basis(s);
   double newSl = curSl, newTp = curTp, t;
   if(StopLossTarget(isLong, curSl, basis, s, t))
      newSl = t;
   if(TakeProfitTarget(isLong, curTp, basis, s, t))
      newTp = t;
   if(newSl == curSl && newTp == curTp)
      return;
   if(trade.PositionModify(ticket, newSl, newTp))
      CsvLog(newSl != curSl ? "SL_MODIFY" : "TP_MODIFY", s.ticket, s.tag, isLong ? 1 : -1, 0, newSl, newTp, basis,
             SignalAgeMs(s), 0, 0, StringFormat("elozo sl=%.2f tp=%.2f", curSl, curTp));
   else
      NotifyError("SL/TP-kovetes", (int)trade.ResultRetcode(), trade.ResultRetcodeDescription());
  }

void LiveStep(bool fresh)
  {
   ulong myTicket = 0;
   bool myLong = false;
   double mySl = 0.0, myTp = 0.0;
   bool hasMine = FindMyPosition(myTicket, myLong, mySl, myTp);
   ulong mirrored = GvGet(g_gvMirrored);

   //--- sajat napvegi kenyszerzaras (masodlagos vedelem -- a master is zar ekkor)
   if(hasMine && ForceCloseTimeReached())
     {
      CloseMyPosition(myTicket, myLong, "EOD");
      return;
     }

   if(hasMine)
     {
      if(!fresh)
         return;   // elavult jelre nem zarunk -- a nativ SL/TP es a napvegi zaras ved
      if(!g_last.hasPosition || g_last.ticket != mirrored)
        {
         CloseMyPosition(myTicket, myLong, "MASTER_CLOSE");
         GvSet(g_gvMirrored, 0);
         return;
        }
      SyncStopLoss(myTicket, myLong, mySl, myTp, g_last);
      return;
     }

   //--- nincs sajat pozicio: ha tukroztunk valamit, az mar a bróker-oldalon zarult (SL/TP) -- nem nyitjuk ujra
   if(mirrored != 0)
     {
      CsvLog("CLOSED_BY_BROKER", mirrored, "", 0, 0, 0, 0, 0, SignalAgeMs(g_last), 0, 0, "nativ SL/TP");
      GvSet(g_gvMirrored, 0);
      GvSet(g_gvMyPos, 0);
     }

   if(!fresh || !g_last.hasPosition || g_last.ticket == GvGet(g_gvHandled))
      return;

   //--- belepesi ablak: ha a master-pozicio mar tul regi, kihagyjuk (es kezeltnek jeloljuk)
   long delay = (long)TimeGMT() - g_last.seenGmt;
   if(delay > InpMaxEntryDelaySec)
     {
      GvSet(g_gvHandled, g_last.ticket);
      PrintFormat("⏭️ Slave: master #%I64u kihagyva -- %I64d mp-e nyilt (ablak: %d mp).",
                  g_last.ticket, delay, InpMaxEntryDelaySec);
      CsvLog("SKIP_LATE", g_last.ticket, g_last.tag, g_last.direction, 0, 0, 0, 0, SignalAgeMs(g_last), 0, 0,
             StringFormat("%I64d mp-e nyilt (ablak: %d mp)", delay, InpMaxEntryDelaySec));
      SendNotification(StringFormat("RF Slave %s: master-belepes kihagyva (%I64d mp keses)", _Symbol, delay));
      return;
     }

   //--- blokkolo feltetelek: az ablakon BELUL ujraprobaljuk, NEM jeloljuk kezeltnek
   string reason;
   if(!EntryAllowedNow(reason))
      return;

   //--- ujraprobalas-fojtas: legfeljebb 1 nyitasi kiserlet masodpercenkent (ne 100 ms-onkent)
   ulong nowMs = GetTickCount64();
   if(nowMs - g_lastAttemptMs < 1000)
      return;
   g_lastAttemptMs = nowMs;

   double usedBasis = 0.0;
   if(OpenMirror(g_last, usedBasis))
     {
      GlobalVariableSet(g_gvBasis, usedBasis);
      GvSet(g_gvMyPos, trade.ResultOrder());   // hedging szamlan a pozicio ticketje = a nyito megbizas ticketje
      //--- CSAK sikeres nyitas UTAN jeloljuk kezeltnek (lasd fejlec, XAUUSD-tanulsag)
      GvSet(g_gvMirrored, g_last.ticket);
      GvSet(g_gvHandled, g_last.ticket);
     }
  }

//+------------------------------------------------------------------+
//| Heartbeat -- LIVE-ban a fo EA fajlnevevel (dashboard), SHADOW-ban  |
//| SAJAT neven, hogy az eles EA heartbeat-jet ne irjuk felul.         |
//+------------------------------------------------------------------+
void WriteHeartbeat()
  {
   string fname = g_effLive ? StringFormat("RegimeFramework_heartbeat_%s_%I64d.txt", _Symbol, InpMagicNumber)
                            : StringFormat("RF_SignalSlave_shadow_%s_%I64d.txt", _Symbol, InpMagicNumber);
   int h = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;
   FileWrite(h, "symbol=" + _Symbol);
   FileWrite(h, "magic=" + IntegerToString(InpMagicNumber));
   FileWrite(h, "server_time=" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS));
   FileWrite(h, "last_bar_time=" + TimeToString(g_lastBarTime, TIME_DATE | TIME_SECONDS));
   FileWrite(h, "heartbeat_counter=" + IntegerToString(g_heartbeatCounter));
   FileWrite(h, "classifier_ready=" + (IsFresh(g_last) ? "true" : "false"));   // slave: "kesz" = friss master-jel
   FileWrite(h, "open_positions=" + IntegerToString(PositionsTotal()));
   FileWrite(h, "trade_error_count=" + IntegerToString(g_tradeErrorCount));
   FileWrite(h, "last_error_msg=" + g_lastErrorMsg);
   FileWrite(h, "account_equity=" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2));
   FileWrite(h, "account_margin_free=" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2));
   FileWrite(h, "market_holiday_today=false");
   FileWrite(h, "spread_guard_baseline_days=" + IntegerToString(CheckPointer(g_spreadGuard) != POINTER_INVALID ? g_spreadGuard.BaselineDayCount() : 0));
   FileWrite(h, "current_regime=" + (g_last.valid ? g_last.masterRegime : "?"));
   FileWrite(h, "current_vol_band=" + (g_last.valid ? g_last.masterVolBand : "?"));
   FileWrite(h, "mode=slave");
   FileWrite(h, "exec_mode_config=" + (InpExecutionMode == EXEC_LIVE ? "LIVE" : "SHADOW"));
   FileWrite(h, "exec_mode_effective=" + ModeStr());
   FileWrite(h, "block_reason=" + g_blockReason);
   FileWrite(h, "signal_file=" + InpSignalFile);
   FileWrite(h, "signal_age_ms=" + IntegerToString(SignalAgeMs(g_last)));
   FileWrite(h, "mirrored_master_ticket=" + IntegerToString((long)(g_effLive ? GvGet(g_gvMirrored) : (g_v.active ? g_v.masterTicket : 0))));
   FileWrite(h, "csv_log=" + g_csvFile);
   FileClose(h);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);
   g_controlFileName = StringFormat("RegimeFramework_control_%s_%I64d.txt", _Symbol, InpMagicNumber);
   g_gvMirrored = StringFormat("RFS_%s_%I64d_mirrored", _Symbol, InpMagicNumber);
   g_gvHandled  = StringFormat("RFS_%s_%I64d_handled", _Symbol, InpMagicNumber);
   g_gvBasis    = StringFormat("RFS_%s_%I64d_basis", _Symbol, InpMagicNumber);
   g_gvMyPos    = StringFormat("RFS_%s_%I64d_mypos", _Symbol, InpMagicNumber);
   g_csvFile    = StringFormat("RF_SignalSlave_%s_%I64d.csv", _Symbol, InpMagicNumber);

   g_spreadGuard = new CSpreadAnomalyGuard();
   g_spreadGuard.Backfill(_Symbol, PERIOD_CURRENT);

   g_last.valid = false;
   g_v.active = false;
   PrintFormat("RF_SignalSlave v1.11 elindult: %s magic=%I64d, forras=%s (Common\\Files), lot=%.2f, naplo=%s",
               _Symbol, InpMagicNumber, InpSignalFile, InpLotSize, g_csvFile);
   UpdateEffectiveMode(true);
   EventSetMillisecondTimer(MathMax(50, InpPollMs));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_v.active)
      CsvLog("DEINIT", g_v.masterTicket, g_v.tag, g_v.isLong ? 1 : -1, 0, g_v.sl, g_v.tp, g_v.basis,
             SignalAgeMs(g_last), 0, 0, "virtualis pozicio nyitva maradt az EA leallasakor");
   if(CheckPointer(g_spreadGuard) == POINTER_DYNAMIC)
      delete g_spreadGuard;
  }

//--- uj bar: spread-bazis frissitese + heartbeat (ugyanaz a ritmus, mint a fo EA-nal)
void OnTick()
  {
   datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(barTime == g_lastBarTime)
      return;
   g_lastBarTime = barTime;
   g_heartbeatCounter++;
   g_spreadGuard.OnNewBar((double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD), barTime);
   WriteHeartbeat();
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   SSnapshot s;
   ReadSnapshot(s);
   if(s.valid)
      g_last = s;
   bool fresh = IsFresh(g_last);

   //--- elavult jel: naplo + CSV azonnal; push CSAK InpStalePushAfterSec folyamatos kieses utan
   //    (2026-09-25-i demo-teszt: a rovid, 1-9 mp-es kiesesek -- pl. szerver-ujracsatlakozas, a publisher
   //    beallitas-ablaka -- push-aradatot okoztak volna)
   if(!fresh)
     {
      if(!g_staleNotified)
        {
         g_staleNotified = true;
         g_staleSinceMs = GetTickCount64();
         g_stalePushed = false;
         Print("⏸️ Slave: a master-jel elavult vagy nem olvashato -- uj nyitas szunetel, a nyitott pozicio natív SL/TP-vel vedett.");
         CsvLog("STALE", 0, "", 0, 0, 0, 0, 0, SignalAgeMs(g_last), 0, 0, "master-jel elavult");
        }
      else if(!g_stalePushed && GetTickCount64() - g_staleSinceMs >= (ulong)InpStalePushAfterSec * 1000)
        {
         g_stalePushed = true;
         SendNotification(StringFormat("RF Slave %s: master-jel %d mp ota elavult (%s)", _Symbol, InpStalePushAfterSec, InpSignalFile));
        }
     }
   else if(g_staleNotified)
     {
      g_staleNotified = false;
      long lastedMs = (long)(GetTickCount64() - g_staleSinceMs);
      Print("▶️ Slave: a master-jel helyreallt -- a kovetes folytatodik.");
      CsvLog("RECOVERED", 0, "", 0, 0, 0, 0, 0, SignalAgeMs(g_last), 0, 0,
             StringFormat("master-jel helyreallt (%I64d ms kieses)", lastedMs));
      if(g_stalePushed)
         SendNotification(StringFormat("RF Slave %s: master-jel helyreallt", _Symbol));
     }

   UpdateEffectiveMode(false);
   if(g_effLive)
      LiveStep(fresh);
   else
      ShadowStep(fresh);
  }
//+------------------------------------------------------------------+
