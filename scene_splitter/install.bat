@echo off
chcp 65001 > nul
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo  Scene Splitter — 의존성 설치
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

set PY=C:\Python313\python.exe
if not exist "%PY%" set PY=python

echo [1/4] PyTorch (CPU) 설치 중...
"%PY%" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
echo.

echo [2/4] TransNetV2 PyTorch 설치 중...
"%PY%" -m pip install transnetv2-pytorch numpy
echo.

echo [3/4] PySceneDetect 설치 중 (폴백용)...
"%PY%" -m pip install "scenedetect[opencv]"
echo.

echo [4/4] ffmpeg 확인...
where ffmpeg > nul 2>&1
if %errorlevel% neq 0 (
    echo   ⚠ ffmpeg가 PATH에 없습니다. 설치:
    echo   winget install Gyan.FFmpeg
) else (
    echo   ✓ ffmpeg OK
)
echo.

echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo  설치 완료. run.bat로 실행하세요.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
pause
