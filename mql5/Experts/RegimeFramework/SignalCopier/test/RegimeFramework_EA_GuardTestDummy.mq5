//+------------------------------------------------------------------+
//| RegimeFramework_EA_GuardTestDummy.mq5                             |
//| CSAK DEMO-TESZTHEZ -- SOHA ne keruljon eles terminalba!           |
//| Az RF_SignalSlave "eles EA vedelmenek" tesztelesere: egy eles EA-t|
//| utanoz (a neve "RegimeFramework"-kel kezdodik). Alapbol NEM csinal |
//| semmit. InpOpenTestPosition=true eseten indulaskor nyit EGY kis    |
//| poziciot a megadott magic-kel -- ezzel az "idegen pozicio" vedelem |
//| (azonos szimbolum/magic, de nem a slave nyitotta) tesztelheto.     |
//+------------------------------------------------------------------+
#property strict
#property version "1.00"

#include <Trade\Trade.mqh>

input bool   InpOpenTestPosition = false;   // true = indulaskor 1 teszt-pozicio nyitasa
input long   InpMagicNumber      = 101001;
input double InpLotSize          = 0.01;

int OnInit()
  {
   PrintFormat("GuardTestDummy elindult (%s) -- DEMO-TESZT EA, nem kereskedik%s.", _Symbol,
               InpOpenTestPosition ? " (kiveve: 1 teszt-pozicio)" : "");
   if(InpOpenTestPosition)
     {
      CTrade t;
      t.SetExpertMagicNumber(InpMagicNumber);
      //--- legalabb a bróker minimalis lotja (Pepperstone NAS100: 0,1 -- a 0,01-es alapertek "Invalid volume"-t adott)
      double lot = MathMax(InpLotSize, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
      if(t.Buy(lot, _Symbol, 0.0, 0.0, 0.0, "GUARD_TEST"))
         PrintFormat("GuardTestDummy: teszt-pozicio nyitva, magic=%I64d", InpMagicNumber);
      else
         PrintFormat("GuardTestDummy: teszt-pozicio nyitasa sikertelen: %d", t.ResultRetcode());
     }
   return INIT_SUCCEEDED;
  }

void OnTick() { }
//+------------------------------------------------------------------+
