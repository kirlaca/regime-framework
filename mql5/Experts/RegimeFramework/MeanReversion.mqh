//+------------------------------------------------------------------+
//| MeanReversion.mqh                                                 |
//| A regime_framework Python MeanReversionComponent-jenek MQL5 portja|
//| (components/mean_reversion.py check_entry()-je).                  |
//|                                                                    |
//| FONTOS ELTERES a Python validate()-tol (lasd PLAN.md 0.1, 3.       |
//| szabaly): a Python oldali resolve_fixed_exit() egy BACKTEST-CSAK   |
//| pesszimista feloldas (melyik serul elobb egy gyertyan belul) - ez  |
//| itt NEM porolodik at. Elve a brokerre valodi SL/TP stop-megbizast  |
//| adunk at (lasd a fo EA OpenPosition()-jet), a broker donti el      |
//| elesben, mi serul.                                                 |
//|                                                                    |
//| A regime-kapu (csak RANGING trend_band mellett aktiv) a hivo (fo   |
//| EA) feladata - lasd IsRegimeEligible().                            |
//+------------------------------------------------------------------+
#property strict

#ifndef MEAN_REVERSION_MQH
#define MEAN_REVERSION_MQH

#include "RegimeClassifier.mqh"

// FONTOS: slDistance/tpDistance TAVOLSAG (ar-egysegben), NEM abszolut ar - a hivo (fo EA) a
// TENYLEGES elo ask/bid-hez kepest szamitja a vegso SL/TP-t nyitaskor, NEM a dontesi bazisul
// hasznalt lezart bar close-ahoz kepest (ami elteret az elo fill-tol) - lasd a fajl fejlec-
// docstringjet es a mar meglevo AnomalyMeanReversion_EA.mq5 OpenLong()/OpenShort() mintajat.
struct SSignal
  {
   bool   hasSignal;
   bool   isLong;      // true = LONG, false = SHORT
   double slDistance;
   double tpDistance;   // 0.0 = nincs fix TP (trailing-stop jellegu setup eseten)
  };

//+------------------------------------------------------------------+
class CMeanReversionComponent
  {
private:
   int      m_emaHandle;
   double   m_mrMultiplier;
   double   m_slMultiplier;
   double   m_riskRewardRatio;
   int      m_sessionStartHour, m_sessionStartMinute, m_sessionEndHour;

   bool IsSessionHour(int hour, int minute)
     {
      bool afterStart = (hour > m_sessionStartHour) ||
                         (hour == m_sessionStartHour && minute >= m_sessionStartMinute);
      return afterStart && hour < m_sessionEndHour;
     }

public:
   CMeanReversionComponent(int emaPeriod, double mrMultiplier, double slMultiplier, double riskRewardRatio,
                            int sessionStartHour = 16, int sessionStartMinute = 30, int sessionEndHour = 21)
     {
      m_mrMultiplier = mrMultiplier;
      m_slMultiplier = slMultiplier;
      m_riskRewardRatio = riskRewardRatio;
      m_sessionStartHour = sessionStartHour;
      m_sessionStartMinute = sessionStartMinute;
      m_sessionEndHour = sessionEndHour;
      m_emaHandle = iMA(_Symbol, PERIOD_CURRENT, emaPeriod, 0, MODE_EMA, PRICE_CLOSE);
     }

   ~CMeanReversionComponent()
     {
      if(m_emaHandle != INVALID_HANDLE)
         IndicatorRelease(m_emaHandle);
     }

   bool IsRegimeEligible(ETrendBand trendBand) const { return trendBand == TREND_RANGING; }

   double GetEma(int shift)
     {
      double buf[];
      ArraySetAsSeries(buf, true);
      if(CopyBuffer(m_emaHandle, 0, shift, 1, buf) <= 0)
         return 0.0;
      return buf[0];
     }

   //--- close/atr a hivo (fo EA) mar lezart bar-jarol jon at (lasd RegimeClassifier.mqh OnNewBar
   //    mintaja - "csak lezart bar-on dontunk"), hogy ez az osztaly ne fuggjon kozvetlenul MT5
   //    idozitestol/API-hivasoktol a sajat EMA lekerdezesen kivul.
   SSignal CheckEntry(int hour, int minute, ETrendBand trendBand, double close, double atr)
     {
      SSignal sig;
      sig.hasSignal = false;
      sig.tpDistance = 0.0;

      if(!IsRegimeEligible(trendBand))
         return sig;
      if(!IsSessionHour(hour, minute))
         return sig;

      double emaCenter = GetEma(1);
      if(emaCenter == 0.0 || atr == 0.0)
         return sig;

      double channelHigh = emaCenter + atr * m_mrMultiplier;
      double channelLow  = emaCenter - atr * m_mrMultiplier;
      double slDist = atr * m_slMultiplier;

      if(close > channelHigh)
        {
         sig.hasSignal = true;
         sig.isLong = false;
         sig.slDistance = slDist;
         sig.tpDistance = slDist * m_riskRewardRatio;
        }
      else if(close < channelLow)
        {
         sig.hasSignal = true;
         sig.isLong = true;
         sig.slDistance = slDist;
         sig.tpDistance = slDist * m_riskRewardRatio;
        }
      return sig;
     }
  };

#endif // MEAN_REVERSION_MQH
//+------------------------------------------------------------------+
