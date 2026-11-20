@echo off
REM ============================================================================
REM RegimeFramework terminal-watchdog inditoszkript
REM
REM KRITIKUS: ezt a scriptet KIZAROLAG dupla-kattintassal, a te SAJAT, INTERAKTIV
REM RDP-munkamenetedbol szabad elinditani (vagy tedd be az Inditopult mappaba --
REM Win+R, shell:startup --, hogy minden bejelentkezeskor automatikusan elinduljon).
REM SOHA ne indítsd SSH-n keresztul -- akkor a Windows Session 0 izolacioja miatt
REM lathatatlan munkamenetbe kerulne, es a gyermekei (a termindalok, amiket
REM ujraindit) is oda kerulnenek, ami PONTOSAN azt a hibat okozna, amit ez a
REM watchdog el akar kerulni. Lasd terminal_watchdog.py fejlec-kommentjet es
REM docs/SESSION_LOG.md 2026-09-13-i bejegyzeset a teljes indoklasert.
REM ============================================================================
setlocal

set EXE_DIR=C:\MT5-Demo\MONITOR
set EXE_NAME=RegimeFramework_TerminalWatchdog.exe

echo.
echo === RegimeFramework terminal-watchdog inditasa ===
echo.
echo Ez a program a hatterben fog futni (nincs lathato ablaka), es 10 masodpercenkent
echo ellenorzi a terminals.json-ban felsorolt MT5-terminalokat -- ha valamelyik nem
echo fut, ujrainditja. Log: %EXE_DIR%\terminal_watchdog.log
echo.

tasklist /FI "IMAGENAME eq %EXE_NAME%" | findstr /I "%EXE_NAME%" >nul
if %ERRORLEVEL%==0 (
    echo Mar fut egy peldany -- nem inditok masodikat.
) else (
    start "" "%EXE_DIR%\%EXE_NAME%"
    echo Elindult.
)

echo.
echo Ez az ablak bezarhato -- a watchdog folyamata tovabb fut a hatterben.
echo.
pause
