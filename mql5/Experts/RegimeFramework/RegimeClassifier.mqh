//+------------------------------------------------------------------+
//| RegimeClassifier.mqh                                              |
//| A regime_framework Python MarketConditionClassifier-jenek elo,    |
//| bar-onkenti (streaming) MQL5 megfeleloje.                         |
//|                                                                    |
//| FONTOS: ez az algoritmus a scratchpad/streaming_classifier_       |
//| reference.py-ban lett ELOSZOR Pythonban megepitve es bebizonyitva,|
//| hogy bar-onkent BIT-PONTOSAN egyezik a mar validalt, batch pandas-|
//| alapu regime/market_condition.py MarketConditionClassifier.       |
//| classify_series()-szel (23014 bar, 0 elteres). Ez a fajl ANNAK a  |
//| mar bizonyitott algoritmusnak a soronkenti MQL5 atirasa - a       |
//| SZINTAXIST viszont innen nem lehet leforditani/tesztelni, azt a   |
//| MetaEditor + Strategy Tester kell megerositse (lasd PLAN.md 0.1,  |
//| 5. szabaly: "portolhatosag es validitas ket kulon kerdes").       |
//|                                                                    |
//| Az ATR/ADX szamitasa SZANDEKOSAN egyszeru (nem Wilder-simitott),  |
//| hogy megegyezzen a core/indicators.py compute_simple_atr()/       |
//| compute_adx()-evel - lasd PLAN.md 0.1, 2. szabaly.                |
//|                                                                    |
//| A pandas .rolling(window).rank(pct=True) helyettesitese: a        |
//| PercentileRank() az un. "average rank" kepletet hasznalja          |
//| holtverseny eseten (ugyanaz, mint a pandas rank(method='average') |
//| alapertelmezett viselkedese) - lasd a fuggveny kommentjet.        |
//+------------------------------------------------------------------+
#property strict

#ifndef REGIME_CLASSIFIER_MQH
#define REGIME_CLASSIFIER_MQH

#define REGIME_ROLLING_WINDOW_BARS 8640   // ~60 kereskedesi nap M10-en, lasd regime/market_condition.py
#define REGIME_TR_DM_PERIOD        14     // ATR/ADX belso simitasi periodusa (NEM a rezsim-ablak)
#define REGIME_TREND_CUT_LOW       0.33
#define REGIME_TREND_CUT_HIGH      0.67

enum ETrendBand { TREND_RANGING, TREND_TRANSITIONAL, TREND_TRENDING, TREND_UNKNOWN };
enum EVolBand   { VOL_LOW, VOL_HIGH, VOL_UNKNOWN };

