@echo off
title Wenhui Novel - Deploy Script
color 0A

setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0"
set "COMPOSE_FILE=%PROJECT_DIR%docker-compose.yml"
set "MAX_RETRIES=30"
set "RETRY_DELAY=5"

echo.
echo ============================================================
echo   Wenhui Novel - Deploy Script
echo ============================================================
echo.

if "%1"=="" (
    echo Usage:
    echo   deploy.bat start    - Start all services
    echo   deploy.bat stop     - Stop all services
    echo   deploy.bat restart  - Restart all services
    echo.
    pause
    exit /b 0
)

if /i "%1"=="start" goto :START
if /i "%1"=="stop" goto :STOP
if /i "%1"=="restart" goto :RESTART

echo ERROR: Unknown command '%1'
echo Usage: deploy.bat start ^| stop ^| restart
pause
exit /b 1

:: ============================================================
:: START - Start all services
:: ============================================================
:START
echo [ACTION] Starting Services...
echo.

echo [STEP 1/6] Checking Environment...
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Docker is not installed!
    echo   Please install Docker Desktop first.
    pause
    exit /b 1
)
echo   OK: Docker is installed

docker compose version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Docker Compose is not available!
    pause
    exit /b 1
)
echo   OK: Docker Compose is available

if not exist "%COMPOSE_FILE%" (
    echo   ERROR: docker-compose.yml not found!
    pause
    exit /b 1
)
echo   OK: docker-compose.yml found

echo.

echo [STEP 2/6] Cleaning Old Containers...
for %%c in (wenhui-frontend wenhui-backend wenhui-natapp wenhui-es wenhui-seaweedfs-master wenhui-seaweedfs-volume wenhui-seaweedfs-filer) do (
    docker stop %%c >nul 2>&1
    docker rm -f %%c >nul 2>&1
)
echo   OK: Old containers cleaned

echo.

echo [STEP 3/6] Building Docker Images...
cd /d "%PROJECT_DIR%"
docker compose build --pull frontend backend
if %errorlevel% neq 0 (
    echo   ERROR: Image build failed!
    pause
    exit /b 1
)
echo   OK: Images built successfully

echo.

echo [STEP 4/6] Starting Services...
cd /d "%PROJECT_DIR%"
docker compose up -d
if %errorlevel% neq 0 (
    echo   ERROR: Failed to start services!
    pause
    exit /b 1
)
echo   OK: Services started

echo.

echo [STEP 5/6] Waiting for Services...
echo   Waiting for backend to be ready...
set "RETRY_COUNT=0"
:WAIT_BACKEND
    curl -s -o nul -w "%%{http_code}" http://localhost:8000/api/health
    if !errorlevel! equ 0 (
        echo   OK: Backend is ready
        goto :WAIT_FRONTEND
    )
    set /a RETRY_COUNT+=1
    echo   Attempt !RETRY_COUNT!/%MAX_RETRIES%...
    timeout /t %RETRY_DELAY% /nobreak >nul
    if !RETRY_COUNT! geq %MAX_RETRIES% (
        echo   ERROR: Backend timeout!
        pause
        exit /b 1
    )
    goto :WAIT_BACKEND

:WAIT_FRONTEND
echo   Waiting for frontend...
timeout /t 3 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://localhost/
if !errorlevel! equ 0 (
    echo   OK: Frontend is ready
) else (
    echo   WARN: Frontend may still be starting...
)

echo.

echo [STEP 6/6] Service Status...
cd /d "%PROJECT_DIR%"
docker compose ps

echo.
echo ============================================================
echo   START COMPLETE!
echo ============================================================
echo.
echo   Local:           http://localhost
echo   Local API:       http://localhost:8000
echo   Public:          https://wenhui.nat100.top
echo.
echo   Press any key to exit...
pause >nul
exit /b 0

:: ============================================================
:: STOP - Stop all services
:: ============================================================
:STOP
echo [ACTION] Stopping Services...
echo.

cd /d "%PROJECT_DIR%"
docker compose down
if %errorlevel% neq 0 (
    echo   ERROR: Failed to stop services!
    pause
    exit /b 1
)
echo   OK: All services stopped

echo.
echo ============================================================
echo   STOP COMPLETE!
echo ============================================================
echo.
echo   All containers have been stopped and removed.
echo.
echo   Press any key to exit...
pause >nul
exit /b 0

:: ============================================================
:: RESTART - Restart all services
:: ============================================================
:RESTART
echo [ACTION] Restarting Services...
echo.

cd /d "%PROJECT_DIR%"
docker compose down
echo   OK: Services stopped

echo.

docker compose up -d
if %errorlevel% neq 0 (
    echo   ERROR: Failed to restart services!
    pause
    exit /b 1
)
echo   OK: Services restarted

echo.
echo ============================================================
echo   RESTART COMPLETE!
echo ============================================================
echo.
echo   Press any key to exit...
pause >nul
exit /b 0

endlocal
exit /b 0
