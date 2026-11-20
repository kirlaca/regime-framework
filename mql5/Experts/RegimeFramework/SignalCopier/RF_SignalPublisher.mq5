//+------------------------------------------------------------------+
//| RF_SignalPublisher.mq5                                            |
//| A REFERENCIA (master) terminalban fut, egy KULON charton, a       |
//| RegimeFramework_EA mellett. NEM kereskedik, NEM kuld megbizast -- |
//| csak figyeli a master EA (InpMasterSymbol + InpMasterMagic)       |
//| nyitott poziciojat, es annak pillanatkepet kiirja a kozos         |
//| (FILE_COMMON) mappaba, ahonnan a masik terminal RF_SignalSlave-je |
//| olvassa. Lasd README.md (tervezesi dontesek, 2026-09-24).         |
//|                                                                    |
//| MIERT PILLANATKEP (allapot) ES NEM ESEMENYNAPLO: ha a slave       |
//| ujraindul vagy kimarad egy esemeny, a kovetkezo pillanatkepbol    |
//| onmagatol helyreall (nyitas/SL-kovetes/zaras egyarant) -- nincs   |
//| elveszett vagy duplan feldolgozott esemeny.                        |
//|                                                                    |
//| ATOMIKUS IRAS: elobb .tmp fajlba ir, majd FileMove(FILE_REWRITE)- |
//| val atnevezi, es az utolso sor "end=OK" -- a slave csak teljes,   |
//| end=OK-val zarulo fajlt fogad el, igy felig irt fajlt sosem olvas.|
//+------------------------------------------------------------------+
#property strict
#property copyright "regime_framework signal copier"
#property version   "1.01"

input string InpMasterSymbol = "USTEC";    // A master EA szimboluma EBBEN a terminalban
input long   InpMasterMagic  = 101001;     // A master EA magic szama
input int    InpHeartbeatMs  = 1000;       // Pillanatkep frissitese legalabb ennyi ms-onkent

long     g_seq          = 0;
ulong    g_lastTicket   = 0;
double   g_lastSl       = -1.0;
double   g_lastTp       = -1.0;
datetime g_seenGmt      = 0;      // mikor LATTUK eloszor az aktualis master-poziciot (TimeGMT)

string SignalFileName() { return StringFormat("RF_signal_%s_%I64d.txt", InpMasterSymbol, InpMasterMagic); }
string TempFileName()   { return StringFormat("RF_signal_%s_%I64d.tmp", InpMasterSymbol, InpMasterMagic); }

//+------------------------------------------------------------------+
//| A master heartbeat-fajljabol (ugyanaz a Common mappa) kiolvassuk  |
//| az aktualis rezsimet -- csak tajekoztato jellegu, a slave a sajat |
//| heartbeat-jebe irja tovabb, hogy a dashboard ertelmes erteket     |
//| mutasson.                                                          |
//+------------------------------------------------------------------+
string ReadMasterHeartbeatValue(string key)
  {
   string fname = StringFormat("RegimeFramework_heartbeat_%s_%I64d.txt", InpMasterSymbol, InpMasterMagic);
   int h = FileOpen(fname, FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return "?";
   string value = "?";
   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      if(StringFind(line, key + "=") == 0)
        {
         value = StringSubstr(line, StringLen(key) + 1);
         break;
        }
     }
   FileClose(h);
   return value;
  }

//+------------------------------------------------------------------+
bool FindMasterPosition(ulong &ticket, int &direction, double &openPrice, double &sl, double &tp,
                        string &tag, datetime &openTime)
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong t = PositionGetTicket(i);
      if(!PositionSelectByTicket(t))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != InpMasterSymbol || PositionGetInteger(POSITION_MAGIC) != InpMasterMagic)
         continue;
      ticket    = t;
      direction = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      sl        = PositionGetDouble(POSITION_SL);
      tp        = PositionGetDouble(POSITION_TP);
      tag       = PositionGetString(POSITION_COMMENT);
      openTime  = (datetime)PositionGetInteger(POSITION_TIME);
      return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
