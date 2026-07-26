#!/usr/bin/env bash

# ============================================================
# setup.sh – run-cut.sh 구동을 위한 가상환경 및 의존성 설치
# ============================================================

echo "[INFO] 시스템 의존성 확인 중..."

if ! command -v uv &>/dev/null; then
    echo "[ERROR] 'uv' 패키지 매니저가 설치되어 있지 않습니다."
    echo "[ERROR] 설치 가이드: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if ! command -v convert &>/dev/null || ! command -v identify &>/dev/null; then
    echo "[ERROR] ImageMagick(convert/identify)이 설치되어 있지 않습니다."
    echo "[ERROR] sudo apt-get install imagemagick 등으로 설치해 주세요."
    exit 1
fi

echo "[INFO] 가상환경(.venv) 구성 중..."
uv venv

echo "[INFO] Python 패키지 설치 중 (opencv-python, numpy)..."
uv pip install opencv-python numpy

echo "========================================================"
echo "[SUCCESS] 환경 설정이 완료되었습니다."
echo "[INFO] 별도의 활성화 없이 바로 './run-cut.sh'를 실행하시면 됩니다."
echo "========================================================"
