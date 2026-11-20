//+------------------------------------------------------------------+
//| LastHourContinuation.mqh                                          |
//| A regime_framework Python LastHourContinuationComponent-jenek     |
//| MQL5 portja (components/last_hour_continuation.py check_entry()/  |
//| check_exit()-je).                                                  |
//|                                                                    |
//| FONTOS ELTERES a tobbi (MeanReversion/TrendFollowing) komponenshez |
//| kepest: ez NEM egy trend_band-hez kotott, XOR-dispatch-elt         |
//| komponens - IDOABLAK-ALAPU, a `trend_band`-tol FUGGETLEN ("time-   |
//| gated"), lasd core/engine.py modul-docstringjet es a fo EA         |
//| OnTick()-jenek megjegyzeset. IsRegimeEligible() ezert MINDIG true-t|
//| ad vissza - a hivo (fo EA) csak akkor probalja meg CheckEntry()-t  |
//| hivni, ha a rendes trend_band-alapu komponens (MeanReversion/      |
//| TrendFollowing) az adott baron NEM jelzett.                        |
//|                                                                    |
//| A "trend_return" (a nap [sessionStart, finalHourStart) ablakanak   |
//| kumulalt log-hozama) a MAR LEZART barokbol, visszafele szamlalva   |
//| all elo - lasd ComputeTrendReturn(). Ez UGYANAZ a szamitas, mint a |
//| Python prepare_indicators()-ben, csak ott egy elore legyartott     |
//| oszlopon, itt elo, bar-onkenti visszaszamlalasal.                  |
//|                                                                    |
//| A belepes csak a nap UTOLSO trend-ablak-baran probalkozik (lasd    |
//| IsFinalTrendBar()) - ugyanaz az idopont, ahol a Python `check_     |
//| entry()`-je a `trend_return`-t megkapja. A zarasi-ablak kenyszer-  |
//| zarasat (is_session_end_bar Python oldalon) a fo EA OnTick()-je    |
//| vegzi kulon, MERT ez korabbi hatarido, mint a meglevo altalanos    |
//| InpForceCloseHour EOD-zaras - lasd IsSessionEndBar().              |
//+------------------------------------------------------------------+
#property strict

#ifndef LAST_HOUR_CONTINUATION_MQH
#define LAST_HOUR_CONTINUATION_MQH

#include "RegimeClassifier.mqh"
#include "MeanReversion.mqh"   // SSignal struct innen ujrahasznositva
#include "UsDst.mqh"

