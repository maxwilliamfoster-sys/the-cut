@echo off
REM ============================================================================
REM  THE CUT — deploy the dialogue Worker.
REM
REM  Just double-click this file, or run it from a terminal.
REM
REM  It does two things:
REM    1. logs you into Cloudflare (opens a browser tab — click Allow)
REM    2. pushes worker/src/index.js live
REM
REM  You only ever need step 1 once; the login is remembered until it expires.
REM  Your existing Worker secrets (GROQ_API_KEY, PLAYER_KEY, DRAIN_KEY) survive
REM  a deploy, so there is nothing to re-enter.
REM ============================================================================

cd /d "%~dp0"

echo.
echo  THE CUT - deploying the dialogue Worker
echo  ---------------------------------------
echo.

echo  [1/3] Checking whether you are logged in to Cloudflare...
call npx --yes wrangler whoami >nul 2>&1
if errorlevel 1 (
  echo        Not logged in. A browser tab will open - click "Allow".
  echo.
  call npx --yes wrangler login
  if errorlevel 1 (
    echo.
    echo  Login failed. Nothing has been deployed. Try running this again.
    pause
    exit /b 1
  )
) else (
  echo        Already logged in.
)

echo.
echo  [2/3] Deploying...
call npx --yes wrangler deploy
if errorlevel 1 (
  echo.
  echo  Deploy failed - see the error above. The live Worker is unchanged.
  pause
  exit /b 1
)

echo.
echo  [3/3] Checking the Worker is answering...
curl -s -m 20 https://the-cut-talk.maxwilliamfoster.workers.dev/
echo.
echo.
echo  Done. Go to the city, walk up to somebody with WASD and press E.
echo.
pause
