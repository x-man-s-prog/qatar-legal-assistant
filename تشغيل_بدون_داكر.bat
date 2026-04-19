@echo off
chcp 65001 > nul
title المساعد القانوني الذكي

echo.
echo  ==========================================
echo   المساعد القانوني الذكي - تشغيل مباشر
echo   (بدون Docker - بدون Ollama - Gemini فقط)
echo  ==========================================
echo.

cd /d "%~dp0"

echo  [1] التحقق من Python...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo  [خطأ] Python غير مثبت!
    echo  يرجى تحميله من: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo      Python: موجود ✓

echo  [2] تثبيت المتطلبات...
pip install "fastapi==0.115.0" "starlette==0.46.2" uvicorn httpx asyncpg pydantic jinja2 aiofiles --quiet 2>nul || pip install fastapi starlette uvicorn httpx asyncpg pydantic jinja2 aiofiles --quiet
echo      المتطلبات: جاهزة ✓

echo  [3] تشغيل المساعد القانوني...
echo.
echo  -----------------------------------------
echo   الرابط: http://localhost:8000
echo   لإيقاف التشغيل: اضغط Ctrl+C
echo  -----------------------------------------
echo.

start /b cmd /c "timeout /t 3 > nul && start http://localhost:8000"

python -m uvicorn main:app --host 127.0.0.1 --port 8000

pause
