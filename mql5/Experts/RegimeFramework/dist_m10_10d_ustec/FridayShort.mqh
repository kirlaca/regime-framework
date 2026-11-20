//+------------------------------------------------------------------+
//| FridayShort.mqh                                                   |
//| A regime_framework Python FridayShortComponent-jenek MQL5 portja  |
//| (components/friday_short.py check_entry()-je).                    |
//|                                                                    |
//| FONTOS ELTERES a tobbi komponenshez kepest: ez egy "quota_exempt   |
//| time_gated" komponens (lasd core/engine.py modul-docstringje) -    |
//| a fo EA OnTick()-je csak akkor probalja meg CheckEntry()-t hivni,  |
//| ha a rendes napi kvota (MeanReversion/TrendFollowing/              |
//| LastHourContinuation) MAR elfogyott aznap, ES meg nem hasznaltuk   |
//| el a Penteki kivetel-slotot.                                       |
//|                                                                    |
//| A kilepes (SL-en kivul) NEM ebben az osztalyban dol el - a fo EA   |
//| kulon, prioritalt szabalyt kap ra (lasd RegimeFramework_EA.mq5     |
//| IsFsHoldEnd()), mert a hold_bars alapu kilepes ATNYULHAT a         |
//| kovetkezo naptari napra (a target_hour=23 miatt), ES a napvegi     |
//| kenyszerzaras (InpForceCloseHour) EPP ekkor lepne mukodesbe -      |
//| a Python Engine oldalan is EZERT lett a hold_bars a nap-hatarra    |
//| korlatozva (lasd components/friday_short.py fejlec-kommentjet).    |
//|                                                                    |
//| FIGYELEM: az MQL5 MqlDateTime.day_of_week konvencioja (0=Vasarnap, |
//| 1=Hetfo, ..., 6=Szombat) ELTER a Python pandas dayofweek-tol       |
//| (0=Hetfo, ..., 6=Vasarnap) - a hivo (fo EA) felelossege ATVALTANI  |
//| pandas-konvenciora, MIELOTT ezt az osztalyt hivja, hogy az         |
//| alapertek (targetDayOfWeek=4, Pentek) mindket oldalon UGYANAZT     |
//| jelentse.                                                          |
//+------------------------------------------------------------------+
#property strict

#ifndef FRIDAY_SHORT_MQH
#define FRIDAY_SHORT_MQH

#include "RegimeClassifier.mqh"
#include "MeanReversion.mqh"   // SSignal struct innen ujrahasznositva

//+------------------------------------------------------------------+
class CFridayShortComponent
  {
private:
   int      m_targetDayOfWeek;   // pandas-konvencio: 0=Hetfo ... 4=Pentek ... 6=Vasarnap
   int      m_targetHour;
   double   m_slAtrMultiplier;

public:
   CFridayShortComponent(int targetDayOfWeek = 4, int targetHour = 23, double slAtrMultiplier = 2.0)
     {
      m_targetDayOfWeek = targetDayOfWeek;
      m_targetHour = targetHour;
      m_slAtrMultiplier = slAtrMultiplier;
     }

   //--- szandekosan MINDIG true - lasd fajl fejlec-docstring, trend_band-fuggetlen.
   bool IsRegimeEligible(ETrendBand trendBand) const { return true; }

   //--- `dayOfWeek` MAR pandas-konvencioban erkezik (lasd fajl fejlec).
   //
   //    JAVITAS (2026-09-11, MT5-port bit-pontos validacioja talalta -- lasd optuna_research repo
   //    SESSION_LOG.md, "MT5-port bit-pontos, FUTTATOTT validacio"): a Python `check_entry()` a
   //    23:00-cimkeju SOR SAJAT zarasat hasznalja (a 23:00-23:10 gyertya zarasakor, valos ido
   //    23:10). Az EA-ban a hivo (OnTick()) `hour,minute`-je viszont az UJ bar oraja -- ami akkor
   //    23:00, amikor a 22:50-23:00 gyertya ZAR (valos ido 23:00), EGY BAR-RAL (10 perccel)
   //    KORABBAN. A regi `minute != 0` ellenorzes emiatt a VALIDALTNAL 10 perccel korabban, MAS
   //    gyertya zaroaraval lepett volna be elesben -- lasd a validacios szkript 2025-06-06-i
   //    konkret, szamszerusitett peldajat (~5 pontos ar-elteres). Javitva `minute != 10`-re, hogy
   //    a bar[1] (amin a dontes alapul) PONTOSAN a 23:00-23:10-es gyertya legyen, megegyezve a
   //    validalt Python-tervvel.
   SSignal CheckEntry(int dayOfWeek, int hour, int minute, double atr)
     {
      SSignal sig;
      sig.hasSignal = false;
      sig.tpDistance = 0.0;   // szandekosan nincs fix TP - a hold-veg/nap-hatar zaras korlatozza az idot

      if(dayOfWeek != m_targetDayOfWeek || hour != m_targetHour || minute != 10)
         return sig;
      if(atr == 0.0)
         return sig;

      sig.hasSignal = true;
      sig.isLong = false;   // mindig SHORT - lasd research/day_hour_confirmatory_check.py
      sig.slDistance = atr * m_slAtrMultiplier;
      return sig;
     }
  };

#endif // FRIDAY_SHORT_MQH
//+------------------------------------------------------------------+