void Publish()
  {
   ulong ticket = 0;
   int direction = 0;
   double openPrice = 0.0, sl = 0.0, tp = 0.0;
   string tag = "";
   datetime openTime = 0;
   bool has = FindMasterPosition(ticket, direction, openPrice, sl, tp, tag, openTime);

   //--- valtozas-detektalas: a seq csak tenyleges allapotvaltozasnal no (uj/zart pozicio, SL/TP-modositas)
   if(!has)
     {
      if(g_lastTicket != 0)
        {
         g_seq++;
         g_lastTicket = 0;
         g_lastSl = -1.0;
         g_lastTp = -1.0;
        }
     }
   else if(ticket != g_lastTicket)
     {
      g_seq++;
      g_lastTicket = ticket;
      g_lastSl = sl;
      g_lastTp = tp;
      //--- a pozicio TENYLEGES nyitasi idejebol szamolunk GMT-t (nem "most"-bol), hogy egy publisher-
      //    ujrainditas utan egy regi master-pozicio ne tunjon frissnek a slave belepesi ablakaban
      g_seenGmt = TimeGMT() - (TimeTradeServer() - openTime);
     }
   else if(sl != g_lastSl || tp != g_lastTp)
     {
      g_seq++;
      g_lastSl = sl;
      g_lastTp = tp;
     }

   double bid = SymbolInfoDouble(InpMasterSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(InpMasterSymbol, SYMBOL_ASK);

   int h = FileOpen(TempFileName(), FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("⚠️ Publisher: tmp fajl irasa sikertelen: %d", GetLastError());
      return;
     }
   FileWrite(h, "version=1");
   FileWrite(h, "seq=" + IntegerToString(g_seq));
   FileWrite(h, "publish_tick_ms=" + IntegerToString((long)GetTickCount64()));
   FileWrite(h, "publish_gmt=" + IntegerToString((long)TimeGMT()));
   FileWrite(h, "master_symbol=" + InpMasterSymbol);
   FileWrite(h, "master_magic=" + IntegerToString(InpMasterMagic));
   FileWrite(h, "master_bid=" + DoubleToString(bid, 8));
   FileWrite(h, "master_ask=" + DoubleToString(ask, 8));
   FileWrite(h, "master_regime=" + ReadMasterHeartbeatValue("current_regime"));
   FileWrite(h, "master_vol_band=" + ReadMasterHeartbeatValue("current_vol_band"));
   FileWrite(h, "has_position=" + (has ? "1" : "0"));
   FileWrite(h, "ticket=" + IntegerToString((long)(has ? ticket : 0)));
   FileWrite(h, "direction=" + IntegerToString(has ? direction : 0));
   FileWrite(h, "tag=" + (has ? tag : ""));
   FileWrite(h, "open_time=" + IntegerToString((long)(has ? openTime : 0)));
   FileWrite(h, "seen_gmt=" + IntegerToString((long)(has ? g_seenGmt : 0)));
   FileWrite(h, "open_price=" + DoubleToString(has ? openPrice : 0.0, 8));
   FileWrite(h, "sl=" + DoubleToString(has ? sl : 0.0, 8));
   FileWrite(h, "tp=" + DoubleToString(has ? tp : 0.0, 8));
   FileWrite(h, "end=OK");
   FileClose(h);

   //--- ha a slave eppen olvassa a celfajlt, a Windows nem engedi felulirni (5004) -- azonnal
   //    ujraprobaljuk (2026-09-25-i demo-teszt: ritka, de egyszeri kimaradast okozott)
   bool moved = false;
   for(int attempt = 0; attempt < 5 && !moved; attempt++)
     {
      moved = FileMove(TempFileName(), FILE_COMMON, SignalFileName(), FILE_COMMON | FILE_REWRITE);
      if(!moved)
         Sleep(2);
     }
   if(!moved)
      PrintFormat("⚠️ Publisher: atnevezes 5 probalkozas utan is sikertelen: %d", GetLastError());
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(!SymbolSelect(InpMasterSymbol, true))
     {
      PrintFormat("❌ Publisher: a(z) %s szimbolum nem valaszthato ki ebben a terminalban.", InpMasterSymbol);
      return INIT_FAILED;
     }
   EventSetMillisecondTimer(MathMax(100, InpHeartbeatMs));
   Publish();
   PrintFormat("RF_SignalPublisher elindult: master=%s magic=%I64d -> %s (Common\\Files)",
               InpMasterSymbol, InpMasterMagic, SignalFileName());
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer() { Publish(); }
void OnTick() { }   // szandekosan ures -- a publisher barmelyik charton futhat

//--- nyitas/zaras/SL-modositas azonnal, a kovetkezo timer-ciklus megvarasa nelkul
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   Publish();
  }
//+------------------------------------------------------------------+
