//+------------------------------------------------------------------+
//| SpreadAnomalyGuard.mqh                                            |
//| Futasidejű vedelem: ha a mai spread a legutobbi napok bazisahoz    |
//| kepest rendellenesen szeles (pl. a mogottes piac ünnepnapon zart,  |
//| de a bróker meg is arazza a CFD-t, szintetikus/vekony-likviditasu  |
//| feed-del), az ÚJ belepesek kimaradnak -- a MEGLEVO poziciok        |
//| kezelese (SL/TP/trailing/kenyszerzaras) valtozatlan marad.          |
//|                                                                    |
//| KONTEXTUS (2026-09-07): a felhasznalo jelezte, hogy az IC Markets  |
//| EA a mai US Labor Day-en (a valos NYSE/NASDAQ zarva) is nyitott    |
//| pozíciot -- lasd MarketHolidays.mqh a naptar-alapu (elore ismert   |
//| unnepnapok) vedelemert. Ez a modul egy MASODIK, kiegeszito reteg:  |
//| BARMILYEN rendellenes napot elkap (bejelentett unnepet, be nem     |
//| jelentett leallast, likviditasi zavart), naptari karbantartas      |
//| nelkul -- ugyanazt a spread/bar-range-elvet hasznalja futasidőben, |
//| amit a kutatasi ág (optuna_research) egesz nap hasznalt villam-    |
//| szurokben a "bruttó jónak tűnik, nettó lehet nem az" vakfolt        |
//| elkerulesere (lasd SESSION_LOG.md 2026-09-06).                     |
//+------------------------------------------------------------------+
#property strict

#define SPREAD_GUARD_BASELINE_DAYS       15    // hany napi atlagot tartunk a bazishoz
#define SPREAD_GUARD_MIN_BASELINE_DAYS   5     // ennel kevesebb tarolt nap eseten meg nem itelunk (nincs eleg adat)
#define SPREAD_GUARD_MIN_SAMPLES_PER_DAY 20    // ennel kevesebb minta/nap eseten a nap kihagyva a bazisbol (pl. resnap)
#define SPREAD_GUARD_ANOMALY_RATIO       3.0   // ha az AKTUALIS spread ennyiszerese a bazis-medianynak -> anomalia

