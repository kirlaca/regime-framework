//+------------------------------------------------------------------+
//| MarketHolidays.mqh -- AUTOMATIKUSAN GENERALVA, NE SZERKESZD KEZZEL |
//| Forras: optuna_research/regime_framework/data/market_holidays.json  |
//| Generator: regime_framework/deployment/generate_holiday_mqh.py      |
//| Uj ev/nap felvetelehez a JSON-t bovitsd, majd futtasd ujra a         |
//| generatort -- ez a fajl minden futtataskor teljesen ujrairodik.      |
//+------------------------------------------------------------------+
#property strict

//--- piaconkenti, zart/csokkentett-kereskedesi napok (YYYYMMDD egeszkent) ---
// US: NYSE/NASDAQ -- covers USTEC/US30/US500 (IC Markets) and US30Cash#/US500Cash#/US100Cash# (XM) (12 nap)
int g_holidayDates_US[] = {20260101, 20260119, 20260216, 20260403, 20260525, 20260619, 20260703, 20260907, 20261126, 20261127, 20261224, 20261225};

//+------------------------------------------------------------------+
//| true, ha a megadott szimbolum piaca zarva/csokkentett-kereskedesu   |
//| a megadott naptari napon (szerveridő YYYYMMDD egesz alakban -- lasd  |
//| DateToYyyymmdd()). Uj szimbolum hozzaadasakor a JSON                 |
//| symbol_market_map-jet bovitsd, NE ide irj kezzel uj if-agat.          |
//+------------------------------------------------------------------+
bool IsMarketHoliday(string symbol, int yyyymmdd)
  {
   if(symbol == "USTEC")
     {
      for(int i = 0; i < ArraySize(g_holidayDates_US); i++)
         if(g_holidayDates_US[i] == yyyymmdd)
            return true;
      return false;
     }
   else if(symbol == "US30")
     {
      for(int i = 0; i < ArraySize(g_holidayDates_US); i++)
         if(g_holidayDates_US[i] == yyyymmdd)
            return true;
      return false;
     }
   else if(symbol == "US500")
     {
      for(int i = 0; i < ArraySize(g_holidayDates_US); i++)
         if(g_holidayDates_US[i] == yyyymmdd)
            return true;
      return false;
     }
   else if(symbol == "US100Cash#")
     {
      for(int i = 0; i < ArraySize(g_holidayDates_US); i++)
         if(g_holidayDates_US[i] == yyyymmdd)
            return true;
      return false;
     }
   else if(symbol == "US500Cash#")
     {
      for(int i = 0; i < ArraySize(g_holidayDates_US); i++)
         if(g_holidayDates_US[i] == yyyymmdd)
            return true;
      return false;
     }
   else if(symbol == "US30Cash#")
     {
      for(int i = 0; i < ArraySize(g_holidayDates_US); i++)
         if(g_holidayDates_US[i] == yyyymmdd)
            return true;
      return false;
     }
   return false;   // ismeretlen szimbolum -- nincs naptar hozza, ne blokkoljon
  }

//+------------------------------------------------------------------+
//| Segedfuggveny: a megadott datetime YYYYMMDD egeszkent (szerveridő). |
//+------------------------------------------------------------------+
int DateToYyyymmdd(datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   return dt.year * 10000 + dt.mon * 100 + dt.day;
  }