//+------------------------------------------------------------------+
class CLastHourContinuationComponent
  {
private:
   double   m_slAtrMultiplier;
   int      m_sessionStartHour, m_sessionStartMinute;
   int      m_finalHourStart;
   int      m_sessionEndHour;
   int      m_minTrendBars;
   bool     m_dstAware;

   //--- true, ha `hour`/`minute` a napi TREND-ABLAKBA esik: [sessionStart, finalHourStart) -
   //    lasd Python _in_trend_window(). `dstShift` -- lasd CurrentDstShift().
   bool InTrendWindow(int hour, int minute, int dstShift)
     {
      int startHour = m_sessionStartHour + dstShift;
      int finalHour = m_finalHourStart + dstShift;
      bool afterStart = (hour > startHour) || (hour == startHour && minute >= m_sessionStartMinute);
      return afterStart && hour < finalHour;
     }

   //--- 0 (valtozatlan, "nyari" orak) ha m_dstAware=false VAGY amerikai DST aktiv az aktualis
   //    baron; 1 (session-orak +1 orara tolva) ha m_dstAware=true ES amerikai DST INAKTIV (tel) --
   //    lasd UsDst.mqh es core/us_session.py Python megfeleloje. A jelenleg indulo bar datumat
   //    hasznaljuk (a trend-ablak egy napon belul van, eleg egyszer szamolni hivasonkent).
   int CurrentDstShift()
     {
      if(!m_dstAware)
         return 0;
      datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
      return UsDstHourShift(barTime);
     }

public:
   CLastHourContinuationComponent(double slAtrMultiplier = 2.5,
                                   int sessionStartHour = 16, int sessionStartMinute = 30,
                                   int finalHourStart = 20, int sessionEndHour = 21,
                                   int minTrendBars = 10, bool dstAware = false)
     {
      m_slAtrMultiplier = slAtrMultiplier;
      m_sessionStartHour = sessionStartHour;
      m_sessionStartMinute = sessionStartMinute;
      m_finalHourStart = finalHourStart;
      m_sessionEndHour = sessionEndHour;
      m_minTrendBars = minTrendBars;
      // `dstAware` -- lasd UsDst.mqh es core/us_session.py fejlec-kommentjet. SZANDEKOSAN false
      // alapertelmezett, hogy a jelenleg elesben hivo kod (parameter nelkul) bit-pontosan
      // valtozatlan maradjon, amig ezt valaki explicit be nem kapcsolja.
      m_dstAware = dstAware;
     }

   //--- szandekosan MINDIG true - lasd fajl fejlec-docstring. A trend_band-fuggetlenseg maga a
   //    "time_gated_components" koncepcio lenyege (lasd core/engine.py).
   bool IsRegimeEligible(ETrendBand trendBand) const { return true; }

   //--- `hour`/`minute` a MOST INDULO bar kezdete (= a mar lezart bar vege), ugyanaz a
   //    konvencio, mint a tobbi komponensnel (lasd MeanReversion.mqh/TrendFollowing.mqh
   //    IsSessionHour()-je) - ez pontosan akkor igaz, amikor a mar lezart bar (bar[1]) volt a
   //    nap UTOLSO trend-ablak-baraja.
   bool IsFinalTrendBar(int hour, int minute)
     {
      int dstShift = CurrentDstShift();
      return hour == (m_finalHourStart + dstShift) && minute == 0;
     }

   //--- true, ha ez a most-indulo bar mar a zarasi-ablakon (session_end) TUL van - ekkor kell a
   //    fo EA-nak zarnia a LastHourContinuation altal nyitott poziciot (lasd Python
   //    is_session_end_bar - a nap utolso, [finalHourStart, sessionEndHour) tartomanyba eso
   //    baraja utani elso bar).
   bool IsSessionEndBar(int hour, int minute)
     {
      int dstShift = CurrentDstShift();
      return hour >= (m_sessionEndHour + dstShift);
     }

   //--- A napi trend-ablak kumulalt log-hozama ([sessionStart, finalHourStart) tartomany, a MAR
   //    LEZART barokbol, bar[1]-tol visszafele szamlalva) - `isValid` false, ha nem volt eleg
   //    (>= m_minTrendBars) bar a mai ablakban (pl. rovidebb/unnepi kereskedesi nap). Lasd Python
   //    prepare_indicators(): trend_return = log(close[utolso trend-bar] / close[elso trend-bar]).
   //
   //    JAVITAS (2026-09-11, code review + felhasznaloi kockazat-attekintes utan -- lasd
   //    optuna_research repo SESSION_LOG.md): a visszasetalas korabban KIZAROLAG ora/percet
   //    nezett (InTrendWindow()), a naptari NAPOT nem -- elmeletileg, ha egy adott napon a
   //    00:00-16:20 savban NINCS bar (pl. a szimbolum aznap csak 16:30-kor kezdene arazodni),
   //    a visszasetalas csendben atcsuszhatna az ELOZO nap sajat trend-ablakaba, es a ket nap
   //    adatat osszemosna. A leggyakoribb kivalto ok (piaci unnepnap) mar korabban is ki volt zarva
   //    (IsMarketHoliday() a teljes napot blokkolja UJ belepesre, LHC-re is, MIELOTT ez a fuggveny
   //    egyaltalan lefutna), es 55 920 valos baron (kb. 20 honap) 0 esetben jelentkezett a hiba
   //    ELOTTE sem -- de olcso, biztonsagos vedelem, ezert most explicit dátum-hatart is huzunk:
   //    a shift=1 bar naptari napjat (`windowDay`) rogzitjuk, es megallunk, ha egy korabbi bar
   //    MAR MAS napra esik, meg akkor is, ha annak ora/perce veletlenul az ablakba esne.
   double ComputeTrendReturn(bool &isValid)
     {
      isValid = false;
      int count = 0;
      double lastClose = 0.0, firstClose = 0.0;
      datetime windowDay = 0;   // a shift=1 bar naptari napja (00:00-ra kerekitve)
      int dstShift = CurrentDstShift();   // a trend-ablak egy napon belul van, eleg egyszer szamolni

      for(int shift = 1; shift <= 200; shift++)   // 200 bar bosegesen eleg biztonsagi felso korlat
        {
         datetime t = iTime(_Symbol, PERIOD_CURRENT, shift);
         if(t == 0)
            break;
         datetime barDay = t - (t % 86400);
         if(shift == 1)
            windowDay = barDay;
         else if(barDay != windowDay)
            break;   // JAVITAS: mar egy MASIK naptari napra estunk vissza -- allj meg, ne mosd ossze
         MqlDateTime dt;
         TimeToStruct(t, dt);
         if(!InTrendWindow(dt.hour, dt.min, dstShift))
            break;   // visszafele haladva kileptunk az ablakbol - elertuk a nap elejet

         double c = iClose(_Symbol, PERIOD_CURRENT, shift);
         count++;
         if(count == 1)
            lastClose = c;    // shift=1 = a nap UTOLSO trend-ablak-baraja
         firstClose = c;      // az utolso ervenyes iteracio = a nap ELSO trend-ablak-baraja
        }

      if(count < m_minTrendBars || lastClose == 0.0 || firstClose == 0.0)
         return 0.0;

      isValid = true;
      return MathLog(lastClose / firstClose);
     }

   //--- Csak a nap utolso trend-ablak-baran ad jelet, es csak POZITIV trend_return eseten (LONG-
   //    only, lasd Python docstring: lefele trend-napokon nincs kimutathato el). SL natic broker
   //    stop-megbizaskent megy at, ugyanugy, mint a MeanReversion-nel - nincs trailing.
   SSignal CheckEntry(int hour, int minute, double atr)
     {
      SSignal sig;
      sig.hasSignal = false;
      sig.tpDistance = 0.0;   // szandekosan nincs fix TP - a session-veg zaras hatarolja az idot

      if(!IsFinalTrendBar(hour, minute))
         return sig;
      if(atr == 0.0)
         return sig;

      bool isValid;
      double trendReturn = ComputeTrendReturn(isValid);
      if(!isValid || trendReturn <= 0.0)
         return sig;

      sig.hasSignal = true;
      sig.isLong = true;
      sig.slDistance = atr * m_slAtrMultiplier;
      return sig;
     }
  };

#endif // LAST_HOUR_CONTINUATION_MQH
//+------------------------------------------------------------------+
