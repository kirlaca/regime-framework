//+------------------------------------------------------------------+
//| TrendFollowing.mqh                                                 |
//| A regime_framework Python TrendFollowingComponent-jenek MQL5 portja|
//| (components/trend_following.py check_entry()/check_exit()-je).    |
//|                                                                    |
//| A trailing stop MEGMARAD elesben is (ez NEM backtest-csak         |
//| mechanizmus, valodi, elo kereskedesben is ertelmes - lasd PLAN.md  |
//| 0.1, 3. szabaly kommentjet a kulonbsegrol) - de itt a broker       |
//| NATIV SL-jet frissitjuk PositionModify()-val minden uj baron,      |
//| NEM egy backtest-only allapot-valtozoval szimulaljuk. A tenyleges  |
//| PositionModify()-hivas a fo EA feladata (lasd UpdateTrailingStop());|
//| ez az osztaly csak a SZAMITAST vegzi (ComputeTrailSl()).           |
//|                                                                    |
//| Az RSI szandekosan EGYSZERU (nem Wilder-simitott, lasd             |
//| core/indicators.py compute_rsi()) - az MQL5 beepitett iRSI()       |
//| Wilder-simitast hasznal, ami MAS eredmenyt adna (PLAN.md 0.1,      |
//| 2. szabaly). Az EMA-khoz viszont a beepitett iMA(MODE_EMA)-t       |
//| hasznaljuk, ugyanugy, mint a mar meglevo referencia-EA             |
//| (AnomalyMeanReversion_EA.mq5) - ott a seedeles-kulonbseg egy       |
//| elhanyagolhato, kifuto tranziens, NEM egy mas keplet, mint az      |
//| ATR/ADX/RSI Wilder-vs-egyszeru esete.                              |
//|                                                                    |
//| BOLLINGER-KITORES MEGERoSITES (hozzaadva 2026-08-20, portolva a    |
//| Python components/trend_following.py azonos valtoztatasabol -     |
//| lasd annak fejlec-docstringjet a teljes kutatasi lancert): a       |
//| belepes mostantol MEGKOVETELI, hogy a zaroar a Bollinger-szalagon  |
//| KIVUL legyen (a trend iranyaba), az EMA-sorrend/RSI-felteteleken   |
//| FELUL. A szalagot KEZILEG szamitjuk (ComputeBollinger()), NEM a    |
//| beepitett iBands()-szel - az iBands NEPESSEGI szorast hasznal      |
//| (N nevezovel), a Python pandas .std() viszont MINTA-szorast        |
//| (N-1 nevezovel) - ez a beepitett fuggvennyel egy csendes,          |
//| dokumentalatlan sav-szelesseg-elteres lenne (PLAN.md 0.1, 2.       |
//| szabaly: indikator-kepletek eltereset dokumentalni kell).          |
//+------------------------------------------------------------------+
#property strict

#ifndef TREND_FOLLOWING_MQH
#define TREND_FOLLOWING_MQH

#include "RegimeClassifier.mqh"
#include "MeanReversion.mqh"   // SSignal struct innen ujrahasznositva

