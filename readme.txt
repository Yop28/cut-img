# 기능 개선 완료 및 사용 가이드

## 주요 변경 사항

### 1. `setup.sh` 추가 및 가상환경 구성
- `uv` 패키지 매니저를 통해 빠른 속도로 `.venv` 가상환경을 구축합니다.
- `-s3`에서 사용할 OpenCV(`opencv-python`)와 `numpy` 라이브러리를 가상환경 내에 격리하여 안전하게 설치합니다.
- 기존 사용하던 시스템 레벨의 `ImageMagick` 설치 여부도 확인합니다.

### 2. `run-cut.sh` 옵션 분기 처리
- 아무 옵션도 주지 않으면 기본 옵션(`-s1`)으로 동작합니다.
- 스크립트 실행 시 `.venv`를 자동으로 활성화하므로 별도의 가상환경 진입이 필요 없습니다.
- 상단 `ASPECT_RATIO` 변수로 결과물 비율을 고정할 수 있습니다. (빈 문자열이면 원본 비율 유지)

### 3. OpenCV 기반 패널 분리 (`-s3`)
- 윤곽선 탐지(Contour Detection)로 4개의 패널을 각각 추출합니다.
- 패널 경계가 불명확할 경우 50% 분할로 자동 Fallback됩니다.

### 4. 경계선 자동 제거 (방안 C + 방안 D)

#### 방안 D — `cut_opencv.py` (자동 감지, `-s3` 전용)
- `strip_border()` 함수 추가: 각 가장자리 행/열의 픽셀 표준편차(std)가 15 미만이면
  단색 경계선으로 판단하여 자동 제거합니다.
- Contour 성공 경로 및 Fallback 50% 경로 모두 적용됩니다.
- aspect ratio 크롭 전에 먼저 실행됩니다.

#### 방안 C — `run-cut.sh` (`-shave`, `-s1`/`-s2` 전용)
- `-shave N` 옵션으로 상·하·좌·우 각 N픽셀을 고정 제거합니다.
- aspect ratio 크롭 전에 적용됩니다.
- 옵션을 생략하면 shave를 적용하지 않습니다.

---

## 사용 방법

### 준비 (최초 1회)
```bash
bash setup.sh
```

### 옵션 설명

| 옵션 | 설명 |
|------|------|
| `-s1` | 기본 분할 (ImageMagick, 빠름) |
| `-s2 [fuzz]` | 자동 여백 제거(-trim) 포함 분할, fuzz 기본값 10 |
| `-s3` | OpenCV 윤곽선 탐지 분할 + 경계선 자동 제거 (방안 D) |
| `-shave N` | s1/s2 모드에서 가장자리 N픽셀 고정 제거 (방안 C) |

### 실행 예시

```bash
# s3 모드 — 경계선이 있는 그리드 이미지 (권장)
# 방안 D(strip_border)가 자동으로 상·하·좌·우 단색 경계선을 감지·제거
./run-cut.sh -s3

# s1 모드 — 기본 분할 (경계선 없는 이미지)
./run-cut.sh -s1

# s1 + shave 5px — 경계선이 얇을 때 (방안 C)
./run-cut.sh -s1 -shave 5

# s1 + shave 10px — 경계선이 두꺼울 때 (방안 C)
./run-cut.sh -s1 -shave 10

# s2 + fuzz 15 + shave 5 — 자동 여백 제거 + 고정 shave 조합
./run-cut.sh -s2 15 -shave 5
```

### 상단 설정값 (run-cut.sh 내부 직접 수정)

```bash
FOLDER_PATH="..."    # 처리할 이미지 폴더 경로
GRID_M=2             # 가로 열 수
GRID_N=2             # 세로 행 수
ASPECT_RATIO="16:9"  # 결과물 비율 강제 ("" 이면 원본 비율 유지)
```

---

## 경계선 제거 동작 원리

```
[s3 모드]
원본 그리드 → Contour 탐지 → 패널 bounding rect 크롭
             └─ Fallback 50% 분할
→ strip_border() : 가장자리 행/열 std < 15 이면 제거
→ aspect ratio 크롭 → 저장

[s1/s2 모드 + -shave N]
원본 그리드 → 50% 분할 크롭
→ -trim (s2만) → -shave NxN → aspect ratio 크롭 → 저장
```

추가적인 조정이 필요하시면 편하게 말씀해 주세요!
