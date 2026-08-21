import sys
import os
import math
import cv2
import numpy as np

# ══════════════════════════════════════════════════════════════════
# 방안 G — 전체 이미지 투영(Projection) 분석 기반 2단계 분할
#
# Step 1: 원본 이미지의 모든 행/열 std를 계산하여
#         경계선 구간(연속된 저-std 행/열 집합)을 탐지한다.
# Step 2: 탐지된 경계선의 "바깥 좌표"를 분할 기준으로 삼아
#         각 패널을 정밀하게 크롭한다.
# ══════════════════════════════════════════════════════════════════

PROJ_STD_THRESHOLD = 10   # std < 이 값이면 단색 경계선 행/열로 판단
PROJ_MIN_THICKNESS = 2    # 경계선으로 인정할 최소 연속 px 수 (노이즈 방지)
SMOOTH_WINDOW      = 5    # 이동평균 스무딩 윈도우 크기 (노이즈 행/열 무시)

TARGET_W = 2752           # 최종 출력 가로 픽셀
TARGET_H = 1536           # 최종 출력 세로 픽셀


# ─────────────────────────────────────────────────────────────────
# 리사이즈 + 좌상단 크롭 → TARGET_W × TARGET_H
# ─────────────────────────────────────────────────────────────────
def resize_and_crop(panel: np.ndarray,
                    target_w: int = TARGET_W,
                    target_h: int = TARGET_H) -> np.ndarray:
    """비율 유지 스케일 후 좌상단 기준 크롭하여 target_w × target_h 반환.

    - 업스케일/다운스케일 모두 지원 (max scale 기준으로 꽉 채움).
    - 다운스케일: cv2.INTER_LANCZOS4 (최고 화질)
    - 업스케일:   cv2.INTER_LANCZOS4
    """
    h, w = panel.shape[:2]
    scale = max(target_w / w, target_h / h)
    new_w = math.ceil(w * scale)
    new_h = math.ceil(h * scale)
    interp = cv2.INTER_LANCZOS4
    resized = cv2.resize(panel, (new_w, new_h), interpolation=interp)
    # 좌상단 기준 크롭 (오른쪽/아래 잘라냄)
    return resized[:target_h, :target_w]


# ─────────────────────────────────────────────────────────────────
# 보조 함수: 이동평균 스무딩
# ─────────────────────────────────────────────────────────────────
def _moving_avg(arr: np.ndarray, window: int) -> np.ndarray:
    """1D 배열에 이동평균을 적용한다. 경계는 패딩 없이 동일 길이 반환."""
    if window <= 1:
        return arr.copy()
    kernel = np.ones(window) / window
    return np.convolve(arr, kernel, mode='same')


# ─────────────────────────────────────────────────────────────────
# 핵심 함수: 투영 프로파일에서 경계선 구간 목록 반환
# ─────────────────────────────────────────────────────────────────
def find_border_segments(stds: np.ndarray,
                         threshold: float = PROJ_STD_THRESHOLD,
                         min_thickness: int = PROJ_MIN_THICKNESS,
                         smooth_window: int = SMOOTH_WINDOW) -> list:
    """1D std 배열에서 저-std 연속 구간(경계선 후보)을 반환한다.

    Returns:
        list of (start_idx, end_idx)  ← 둘 다 inclusive
        길이(end-start+1) >= min_thickness 인 구간만 포함.
    """
    smoothed = _moving_avg(stds, smooth_window)
    low_mask = smoothed < threshold   # True = 경계선 픽셀

    segments = []
    in_seg = False
    seg_start = 0
    for i, is_low in enumerate(low_mask):
        if is_low and not in_seg:
            in_seg = True
            seg_start = i
        elif not is_low and in_seg:
            in_seg = False
            seg_end = i - 1
            if seg_end - seg_start + 1 >= min_thickness:
                segments.append((seg_start, seg_end))
    if in_seg:
        seg_end = len(low_mask) - 1
        if seg_end - seg_start + 1 >= min_thickness:
            segments.append((seg_start, seg_end))

    return segments


