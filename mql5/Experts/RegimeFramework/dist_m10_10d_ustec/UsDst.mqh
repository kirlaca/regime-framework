//+------------------------------------------------------------------+
//| UsDst.mqh                                                          |
//| Amerikai DST (nyari idoszamitas, 2007 utani szabaly: marcius 2.    |
//| vasarnapja - november 1. vasarnapja) determinisztikus, naptar-     |
//| alapu szamitasa. Az MQL5-nek nincs zoneinfo-szeru idozona-         |
//| adatbazisa, ezert kezzel szamoljuk a datumhatarokat - ugyanaz az   |
//| elv, mint a Python `core/us_session.py` us_dst_hour_shift()-je,    |
//| csak explicit szaballyal a `zoneinfo` helyett.                     |
//|                                                                    |
//| KONTEXTUS (2026-09-14, elesben eszlelt felhasznaloi megfigyeles +  |
//| `research/dst_fix_validation.py` empirikus megerositese): a broker |
//| szervere FIX UTC+3-on fut, NEM koveti a DST-t -- a valos amerikai  |
//| piacnyitas (9:30 America/New_York) szerveridoben 16:30 (nyar) es   |
//| 17:30 (tel) kozott vandorol. A pontossag napi (nem masodperces)    |
//| granularitasu -- a tenyleges valtas oraja (2:00 helyi ido) nem     |
//| szamit bar-naponkenti hasznalatra.                                 |
//+------------------------------------------------------------------+
#property strict

#ifndef US_DST_MQH
#define US_DST_MQH

//--- az adott honap N-edik VASARNAPJANAK napja (1-alapu N, pl. N=2 marciusban a masodik vasarnap).
int NthSundayOfMonth(int year, int month, int n)
  {
   MqlDateTime dt;
   dt.year = year; dt.mon = month; dt.day = 1; dt.hour = 0; dt.min = 0; dt.sec = 0;
   datetime firstOfMonth = StructToTime(dt);
   TimeToStruct(firstOfMonth, dt);
   // MQL5 day_of_week: 0=Vasarnap...6=Szombat.
   int firstSunday = 1 + ((7 - dt.day_of_week) % 7);
   return firstSunday + (n - 1) * 7;
  }

//--- 0, ha az adott datumon amerikai nyari idoszamitas (DST) van ervenyben -- a jelenlegi,
//    hardkodolt session-orak erre vannak kalibralva --, 1, ha nincs (teli, a valos amerikai
//    nyitas egy oraval kesobb esik a FIX UTC+3-on futo szerver idejehez kepest). Lasd
//    core/us_session.py us_dst_hour_shift() Python megfeleloje.
int UsDstHourShift(datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   int dstStartDay = NthSundayOfMonth(dt.year, 3, 2);    // marcius 2. vasarnapja
   int dstEndDay   = NthSundayOfMonth(dt.year, 11, 1);   // november 1. vasarnapja

   bool afterStart = (dt.mon > 3) || (dt.mon == 3 && dt.day >= dstStartDay);
   bool beforeEnd  = (dt.mon < 11) || (dt.mon == 11 && dt.day < dstEndDay);
   bool isDst = afterStart && beforeEnd;
   return isDst ? 0 : 1;
  }

#endif // US_DST_MQH
//+------------------------------------------------------------------+