class CSpreadAnomalyGuard
  {
private:
   double   m_dailyAvgSpread[SPREAD_GUARD_BASELINE_DAYS];   // korkoros puffer
   int      m_bufferCount;
   int      m_bufferHead;

   double   m_todaySum;
   int      m_todayCount;
   datetime m_todayStart;

   double Median(double &values[], int n)
     {
      double sorted[];
      ArrayResize(sorted, n);
      ArrayCopy(sorted, values, 0, 0, n);
      ArraySort(sorted);
      if(n % 2 == 1)
         return sorted[n / 2];
      return (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0;
     }

   void PushDailyAverage(double avg)
     {
      m_dailyAvgSpread[m_bufferHead] = avg;
      m_bufferHead = (m_bufferHead + 1) % SPREAD_GUARD_BASELINE_DAYS;
      if(m_bufferCount < SPREAD_GUARD_BASELINE_DAYS)
         m_bufferCount++;
     }

public:
   CSpreadAnomalyGuard()
     {
      ArrayInitialize(m_dailyAvgSpread, 0.0);
      m_bufferCount = 0;
      m_bufferHead  = 0;
      m_todaySum    = 0.0;
      m_todayCount  = 0;
      m_todayStart  = 0;
     }

   //+------------------------------------------------------------------+
   //| A charton MAR elerheto historikus barokbol tolti fel a bazis-     |
   //| puffert (ugyanaz a minta, mint BackfillClassifier() a fo EA-ban)  |
   //| -- friss inditas/ujraforditas utan NE kelljen kb. 3 hetet varni,  |
   //| mire a vedelem eleg adatot lat. Az MqlRates.spread mezo (pontban) |
   //| mar tartalmazza a historikus atlag-spreadet baronkent.            |
   //+------------------------------------------------------------------+
   void Backfill(string symbol, ENUM_TIMEFRAMES timeframe)
     {
      int barsPerDay = (int)MathRound(86400.0 / PeriodSeconds(timeframe));
      int needed = barsPerDay * (SPREAD_GUARD_BASELINE_DAYS + 2);

      MqlRates rates[];
      ArraySetAsSeries(rates, false);   // kronologikus sorrend kell (0=legregebbi)
      int copied = CopyRates(symbol, timeframe, 1, needed, rates);
      if(copied <= 0)
        {
         PrintFormat("⚠️ SpreadAnomalyGuard: nem sikerult historikus adatot lekerni a bazis-"
                     "feltoltéshez (hiba: %d) -- a vedelem %d nap alatt magatol felepül.",
                     GetLastError(), SPREAD_GUARD_MIN_BASELINE_DAYS);
         return;
        }

      datetime dayCursor = 0;
      double sum = 0.0;
      int count = 0;
      for(int i = 0; i < copied; i++)
        {
         datetime barDay = rates[i].time - (rates[i].time % 86400);
         if(dayCursor == 0)
            dayCursor = barDay;
         if(barDay != dayCursor)
           {
            if(count >= SPREAD_GUARD_MIN_SAMPLES_PER_DAY)
               PushDailyAverage(sum / count);
            sum = 0.0;
            count = 0;
            dayCursor = barDay;
           }
         sum += (double)rates[i].spread;
         count++;
        }
      // az utolso (meg folyamatban levo/ma) napot szandekosan NEM zarjuk le itt -- azt az elo
      // OnNewBar() zarja majd le, amikor tenyleges napvaltast eszlel.

      PrintFormat("SpreadAnomalyGuard bazis feltoltve: %d nap (kert: max %d), median=%.1f pont.",
                  m_bufferCount, SPREAD_GUARD_BASELINE_DAYS, BaselineMedian());
     }

   //+------------------------------------------------------------------+
   //| Minden UJ baron hivando (a fo EA "csak uj gyertyan dontunk"        |
   //| kapuja utan) -- felhalmozza a mai nap spread-mintait, es          |
   //| napvaltaskor lezarja az elozo napot a bazis-puffer fele.           |
   //+------------------------------------------------------------------+
   void OnNewBar(double currentSpread, datetime barTime)
     {
      datetime barDay = barTime - (barTime % 86400);
      if(m_todayStart == 0)
         m_todayStart = barDay;
      if(barDay != m_todayStart)
        {
         if(m_todayCount >= SPREAD_GUARD_MIN_SAMPLES_PER_DAY)
            PushDailyAverage(m_todaySum / m_todayCount);
         m_todaySum   = 0.0;
         m_todayCount = 0;
         m_todayStart = barDay;
        }
      m_todaySum += currentSpread;
      m_todayCount++;
     }

   //+------------------------------------------------------------------+
   //| true, ha VAN eleg bazis-adatunk ES az AKTUALIS (pillanatnyi)       |
   //| spread rendellenesen szeles a bazis-medianhoz kepest. Szandekosan  |
   //| a pillanatnyi (nem a mai napi atlag) spreadet hasonlitjuk, hogy a  |
   //| vedelem MAR a session elso baraitol kezdve mukodjon, ne csak       |
   //| miutan a mai nap sajat mintaszama mar elerte a kuszobot.            |
   //+------------------------------------------------------------------+
   bool IsAnomalous(double currentSpread)
     {
      if(m_bufferCount < SPREAD_GUARD_MIN_BASELINE_DAYS)
         return false;   // nincs eleg tortenelmi adat -- ne blokkoljon indokolatlanul
      double baselineMedian = BaselineMedian();
      if(baselineMedian <= 0.0)
         return false;
      return (currentSpread / baselineMedian) >= SPREAD_GUARD_ANOMALY_RATIO;
     }

   double BaselineMedian()
     {
      if(m_bufferCount == 0)
         return 0.0;
      double baseline[];
      ArrayResize(baseline, m_bufferCount);
      ArrayCopy(baseline, m_dailyAvgSpread, 0, 0, m_bufferCount);
      return Median(baseline, m_bufferCount);
     }

   int BaselineDayCount()
     {
      return m_bufferCount;
     }
  };
//+------------------------------------------------------------------+
