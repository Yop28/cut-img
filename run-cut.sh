#!/usr/bin/env bash

# ============================================================
# run-cut.sh  –  그리드 이미지를 개별 샷으로 분리하는 스크립트
# ============================================================

# ─────────────────────── 설정값 ────────────────────────────
FOLDER_PATH="/run/media/u/B62F9460757288E2/Work/신약/7C#/images/pre-work/4/openart-download"   # 처리할 이미지 폴더 경로
GRID_M=2                              # 가로 열 수 (columns)
GRID_N=2                              # 세로 행 수 (rows)
ASPECT_RATIO="16:9"                   # 결과물 비율 강제 (빈 문자열이면 무시, 예: 16:9)
# ────────────────────────────────────────────────────────────

# ── 옵션 파싱 (기본값 s1, s2의 기본 fuzz는 10%)
MODE="s1"
TRIM_FUZZ="10%"
SHAVE_PX=0          # -shave N 옵션 기본값 (0=비활성)

while [[ $# -gt 0 ]]; do
  case $1 in
    -s1)
      MODE="s1"
      shift
      ;;
    -s2)
      MODE="s2"
      if [[ -n "$2" && "$2" != -* ]]; then
        TRIM_FUZZ="${2}%"
        shift
      fi
      shift
      ;;
    -s3)
      MODE="s3"
      shift
      ;;
    -shave)
      # -shave N : s1/s2 모드에서 경계선 제거 픽셀 수 (방안 C)
      if [[ -n "$2" && "$2" =~ ^[0-9]+$ ]]; then
        SHAVE_PX="$2"
        shift
      else
        SHAVE_PX=5   # 기본값
      fi
      shift
      ;;
    *)
      echo "[ERROR] 알 수 없는 옵션: $1" >&2
      exit 1
      ;;
  esac
done

# ── 가상환경 활성화 검사 (setup.sh를 통해 생성된 .venv)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
VENV_PATH="${SCRIPT_DIR}/.venv"

if [[ -f "${VENV_PATH}/bin/activate" ]]; then
    source "${VENV_PATH}/bin/activate"
else
    echo "[ERROR] 가상환경이 없습니다. 먼저 'bash setup.sh'를 실행해주세요." >&2
    exit 1
fi

# ── 내부 변수
OUTPUT_DIR="${FOLDER_PATH}/cut-imgs"
LOG_FILE="${FOLDER_PATH}/logs.txt"
COUNTER=1

# ── 의존 도구 확인 (ImageMagick, Python)
if ! command -v convert &>/dev/null || ! command -v identify &>/dev/null; then
    echo "[ERROR] ImageMagick(convert/identify)이 설치되어 있지 않습니다." >&2
    exit 1
fi

if [[ "$MODE" == "s3" ]] && ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python3가 설치되어 있지 않습니다. (-s3 동작 불가)" >&2
    exit 1
fi

# ── 출력 폴더 생성
mkdir -p "${OUTPUT_DIR}"

# ── 로그 함수
log_error() {
    local msg="$1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: ${msg}" | tee -a "${LOG_FILE}"
}

log_info() {
    local msg="$1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO:  ${msg}"
}

# ── 지원 이미지 확장자 목록 (대소문자 무관하게 처리)
IMAGE_EXTENSIONS=("jpg" "jpeg" "png" "webp" "bmp" "gif" "tiff" "tif" "avif")

is_image() {
    local file="$1"
    local ext="${file##*.}"
    ext="${ext,,}"
    for e in "${IMAGE_EXTENSIONS[@]}"; do
        [[ "$ext" == "$e" ]] && return 0
    done
    return 1
}

if [[ ! -d "${FOLDER_PATH}" ]]; then
    echo "[ERROR] 폴더를 찾을 수 없습니다: ${FOLDER_PATH}" >&2
    exit 1
fi

log_info "시작 - 모드: ${MODE}, 폴더: ${FOLDER_PATH}, 그리드: ${GRID_M}x${GRID_N}"
if [[ "$MODE" == "s2" ]]; then
    log_info "-s2 모드 Fuzz 값: ${TRIM_FUZZ}"
fi
if [[ "$SHAVE_PX" -gt 0 ]] && [[ "$MODE" != "s3" ]]; then
    log_info "-shave 값: ${SHAVE_PX}px (방안 C 경계선 제거 활성)"
fi
log_info "출력 폴더: ${OUTPUT_DIR}"

mapfile -t IMAGE_FILES < <(
    ls "${FOLDER_PATH}" 2>/dev/null \
    | while IFS= read -r fname; do
        fpath="${FOLDER_PATH}/${fname}"
        if [[ -f "$fpath" ]] && is_image "$fname"; then
            echo "$fpath"
        fi
    done
)