//+------------------------------------------------------------------+
class CMarketConditionClassifier
  {
private:
   //--- 14-bar-os kor-pufferek a TR/+DM/-DM egyszeru mozgoatlagahoz
   double   m_trBuf[REGIME_TR_DM_PERIOD];
   double   m_plusDmBuf[REGIME_TR_DM_PERIOD];
   double   m_minusDmBuf[REGIME_TR_DM_PERIOD];
   int      m_trDmWriteIdx;
   int      m_trDmFillCount;

   //--- 14-bar-os kor-puffer a DX egyszeru mozgoatlagahoz (ez adja az ADX-et)
   double   m_dxBuf[REGIME_TR_DM_PERIOD];
   int      m_dxWriteIdx;
   int      m_dxFillCount;

   //--- ~8640-bar-os gordulo ablak az ATR/ADX percentilis-rangjahoz
   double   m_atrWindow[REGIME_ROLLING_WINDOW_BARS];
   double   m_adxWindow[REGIME_ROLLING_WINDOW_BARS];
   int      m_windowWriteIdx;
   int      m_windowFillCount;

   //--- elozo (lezart) bar OHLC-je a TR/+DM/-DM szamitasahoz
   bool     m_hasPrevBar;
   double   m_prevHigh, m_prevLow, m_prevClose;

   //--- utolso ervenyes eredmenyek
   double     m_lastAtr, m_lastAdx;
   ETrendBand m_lastTrendBand;
   EVolBand   m_lastVolBand;
   bool       m_isReady;   // true, ha a teljes ~8640-bar-os ablak feltoltodott

   //--- egyszeru mozgoatlag egy kor-pufferen (a jelenleg feltoltott elemszamon)
   double RollingMean(const double &buf[], int fillCount)
     {
      if(fillCount <= 0)
         return 0.0;
      double sum = 0.0;
      for(int i = 0; i < fillCount; i++)
         sum += buf[i];
      return sum / fillCount;
     }

   //--- TR/+DM/-DM egyutt tolodik egy kozos indexen, hogy a harom puffer soha ne csusszon szet
   void PushTrDm(double tr, double plusDm, double minusDm)
     {
      m_trBuf[m_trDmWriteIdx] = tr;
      m_plusDmBuf[m_trDmWriteIdx] = plusDm;
      m_minusDmBuf[m_trDmWriteIdx] = minusDm;
      m_trDmWriteIdx = (m_trDmWriteIdx + 1) % REGIME_TR_DM_PERIOD;
      if(m_trDmFillCount < REGIME_TR_DM_PERIOD)
         m_trDmFillCount++;
     }

   void PushDx(double dx)
     {
      m_dxBuf[m_dxWriteIdx] = dx;
      m_dxWriteIdx = (m_dxWriteIdx + 1) % REGIME_TR_DM_PERIOD;
      if(m_dxFillCount < REGIME_TR_DM_PERIOD)
         m_dxFillCount++;
     }

   //--- ATR/ADX egyutt tolodik egy kozos indexen, ugyanazon okbol, mint PushTrDm()
   void PushWindow(double atrValue, double adxValue)
     {
      m_atrWindow[m_windowWriteIdx] = atrValue;
      m_adxWindow[m_windowWriteIdx] = adxValue;
      m_windowWriteIdx = (m_windowWriteIdx + 1) % REGIME_ROLLING_WINDOW_BARS;
      if(m_windowFillCount < REGIME_ROLLING_WINDOW_BARS)
         m_windowFillCount++;
     }

   //--- Atlag-rangsoroláson (average rank, holtversenynel) alapulo percentilis-rang - ugyanaz,
   //    mint a pandas Series.rank(pct=True) alapertelmezett viselkedese. A currentValue-nak MAR
   //    bent kell lennie a buf-ban (a hivo a PUSH UTAN hivja ezt), hogy a sajat maga altal
   //    alkotott ablakhoz kepest rangsorolodjon - ugyanugy, mint a pandas .rolling(w).rank().
   double PercentileRank(const double &buf[], int fillCount, double currentValue)
     {
      if(fillCount <= 0)
         return -1.0;
      int lessCount = 0, equalCount = 0;
      for(int i = 0; i < fillCount; i++)
        {
         if(buf[i] < currentValue)
            lessCount++;
         else if(buf[i] == currentValue)
            equalCount++;
        }
      double rank = lessCount + (equalCount + 1) / 2.0;
      return rank / fillCount;
     }

public:
   CMarketConditionClassifier()
     {
      m_trDmWriteIdx = 0; m_trDmFillCount = 0;
      m_dxWriteIdx = 0; m_dxFillCount = 0;
      m_windowWriteIdx = 0; m_windowFillCount = 0;
      m_hasPrevBar = false;
      m_isReady = false;
      m_lastAtr = 0.0; m_lastAdx = 0.0;
      m_lastTrendBand = TREND_UNKNOWN;
      m_lastVolBand = VOL_UNKNOWN;
     }

   //--- Minden LEZART bar-on EGYSZER hivando (nem minden tick-en) - lasd az EA OnTick() "csak uj
   //    bar nyitasakor" mintajat, ugyanugy, mint az AnomalyMeanReversion_EA.mq5-ben.
   //    Visszaadja, hogy ezen a baron mar ervenyes-e a besorolas (IsReady()-vel is lekerdezheto).
   bool OnNewBar(double high, double low, double close)
     {
      if(!m_hasPrevBar)
        {
         m_prevHigh = high; m_prevLow = low; m_prevClose = close;
         m_hasPrevBar = true;
         return false;   // az elso bar-nal nincs elozo close/high/low -> nincs TR/DM
        }

      double upMove = high - m_prevHigh;
      double downMove = m_prevLow - low;
      double plusDm = (upMove > downMove && upMove > 0.0) ? upMove : 0.0;
      double minusDm = (downMove > upMove && downMove > 0.0) ? downMove : 0.0;
      double tr = MathMax(high - low, MathMax(MathAbs(high - m_prevClose), MathAbs(low - m_prevClose)));

      m_prevHigh = high; m_prevLow = low; m_prevClose = close;

      PushTrDm(tr, plusDm, minusDm);
      if(m_trDmFillCount < REGIME_TR_DM_PERIOD)
         return false;   // meg nincs eleg adat a 14-baros simitashoz

      double trAvg = RollingMean(m_trBuf, m_trDmFillCount);
      double plusDi = 100.0 * RollingMean(m_plusDmBuf, m_trDmFillCount) / trAvg;
      double minusDi = 100.0 * RollingMean(m_minusDmBuf, m_trDmFillCount) / trAvg;
      double dx = 100.0 * MathAbs(plusDi - minusDi) / (plusDi + minusDi);

      m_lastAtr = trAvg;   // az ATR maga a TR egyszeru mozgoatlaga - lasd compute_simple_atr()

      PushDx(dx);
      if(m_dxFillCount < REGIME_TR_DM_PERIOD)
         return false;   // az ADX-hez (DX 14-baros atlaga) meg nincs eleg minta

      m_lastAdx = RollingMean(m_dxBuf, m_dxFillCount);

      PushWindow(m_lastAtr, m_lastAdx);
      if(m_windowFillCount < REGIME_ROLLING_WINDOW_BARS)
        {
         m_isReady = false;
         return false;   // meg nincs eleg adat a ~8640-baros gordulo ablakhoz
        }

      double volPct = PercentileRank(m_atrWindow, m_windowFillCount, m_lastAtr);
      double trendPct = PercentileRank(m_adxWindow, m_windowFillCount, m_lastAdx);

      if(trendPct <= REGIME_TREND_CUT_LOW)
         m_lastTrendBand = TREND_RANGING;
      else if(trendPct <= REGIME_TREND_CUT_HIGH)
         m_lastTrendBand = TREND_TRANSITIONAL;
      else
         m_lastTrendBand = TREND_TRENDING;

      m_lastVolBand = (volPct < 0.5) ? VOL_LOW : VOL_HIGH;
      m_isReady = true;
      return true;
     }

   bool       IsReady()    const { return m_isReady; }
   double     LastAtr()    const { return m_lastAtr; }
   double     LastAdx()    const { return m_lastAdx; }
   ETrendBand TrendBand()  const { return m_lastTrendBand; }
   EVolBand   VolBand()    const { return m_lastVolBand; }

   //--- diagnosztikai segedek (logolashoz)
   string TrendBandStr() const
     {
      switch(m_lastTrendBand)
        {
         case TREND_RANGING:      return "RANGING";
         case TREND_TRANSITIONAL: return "TRANSITIONAL";
         case TREND_TRENDING:     return "TRENDING";
         default:                 return "UNKNOWN";
        }
     }

   string VolBandStr() const
     {
      switch(m_lastVolBand)
        {
         case VOL_LOW:  return "LOW";
         case VOL_HIGH: return "HIGH";
         default:       return "UNKNOWN";
        }
     }
  };

#endif // REGIME_CLASSIFIER_MQH
//+------------------------------------------------------------------+