//+------------------------------------------------------------------+
class CTrendFollowingComponent
  {
private:
   int      m_fastEmaHandle, m_slowEmaHandle;
   double   m_slAtrMultiplier;
   double   m_trailAtrMultiplier;
   double   m_rsiLongMin;
   double   m_rsiShortMax;
   int      m_rsiPeriod;
   int      m_bollingerPeriod;
   double   m_bollingerK;
   int      m_sessionStartHour, m_sessionStartMinute, m_sessionEndHour;

   bool IsSessionHour(int hour, int minute)
     {
      bool afterStart = (hour > m_sessionStartHour) ||
                         (hour == m_sessionStartHour && minute >= m_sessionStartMinute);
      return afterStart && hour < m_sessionEndHour;
     }

   //--- Egyszeru (NEM Wilder-simitott) RSI - lasd core/indicators.py compute_rsi() docstringjet.
   double GetSimpleRsi(int period, int shift)
     {
      int needed = period + shift + 1;
      double close[];
      ArraySetAsSeries(close, true);
      if(CopyClose(_Symbol, PERIOD_CURRENT, 0, needed, close) <= 0)
         return 50.0;

      double gainSum = 0.0, lossSum = 0.0;
      for(int i = shift; i < shift + period; i++)
        {
         double delta = close[i] - close[i + 1];
         if(delta > 0.0)
            gainSum += delta;
         else
            lossSum += -delta;
        }
      double avgGain = gainSum / period;
      double avgLoss = lossSum / period;
      if(avgLoss == 0.0)
         return 100.0;
      double rs = avgGain / avgLoss;
      return 100.0 - (100.0 / (1.0 + rs));
     }

   //--- Bollinger-szalag KEZI szamitasa - lasd fajl fejlec-docstring, miert nem a beepitett
   //    iBands()-szel (nepessegi vs. minta-szoras eltero). upper/lower 0.0, ha nincs eleg adat.
   void ComputeBollinger(int period, double k, int shift, double &upper, double &lower)
     {
      int needed = period + shift;
      double close[];
      ArraySetAsSeries(close, true);
      if(CopyClose(_Symbol, PERIOD_CURRENT, 0, needed, close) < needed)
        {
         upper = 0.0;
         lower = 0.0;
         return;
        }

      double sum = 0.0;
      for(int i = shift; i < shift + period; i++)
         sum += close[i];
      double mean = sum / period;

      double sqSum = 0.0;
      for(int i = shift; i < shift + period; i++)
         sqSum += (close[i] - mean) * (close[i] - mean);
      double std = MathSqrt(sqSum / (period - 1));   // MINTA-szoras (N-1), mint a pandas .std()

      upper = mean + k * std;
      lower = mean - k * std;
     }

public:
   CTrendFollowingComponent(double fastEmaDays, double slowEmaDays, double slAtrMultiplier,
                             double trailAtrMultiplier, double rsiLongMin, double rsiShortMax,
                             int barsPerDay = 144, int rsiPeriod = 14,
                             int bollingerPeriod = 20, double bollingerK = 2.0,
                             int sessionStartHour = 16, int sessionStartMinute = 30, int sessionEndHour = 21)
     {
      int fastSpan = (int)MathMax(2, MathRound(fastEmaDays * barsPerDay));
      int slowSpan = (int)MathMax(3, MathRound(slowEmaDays * barsPerDay));
      m_fastEmaHandle = iMA(_Symbol, PERIOD_CURRENT, fastSpan, 0, MODE_EMA, PRICE_CLOSE);
      m_slowEmaHandle = iMA(_Symbol, PERIOD_CURRENT, slowSpan, 0, MODE_EMA, PRICE_CLOSE);
      m_slAtrMultiplier = slAtrMultiplier;
      m_trailAtrMultiplier = trailAtrMultiplier;
      m_rsiLongMin = rsiLongMin;
      m_rsiShortMax = rsiShortMax;
      m_rsiPeriod = rsiPeriod;
      m_bollingerPeriod = bollingerPeriod;
      m_bollingerK = bollingerK;
      m_sessionStartHour = sessionStartHour;
      m_sessionStartMinute = sessionStartMinute;
      m_sessionEndHour = sessionEndHour;
     }

   ~CTrendFollowingComponent()
     {
      if(m_fastEmaHandle != INVALID_HANDLE)
         IndicatorRelease(m_fastEmaHandle);
      if(m_slowEmaHandle != INVALID_HANDLE)
         IndicatorRelease(m_slowEmaHandle);
     }

   bool IsRegimeEligible(ETrendBand trendBand) const { return trendBand == TREND_TRENDING; }

   double GetEma(int handle, int shift)
     {
      double buf[];
      ArraySetAsSeries(buf, true);
      if(CopyBuffer(handle, 0, shift, 1, buf) <= 0)
         return 0.0;
      return buf[0];
     }

   //--- Allapot-alapu belepes (NEM a pontos keresztezesi bar-t varja) - lasd a Python komponens
   //    fejlec-docstringjenek TORTENET szakaszat, miert valtottunk erre a keresztezes-alapu
   //    valtozatrol (2026-08-19, kev es trade-szam volt a szuk session-ablak miatt).
   SSignal CheckEntry(int hour, int minute, ETrendBand trendBand, double close, double atr)
     {
      SSignal sig;
      sig.hasSignal = false;
      sig.tpDistance = 0.0;   // szandekosan nincs fix TP - a trailing stop engedi "futni"

      if(!IsRegimeEligible(trendBand))
         return sig;
      if(!IsSessionHour(hour, minute))
         return sig;

      double fastNow = GetEma(m_fastEmaHandle, 1);
      double slowNow = GetEma(m_slowEmaHandle, 1);
      if(fastNow == 0.0 || slowNow == 0.0 || atr == 0.0)
         return sig;

      double rsi = GetSimpleRsi(m_rsiPeriod, 1);

      double bbUpper, bbLower;
      ComputeBollinger(m_bollingerPeriod, m_bollingerK, 1, bbUpper, bbLower);
      if(bbUpper == 0.0 && bbLower == 0.0)
         return sig;

      if(fastNow > slowNow && rsi >= m_rsiLongMin && close > bbUpper)
        {
         sig.hasSignal = true;
         sig.isLong = true;
         sig.slDistance = atr * m_slAtrMultiplier;
        }
      else if(fastNow < slowNow && rsi <= m_rsiShortMax && close < bbLower)
        {
         sig.hasSignal = true;
         sig.isLong = false;
         sig.slDistance = atr * m_slAtrMultiplier;
        }
      return sig;
     }

   //--- Trailing stop UJ jelolt SL-je - a hivo (fo EA) felelossege eldonteni, hogy ez szigorubb-e
   //    a jelenlegi SL-nel (csak akkor hivja a PositionModify()-t - a stop soha nem lazulhat),
   //    es frissiteni a trendExtreme allapotot (lasd a fo EA UpdateTrailingStop()-jat).
   double ComputeTrailSl(bool isLong, double trendExtreme, double atr)
     {
      if(isLong)
         return trendExtreme - atr * m_trailAtrMultiplier;
      return trendExtreme + atr * m_trailAtrMultiplier;
     }
  };

#endif // TREND_FOLLOWING_MQH
//+------------------------------------------------------------------+