if [[ ${#IMAGE_FILES[@]} -eq 0 ]]; then
    log_info "처리할 이미지 파일이 없습니다."
    exit 0
fi

log_info "총 ${#IMAGE_FILES[@]}개의 이미지를 처리합니다."

# ── 이미지별 처리
for IMG_PATH in "${IMAGE_FILES[@]}"; do
    IMG_NAME="$(basename "${IMG_PATH}")"
    log_info "처리 중: ${IMG_NAME}"

    if [[ "$MODE" == "s3" ]]; then
        # Python 스크립트 호출 (출력 결과의 마지막 줄이 다음 카운터)
        NEW_COUNTER=$(python3 "${SCRIPT_DIR}/cut_opencv.py" "${IMG_PATH}" "${OUTPUT_DIR}" "${GRID_M}" "${GRID_N}" "${COUNTER}" "${ASPECT_RATIO}")
        if [[ $? -eq 0 ]]; then
            # NEW_COUNTER에서 마지막 줄 추출
            COUNTER=$(echo "$NEW_COUNTER" | tail -n 1)
        else
            log_error "${IMG_NAME} - s3(OpenCV) 분할 실패. 건너뜁니다."
        fi
        continue
    fi

    # s1, s2 처리 (ImageMagick)
    if ! DIMENSIONS=$(identify -format "%wx%h" "${IMG_PATH}[0]" 2>/dev/null); then
        log_error "${IMG_NAME} - 이미지 크기를 읽을 수 없습니다. 건너뜁니다."
        continue
    fi

    IMG_W="${DIMENSIONS%%x*}"
    IMG_H="${DIMENSIONS##*x}"

    CELL_W=$(( IMG_W / GRID_M ))
    CELL_H=$(( IMG_H / GRID_N ))

    if [[ $CELL_W -le 0 ]] || [[ $CELL_H -le 0 ]]; then
        log_error "${IMG_NAME} - 이미지 크기(${IMG_W}x${IMG_H})가 그리드(${GRID_M}x${GRID_N})보다 작습니다. 건너뜁니다."
        continue
    fi

    for (( row=0; row<GRID_N; row++ )); do
        for (( col=0; col<GRID_M; col++ )); do
            OFFSET_X=$(( col * CELL_W ))
            OFFSET_Y=$(( row * CELL_H ))
            OUT_FILE="${OUTPUT_DIR}/img-$(printf '%03d' "${COUNTER}").jpg"

            # 비율 강제(Center Crop) 로직 추가
            CROP_RATIO_CMD=()
            if [[ -n "$ASPECT_RATIO" ]]; then
                CROP_RATIO_CMD=(-gravity center -crop "${ASPECT_RATIO}" +repage)
            fi

            # 방안 C: -shave 경계선 제거 (aspect ratio 전 적용)
            SHAVE_CMD=()
            if [[ "$SHAVE_PX" -gt 0 ]]; then
                SHAVE_CMD=(-shave "${SHAVE_PX}x${SHAVE_PX}" +repage)
            fi

            # 분기 처리
            if [[ "$MODE" == "s2" ]]; then
                # s2: 자른 후 자동 여백 제거(-trim) → shave → 비율 크롭
                if ! convert "${IMG_PATH}[0]" \
                        -crop "${CELL_W}x${CELL_H}+${OFFSET_X}+${OFFSET_Y}" \
                        +repage \
                        -fuzz "${TRIM_FUZZ}" -trim +repage \
                        "${SHAVE_CMD[@]}" \
                        "${CROP_RATIO_CMD[@]}" \
                        "${OUT_FILE}" 2>/dev/null; then
                    log_error "${IMG_NAME} - 샷 분리/여백제거 실패 (row=${row}, col=${col}). 건너뜁니다."
                    continue
                fi
                # 최종 2752×1536 리사이즈 + 좌상단 크롭 (Lanczos 최고 화질)
                if ! convert "${OUT_FILE}" \
                        -filter Lanczos \
                        -resize "2752x1536^" \
                        -gravity NorthWest \
                        -extent 2752x1536 \
                        "${OUT_FILE}" 2>/dev/null; then
                    log_error "${IMG_NAME} - 리사이즈/크롭 실패 (row=${row}, col=${col}). 건너뜁니다."
                    continue
                fi
            else
                # s1: 기본 분할 → shave → 비율 크롭
                if ! convert "${IMG_PATH}[0]" \
                        -crop "${CELL_W}x${CELL_H}+${OFFSET_X}+${OFFSET_Y}" \
                        +repage \
                        "${SHAVE_CMD[@]}" \
                        "${CROP_RATIO_CMD[@]}" \
                        "${OUT_FILE}" 2>/dev/null; then
                    log_error "${IMG_NAME} - 샷 분리 실패 (row=${row}, col=${col}). 건너뜁니다."
                    continue
                fi
                # 최종 2752×1536 리사이즈 + 좌상단 크롭 (Lanczos 최고 화질)
                if ! convert "${OUT_FILE}" \
                        -filter Lanczos \
                        -resize "2752x1536^" \
                        -gravity NorthWest \
                        -extent 2752x1536 \
                        "${OUT_FILE}" 2>/dev/null; then
                    log_error "${IMG_NAME} - 리사이즈/크롭 실패 (row=${row}, col=${col}). 건너뜁니다."
                    continue
                fi
            fi

            log_info "  → 저장: $(basename "${OUT_FILE}")"
            (( COUNTER++ ))
        done
    done
done

log_info "완료 - 총 $(( COUNTER - 1 ))개의 샷 이미지가 생성되었습니다."
log_info "출력 위치: ${OUTPUT_DIR}"