# ─────────────────────────────────────────────────────────────────
# 핵심 함수: 투영 분석으로 grid_m x grid_n 패널 좌표 계산
# ─────────────────────────────────────────────────────────────────
def get_panels_by_projection(img: np.ndarray,
                             grid_m: int,
                             grid_n: int) -> list:
    """원본 이미지의 수평·수직 투영 std 분석으로 패널 크롭 좌표를 계산한다.

    경계선(저-std 구간)을 기준으로 각 패널의 실제 콘텐츠 영역만 잘라낸다.

    Returns:
        list of np.ndarray (패널 이미지), 좌상단→우상단→좌하단→우하단 순.
        탐지 실패 시 [] 반환.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

    # ── 수평(행) 방향 투영
    row_stds = np.array([np.std(gray[r, :]) for r in range(h)], dtype=float)
    # ── 수직(열) 방향 투영
    col_stds = np.array([np.std(gray[:, c]) for c in range(w)], dtype=float)

    row_segs = find_border_segments(row_stds)
    col_segs = find_border_segments(col_stds)

    print(f"  [방안G] 수평 경계선 구간: {row_segs}", file=sys.stderr)
    print(f"  [방안G] 수직 경계선 구간: {col_segs}", file=sys.stderr)

    # ── 수평 분할선: 이미지 상·하 가장자리와 내부 중앙선을 분류
    #   - 이미지 경계(가장자리)에 붙은 구간 → outer border
    #   - 이미지 중간에 있는 구간 → divider
    def classify_segments(segs, total, grid_count):
        """구간 목록을 outer_borders와 inner_dividers로 분류."""
        outer_start = [s for s in segs if s[0] == 0]          # 시작(0)에 붙은 구간
        outer_end   = [s for s in segs if s[1] == total - 1]  # 끝(total-1)에 붙은 구간
        inner       = [s for s in segs
                       if s not in outer_start and s not in outer_end]
        return outer_start, outer_end, inner

    row_os, row_oe, row_inner = classify_segments(row_segs, h, grid_n)
    col_os, col_oe, col_inner = classify_segments(col_segs, w, grid_m)

    # ── 패널 경계 좌표 계산
    #   각 축에 대해 [콘텐츠_시작, 콘텐츠_끝] 목록을 만든다.
    #   grid_n=2 이면 row 축에 콘텐츠 구간이 2개 있어야 함.

    def build_content_ranges(outer_s, outer_e, inner_divs, total, grid_count):
        """콘텐츠 구간 리스트 [(start, end), ...] 반환 (grid_count개)."""
        # 시작 오프셋: outer_start 구간의 끝+1
        content_start = (outer_s[0][1] + 1) if outer_s else 0
        # 끝 오프셋: outer_end 구간의 시작-1
        content_end   = (outer_e[0][0] - 1) if outer_e else total - 1

        if grid_count == 1:
            return [(content_start, content_end)]

        # 내부 분할선이 있으면 그것을 기준으로 나눔
        if len(inner_divs) >= grid_count - 1:
            # 가운데에 가장 가까운 (grid_count-1)개 선택
            mid = total / 2
            inner_divs_sorted = sorted(inner_divs,
                                       key=lambda s: abs((s[0]+s[1])/2 - mid))
            chosen = sorted(inner_divs_sorted[:grid_count - 1],
                            key=lambda s: s[0])
            ranges = []
            prev = content_start
            for div in chosen:
                ranges.append((prev, div[0] - 1))
                prev = div[1] + 1
            ranges.append((prev, content_end))
            return ranges
        else:
            # 분할선 미탐지 → 균등 분할 (경계선 제외 영역 기준)
            print("  [방안G] 내부 분할선 미탐지 → 균등 분할 적용", file=sys.stderr)
            content_len = content_end - content_start + 1
            step = content_len // grid_count
            return [(content_start + i * step,
                     content_start + (i + 1) * step - 1 if i < grid_count - 1
                     else content_end)
                    for i in range(grid_count)]

    row_ranges = build_content_ranges(row_os, row_oe, row_inner, h, grid_n)
    col_ranges = build_content_ranges(col_os, col_oe, col_inner, w, grid_m)

    print(f"  [방안G] 행 콘텐츠 구간: {row_ranges}", file=sys.stderr)
    print(f"  [방안G] 열 콘텐츠 구간: {col_ranges}", file=sys.stderr)

    if len(row_ranges) != grid_n or len(col_ranges) != grid_m:
        print("  [방안G] 구간 수 불일치 → Fallback", file=sys.stderr)
        return []

    # ── 패널 크롭 (좌상단→우상단→좌하단→우하단 순)
    panels = []
    for (ry1, ry2) in row_ranges:
        for (cx1, cx2) in col_ranges:
            crop = img[ry1:ry2 + 1, cx1:cx2 + 1]
            if crop.size > 0:
                panels.append(crop)

    return panels


# ─────────────────────────────────────────────────────────────────
# 보조 후처리: 패널 가장자리 잔여 경계선 제거 (strip_border)
# ─────────────────────────────────────────────────────────────────
def strip_border(panel: np.ndarray,
                 threshold: float = PROJ_STD_THRESHOLD,
                 min_thickness: int = PROJ_MIN_THICKNESS) -> np.ndarray:
    """패널 이미지의 상·하·좌·우 가장자리에서 단색 경계선 행/열을 제거한다.

    방안 G 이후 남은 잔여 경계선을 후처리로 제거하는 보조 함수.
    경계선이 없는 이미지는 변화 없이 반환한다.
    """
    if panel is None or panel.size == 0:
        return panel

    h, w = panel.shape[:2]
    gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY) if len(panel.shape) == 3 else panel

    row_stds = np.array([np.std(gray[r, :]) for r in range(h)], dtype=float)
    col_stds = np.array([np.std(gray[:, c]) for c in range(w)], dtype=float)

    row_segs = find_border_segments(row_stds, threshold, min_thickness)
    col_segs = find_border_segments(col_stds, threshold, min_thickness)

    # 가장자리(0 또는 끝)에 붙은 구간만 제거
    top    = (row_segs[0][1] + 1)   if row_segs and row_segs[0][0] == 0     else 0
    bottom = (row_segs[-1][0])      if row_segs and row_segs[-1][1] == h - 1 else h
    left   = (col_segs[0][1] + 1)   if col_segs and col_segs[0][0] == 0     else 0
    right  = (col_segs[-1][0])      if col_segs and col_segs[-1][1] == w - 1 else w

    if bottom <= top or right <= left:
        return panel

    stripped = panel[top:bottom, left:right]
    return stripped if stripped.size > 0 else panel


# ─────────────────────────────────────────────────────────────────
# 비율 크롭 (Center Crop)
# ─────────────────────────────────────────────────────────────────
def apply_aspect_ratio(panel: np.ndarray, aspect_ratio: str) -> np.ndarray:
    """지정된 비율로 중앙 크롭한다."""
    try:
        ar_w_str, ar_h_str = aspect_ratio.split(':')
        ar_w, ar_h = float(ar_w_str), float(ar_h_str)
        target_ratio = ar_w / ar_h

        ph, pw = panel.shape[:2]
        current_ratio = pw / ph

        if current_ratio > target_ratio:
            new_w = int(ph * target_ratio)
            new_h = ph
        else:
            new_w = pw
            new_h = int(pw / target_ratio)

        sx = (pw - new_w) // 2
        sy = (ph - new_h) // 2
        return panel[sy:sy + new_h, sx:sx + new_w]
    except Exception as e:
        print(f"WARNING: aspect ratio 적용 실패 {aspect_ratio}: {e}", file=sys.stderr)
        return panel


# ─────────────────────────────────────────────────────────────────
# 메인 처리 함수
# ─────────────────────────────────────────────────────────────────
def process_image(img_path, output_dir, grid_m, grid_n, start_counter, aspect_ratio=""):
    img = cv2.imread(img_path)
    if img is None:
        print(f"ERROR: Cannot read {img_path}", file=sys.stderr)
        sys.exit(1)

    h, w = img.shape[:2]

    panels = []

    # ── Step 1: 방안 G — 투영 분석 기반 정밀 분할
    panels = get_panels_by_projection(img, grid_m, grid_n)

    if panels:
        print("INFO: [방안G] 투영 분석으로 패널 분할 성공.", file=sys.stderr)
    else:
        # ── Fallback: 균등 분할
        print("INFO: [방안G] 실패 → 균등 분할 Fallback.", file=sys.stderr)
        cell_w = w // grid_m
        cell_h = h // grid_n
        for row in range(grid_n):
            for col in range(grid_m):
                x1 = col * cell_w
                y1 = row * cell_h
                panels.append(img[y1:y1 + cell_h, x1:x1 + cell_w])

    # ── Step 2: 저장 (잔여 경계선 후처리 → 비율 크롭 → 저장)
    counter = start_counter
    for p in panels:
        if p.size == 0:
            continue

        # 잔여 경계선 후처리 (방안 G 이후 남은 경계선 제거)
        p = strip_border(p)
        if p.size == 0:
            continue

        # 비율 크롭
        if aspect_ratio:
            p = apply_aspect_ratio(p, aspect_ratio)

        # 최종 2752×1536 리사이즈 + 좌상단 크롭 (Lanczos 최고 화질)
        p = resize_and_crop(p)

        out_file = os.path.join(output_dir, f"img-{counter:03d}.jpg")
        cv2.imwrite(out_file, p)
        print(f"  → 저장: img-{counter:03d}.jpg", file=sys.stderr)
        counter += 1

    # bash가 읽을 다음 카운터 출력
    print(counter)


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("Usage: python cut_opencv.py <img_path> <output_dir> <grid_m> <grid_n>"
              " <start_counter> [aspect_ratio]", file=sys.stderr)
        sys.exit(1)

    img_path      = sys.argv[1]
    output_dir    = sys.argv[2]
    grid_m        = int(sys.argv[3])
    grid_n        = int(sys.argv[4])
    start_counter = int(sys.argv[5])
    aspect_ratio  = sys.argv[6] if len(sys.argv) >= 7 else ""

    process_image(img_path, output_dir, grid_m, grid_n, start_counter, aspect_ratio)
