@echo off
title HUIT AI Chatbot Server
echo ========================================================
echo   HE THONG TROR LY AI TUYEN SINH HUIT - DH CONG THUONG
echo ========================================================
echo.
echo Dang khoi chay backend server tai http://localhost:8000 ...
echo Ban co the mo trinh duyet truy cap: http://localhost:8000
echo.
cd /d "%~dp0"
python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
pause
