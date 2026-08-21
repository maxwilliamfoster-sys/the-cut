@echo off
setlocal
REM ============================================================================
REM  THE CUT — deploy the dialogue Worker.
REM
REM  Just double-click this file, or run it from a terminal.
REM
REM  THE ACCOUNT MATTERS. The Worker and its KV namespace live under
REM  maxwilliamfoster@gmail.com. Logging in with any other Cloudflare account
REM  gets you a confusing failure deep in a log file:
REM
REM      KV namespace 'ed0402...' not found [code: 10041]
REM
REM  ...because the namespace is real, just not in the account you signed into.
REM  So this checks who you are BEFORE it tries anything.
REM ============================================================================

set EXPECTED=maxwilliamfoster@gmail.com

cd /d "%~dp0"

echo.
echo  THE CUT - deploying the dialogue Worker
echo  ---------------------------------------
echo.

echo  [1/4] Who are you logged in as?
call npx --yes wrangler whoami 2>nul | findstr /C:"%EXPECTED%" >nul
if errorlevel 1 (
  echo.
  echo  ---------------------------------------------------------------
  echo   You are NOT logged in as %EXPECTED%.
  echo.
  echo   The Worker and its KV storage live in that account. Deploying
  echo   from any other one fails with "KV namespace not found".
  echo.
  echo   Fixing it takes two steps:
  echo     1. this script will log you out now
  echo     2. a browser tab opens - sign in as %EXPECTED%
  echo  ---------------------------------------------------------------
  echo.
  pause
  call npx --yes wrangler logout
  echo.
  echo  Now signing in. Pick %EXPECTED% in the browser.
  call npx --yes wrangler login
  if errorlevel 1 (
    echo.
    echo  Login failed. Nothing has been deployed.
    pause
    exit /b 1
  )
  call npx --yes wrangler whoami 2>nul | findstr /C:"%EXPECTED%" >nul
  if errorlevel 1 (
    echo.
    echo  Still signed in as the wrong account. Nothing has been deployed.
    echo  Run this again and pick %EXPECTED%.
    pause
    exit /b 1
  )
)
echo        OK - %EXPECTED%

echo.
echo  [2/4] Deploying...
call npx --yes wrangler deploy
if errorlevel 1 (
  echo.
  echo  Deploy failed - the error is above. The live Worker is unchanged.
  pause
  exit /b 1
)

echo.
echo  [3/4] Is it answering?
curl -s -m 20 https://the-cut-talk.maxwilliamfoster.workers.dev/
echo.

echo.
echo  [4/4] Can it actually think?
curl -s -m 60 -X POST https://the-cut-talk.maxwilliamfoster.workers.dev/talk ^
  -H "Content-Type: application/json" ^
  -H "X-Player-Key: fuWBiw8wX0f3" ^
  -d "{\"agent\":\"tee\",\"line\":\"Cold one tonight.\"}"
echo.
echo.
echo  If you saw a reply above, it works - go and talk to someone.
echo  If you saw "brain unavailable", the deploy landed but every brain is
echo  out of tokens; it will come back on its own.
echo.
pause
