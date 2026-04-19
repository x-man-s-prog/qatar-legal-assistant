@echo off
chcp 65001 > nul
title المساعد القانوني الذكي

echo.
echo  ======================================
echo   المساعد القانوني الذكي — تشغيل محلي
echo  ======================================
echo.

REM التحقق من مفتاح Claude
findstr /C:"sk-ant-XXXXXX" "%~dp0.env" > nul 2>&1
if %errorlevel% == 0 (
    echo  [!] تحذير: لم تُعيّن مفتاح ANTHROPIC_API_KEY في ملف .env
    echo.
    echo      افتح الملف: %~dp0.env
    echo      وضع مفتاحك الحقيقي بدلاً من: sk-ant-XXXXXXXXXXXXXXXXXXXXXXXXXX
    echo.
    pause
    exit /b 1
)

echo  [1] تشغيل Docker Desktop...
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo      بدء تشغيل Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo      انتظار 30 ثانية...
    timeout /t 30 /nobreak > nul
)

echo  [2] تشغيل قاعدة البيانات PostgreSQL...
docker compose -f "C:\rag-system\docker-compose.yml" up -d postgres > nul 2>&1
timeout /t 5 /nobreak > nul
echo      PostgreSQL: جاهز

echo  [3] التحقق من Ollama...
ollama list > nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Ollama غير مشغّل. جارٍ تشغيله...
    start "" "C:\Users\%USERNAME%\AppData\Local\Programs\Ollama\ollama.exe"
    timeout /t 5 /nobreak > nul
)
echo      Ollama: جاهز

echo  [4] تشغيل المساعد القانوني...
echo.
echo  ─────────────────────────────────────
echo   الرابط: http://localhost:8000
echo   لإيقاف التشغيل: اضغط Ctrl+C
echo  ─────────────────────────────────────
echo.

REM فتح المتصفح
start /b cmd /c "timeout /t 3 > nul && start http://localhost:8000"

REM تشغيل الخادم
cd /d "%~dp0"
python -m uvicorn main:app --host 0.0.0.0 --port 8000

pause
