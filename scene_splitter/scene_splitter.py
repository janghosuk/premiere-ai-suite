"""
Scene Splitter — 딥러닝 기반 자동 장면 편집 탐지
─────────────────────────────────────────────────────
Premiere Pro의 'Scene Edit Detection' (Adobe Sensei) 기능을 대체하는 오픈소스 도구.

탐지 엔진:
  1) TransNetV2 (기본, 권장)
     - soCzech/TransNetV2 - 딥러닝 기반 Shot Boundary Detection SOTA 모델
     - Adobe Sensei와 동급 수준의 정확도
     - https://github.com/soCzech/TransNetV2
  2) PySceneDetect (폴백)
     - 전통적 컨텐츠 비교 방식

각 컷의 첫 프레임은 JPEG 섬네일로 자동 저장됩니다.
"""

import os
import sys
import io
import time
import threading
import shutil
import subprocess
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# UTF-8 출력
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# ─── 선택적 의존성 ───
try:
    from scenedetect import detect, ContentDetector, AdaptiveDetector, ThresholdDetector
    PYSCENEDETECT_AVAILABLE = True
except ImportError:
    PYSCENEDETECT_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from transnetv2_pytorch import TransNetV2
    TRANSNET_AVAILABLE = True
except ImportError:
    TRANSNET_AVAILABLE = False


# ─── Claude 스타일 컬러 ───
BG = "#1a1815"
SURFACE = "#262624"
SURFACE_2 = "#34322e"
BORDER = "#3d3b36"
TEXT = "#f5f4ed"
TEXT_DIM = "#c2bfb6"
TEXT_MUTE = "#8a8780"
ACCENT = "#d97757"
ACCENT_HOVER = "#e88a6a"
SUCCESS = "#7fb87f"
ERROR = "#e07a7a"

# TransNetV2 가중치 (Hugging Face, ~30MB, 1회만 다운로드)
TRANSNET_WEIGHTS_URL = (
    "https://huggingface.co/Sn4kehead/TransNetV2/resolve/main/"
    "transnetv2-pytorch-weights.pth"
)


def get_desktop_path() -> Path:
    home = Path.home()
    for p in [home / "Desktop", home / "바탕 화면",
              home / "OneDrive" / "Desktop", home / "OneDrive" / "바탕 화면"]:
        if p.exists():
            return p
    return home


def get_cache_dir() -> Path:
    cache = Path.home() / ".cache" / "scene_splitter"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def run_ffmpeg(args: list, timeout: int = 180) -> tuple:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
            capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def extract_jpeg_frame(video_path: str, time_sec: float, output_path: str) -> bool:
    """고품질 JPEG 섬네일 추출"""
    args = [
        "-ss", f"{time_sec:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_path,
    ]
    ok, _ = run_ffmpeg(args, timeout=30)
    return ok


def split_video_segment(video_path: str, start_sec: float, end_sec: float,
                        output_path: str) -> bool:
    """ffmpeg 스트림 카피 (무손실, 빠름)"""
    args = [
        "-ss", f"{start_sec:.3f}",
        "-to", f"{end_sec:.3f}",
        "-i", video_path,
        "-c", "copy",
        "-map", "0",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ]
    ok, _ = run_ffmpeg(args, timeout=180)
    return ok


def get_video_fps(video_path: str) -> float:
    """ffprobe로 영상 FPS 조회"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        rate = result.stdout.strip()
        if "/" in rate:
            num, den = rate.split("/")
            return float(num) / float(den) if float(den) != 0 else 25.0
        return float(rate)
    except Exception:
        return 25.0


# ─── TransNetV2 (딥러닝 SOTA) ───
def download_transnet_weights(dest: Path, log_fn) -> None:
    """HuggingFace에서 TransNetV2 가중치 다운로드 (최초 1회)"""
    log_fn(f"TransNetV2 가중치 다운로드 중 (~30MB)...", "info")
    log_fn(f"  {TRANSNET_WEIGHTS_URL}", "info")

    tmp = dest.with_suffix(".tmp")
    try:
        def reporthook(blocks, block_size, total_size):
            if total_size > 0:
                pct = min(100, blocks * block_size * 100 // total_size)
                if pct % 10 == 0 and blocks * block_size <= total_size:
                    log_fn(f"  진행: {pct}%", "info")

        urllib.request.urlretrieve(TRANSNET_WEIGHTS_URL, str(tmp), reporthook)
        tmp.rename(dest)
        log_fn(f"✓ 가중치 저장: {dest}", "success")
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"가중치 다운로드 실패: {e}")


def extract_frames_transnet(video_path: str, log_fn) -> "np.ndarray":
    """
    ffmpeg로 영상 프레임을 TransNetV2 입력 형식으로 추출.
    TransNetV2는 48x27 RGB24 고정 해상도 입력을 요구.
    """
    log_fn("ffmpeg로 프레임 추출 중 (48x27 RGB24)...", "info")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "48x27",
        "pipe:",
    ]
    proc = subprocess.run(
        cmd, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 프레임 추출 실패: {proc.stderr.decode(errors='replace')[:300]}")

    frame_bytes = proc.stdout
    expected_frame_size = 48 * 27 * 3
    total_frames = len(frame_bytes) // expected_frame_size
    if total_frames == 0:
        raise RuntimeError("프레임이 0개 추출됨")

    frames = np.frombuffer(frame_bytes, np.uint8).reshape(-1, 27, 48, 3)
    log_fn(f"  ✓ {len(frames)} 프레임 추출", "success")
    return frames


def transnet_predict(model, frames: "np.ndarray", log_fn) -> "np.ndarray":
    """
    TransNetV2 슬라이딩 윈도우 추론.
    모델은 100프레임 윈도우 중 가운데 50프레임의 예측만 사용.
    각 프레임당 [0, 1] scene boundary 확률 점수 반환.
    """
    log_fn("TransNetV2 추론 중...", "info")

    # 25 프레임 시작 패딩 + 프레임들 + 25 프레임 끝 패딩 (100 배수 맞춤)
    no_pad_start = 25
    remainder = len(frames) % 50
    no_pad_end = 25 + (50 - remainder if remainder != 0 else 0)

    start_frame = np.expand_dims(frames[0], 0)
    end_frame = np.expand_dims(frames[-1], 0)
    padded = np.concatenate(
        [start_frame] * no_pad_start + [frames] + [end_frame] * no_pad_end, axis=0
    )

    predictions = []
    ptr = 0
    device = next(model.parameters()).device

    total_windows = (len(padded) - 100) // 50 + 1
    window_idx = 0

    while ptr + 100 <= len(padded):
        window = padded[ptr:ptr + 100]  # [100, 27, 48, 3]
        inp = torch.from_numpy(window[np.newaxis]).to(device)  # [1, 100, 27, 48, 3]

        with torch.no_grad():
            output = model(inp)
            # use_many_hot_targets=True → (one_hot, {"many_hot": ...})
            if isinstance(output, tuple):
                single = output[0]
            else:
                single = output
            # [1, 100, 1] → [100]
            single = torch.sigmoid(single[0, :, 0]).cpu().numpy()

        # 가운데 50프레임 (인덱스 25:75) 만 사용 — 양쪽 패딩 영역 제외
        predictions.append(single[25:75])
        ptr += 50
        window_idx += 1
        if window_idx % 10 == 0:
            log_fn(f"  윈도우 {window_idx}/{total_windows}", "info")

    all_preds = np.concatenate(predictions)
    # 원본 프레임 수만큼만 잘라내기
    return all_preds[:len(frames)]


def predictions_to_scenes(preds: "np.ndarray",
                          threshold: float = 0.5,
                          min_scene_frames: int = 15) -> list:
    """
    TransNetV2 예측값 → 장면 경계 (프레임 인덱스 기준).

    핵심 로직:
    1) Peak detection — threshold 위 연속 구간에서 '가장 높은' 프레임 1개만 cut으로 채택
       (dissolve/fade처럼 여러 프레임이 같이 켜지는 경우 False Positive 방지)
    2) Minimum distance 강제 — cut 사이 간격이 min_scene_frames 미만이면
       확률이 낮은 쪽을 제거해 너무 짧은 장면이 나오는 것 방지

    Args:
        preds: [T] 프레임별 sigmoid 확률 (0~1)
        threshold: peak 높이 임계값
        min_scene_frames: 두 cut 사이 최소 프레임 수

    Returns:
        [(start_frame, end_frame), ...] (반열림 구간의 정수 인덱스)
    """
    n = len(preds)
    if n == 0:
        return []

    # ── 1단계: threshold 위 연속 구간에서 peak만 추출 ──
    cut_points = []  # cut 프레임 인덱스
    i = 0
    while i < n:
        if preds[i] >= threshold:
            # 이 연속 구간의 peak 찾기
            peak_idx = i
            peak_val = float(preds[i])
            j = i + 1
            while j < n and preds[j] >= threshold:
                if float(preds[j]) > peak_val:
                    peak_idx = j
                    peak_val = float(preds[j])
                j += 1
            cut_points.append(peak_idx)
            i = j  # 이 구간 건너뛰기
        else:
            i += 1

    # ── 2단계: 최소 거리 강제 ──
    if min_scene_frames > 0 and len(cut_points) > 1:
        filtered = [cut_points[0]]
        for c in cut_points[1:]:
            if c - filtered[-1] >= min_scene_frames:
                filtered.append(c)
            else:
                # 너무 가까움 — 확률 더 높은 쪽만 유지
                if float(preds[c]) > float(preds[filtered[-1]]):
                    filtered[-1] = c
        cut_points = filtered

    # ── 3단계: cut 지점 → 장면 구간 변환 ──
    if not cut_points:
        return [(0, n - 1)]

    scenes = []
    prev = 0
    for c in cut_points:
        if c > prev:
            scenes.append((int(prev), int(c - 1)))
        prev = c
    # 마지막 구간
    if prev < n:
        scenes.append((int(prev), int(n - 1)))

    # 첫 장면 길이 체크 (min_scene_frames 미만이면 다음 장면에 병합)
    if len(scenes) >= 2:
        first_start, first_end = scenes[0]
        if (first_end - first_start + 1) < min_scene_frames:
            _, second_end = scenes[1]
            scenes[0] = (first_start, second_end)
            scenes.pop(1)

    return scenes


def detect_scenes_transnet(video_path: str, threshold: float,
                            min_scene_sec: float, log_fn) -> list:
    """TransNetV2로 장면 탐지. [(start_sec, end_sec), ...] 반환"""
    if not NUMPY_AVAILABLE:
        raise RuntimeError("numpy 필요: pip install numpy")
    if not TORCH_AVAILABLE:
        raise RuntimeError(
            "PyTorch가 설치되지 않았습니다.\n"
            "설치: pip install torch --index-url https://download.pytorch.org/whl/cpu"
        )
    if not TRANSNET_AVAILABLE:
        raise RuntimeError(
            "transnetv2-pytorch가 설치되지 않았습니다.\n"
            "설치: pip install transnetv2-pytorch"
        )

    # 1. 가중치 준비
    weights_path = get_cache_dir() / "transnetv2-pytorch-weights.pth"
    if not weights_path.exists():
        download_transnet_weights(weights_path, log_fn)
    else:
        log_fn(f"✓ 캐시된 가중치 사용: {weights_path.name}", "success")

    # 2. 모델 로드
    log_fn("TransNetV2 모델 로드 중...", "info")
    model = TransNetV2()
    try:
        state_dict = torch.load(str(weights_path), map_location="cpu", weights_only=True)
    except TypeError:
        state_dict = torch.load(str(weights_path), map_location="cpu")
    model.load_state_dict(state_dict)
    model.eval()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    log_fn(f"  ✓ 디바이스: {device.upper()}", "success")

    # 3. 프레임 추출
    frames = extract_frames_transnet(video_path, log_fn)

    # 4. 추론
    t0 = time.time()
    preds = transnet_predict(model, frames, log_fn)
    log_fn(f"  ✓ 추론 완료 ({time.time()-t0:.1f}초)", "success")

    # 5. FPS 계산
    fps = get_video_fps(video_path)
    log_fn(f"  ✓ FPS: {fps:.2f}", "info")

    # 6. Peak detection + 최소 거리 필터
    min_frames = max(1, int(round(min_scene_sec * fps)))
    log_fn(f"  설정: threshold={threshold:.2f}, 최소 장면={min_scene_sec:.2f}s "
           f"({min_frames} 프레임)", "info")

    # 진단: raw prediction 분포
    raw_peaks = int((preds > threshold).sum())
    log_fn(f"  raw peak 프레임 수: {raw_peaks} "
           f"(max={float(preds.max()):.3f}, mean={float(preds.mean()):.3f})", "info")

    scene_frames = predictions_to_scenes(preds, threshold=threshold,
                                          min_scene_frames=min_frames)
    cuts = [(s / fps, (e + 1) / fps) for s, e in scene_frames]

    log_fn(f"✓ TransNetV2가 {len(cuts)}개 컷 감지 "
           f"(False Positive 필터링 후)", "success")
    return cuts


# ─── PySceneDetect (폴백) ───
def detect_scenes_pyscenedetect(video_path: str, detector_type: str,
                                  threshold: float, log_fn) -> list:
    if not PYSCENEDETECT_AVAILABLE:
        raise RuntimeError("PySceneDetect 미설치: pip install scenedetect[opencv]")

    log_fn(f"PySceneDetect 분석 중 ({detector_type}, threshold={threshold:.1f})...", "info")

    if detector_type == "content":
        detector = ContentDetector(threshold=threshold, min_scene_len=15)
    elif detector_type == "adaptive":
        detector = AdaptiveDetector(adaptive_threshold=max(1.0, threshold / 9))
    else:
        detector = ThresholdDetector(threshold=threshold, min_scene_len=15)

    scene_list = detect(video_path, detector, show_progress=False)
    cuts = [(s.get_seconds(), e.get_seconds()) for (s, e) in scene_list]
    log_fn(f"✓ PySceneDetect가 {len(cuts)}개 컷 감지", "success")
    return cuts


# ─── GUI ───
class SceneSplitterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Scene Splitter — AI 장면 편집 탐지")
        self.root.geometry("740x820")
        self.root.minsize(640, 680)
        self.root.configure(bg=BG)

        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(get_desktop_path()))
        self.mode = tk.StringVar(value="transnet")  # transnet | pyscenedetect
        self.transnet_threshold = tk.DoubleVar(value=0.5)
        self.transnet_threshold_text = tk.StringVar(value="0.50")
        self.min_scene_sec = tk.DoubleVar(value=0.6)
        self.min_scene_sec_text = tk.StringVar(value="0.6s")
        self.threshold = tk.DoubleVar(value=27.0)
        self.threshold_text = tk.StringVar(value="27.0")
        self.detector_type = tk.StringVar(value="content")
        self.save_thumbnails = tk.BooleanVar(value=True)
        self.is_running = False

        self._setup_styles()
        self._build_ui()
        self._check_environment()

    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")

        s.configure("App.TFrame", background=BG)
        s.configure("Title.TLabel", background=BG, foreground=TEXT,
                    font=("Segoe UI", 16, "bold"))
        s.configure("Sub.TLabel", background=BG, foreground=TEXT_MUTE,
                    font=("Segoe UI", 9))
        s.configure("Field.TLabel", background=BG, foreground=TEXT_DIM,
                    font=("Segoe UI", 10, "bold"))
        s.configure("Hint.TLabel", background=BG, foreground=TEXT_MUTE,
                    font=("Segoe UI", 9))
        s.configure("Value.TLabel", background=BG, foreground=ACCENT,
                    font=("Segoe UI", 10, "bold"))
        s.configure("Badge.TLabel", background=SURFACE_2, foreground=ACCENT,
                    font=("Segoe UI", 8, "bold"), padding=(6, 2))

        s.configure("TEntry",
                    fieldbackground=SURFACE, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    insertcolor=TEXT, borderwidth=1)
        s.map("TEntry",
              fieldbackground=[("focus", SURFACE_2)],
              bordercolor=[("focus", ACCENT)])

        s.configure("TButton",
                    background=SURFACE_2, foreground=TEXT,
                    borderwidth=0, font=("Segoe UI", 9), padding=(12, 6))
        s.map("TButton", background=[("active", BORDER)])

        s.configure("Accent.TButton",
                    background=ACCENT, foreground="#1a1815",
                    borderwidth=0, font=("Segoe UI", 11, "bold"),
                    padding=(16, 10))
        s.map("Accent.TButton",
              background=[("active", ACCENT_HOVER), ("disabled", SURFACE_2)],
              foreground=[("disabled", TEXT_MUTE)])

        s.configure("TRadiobutton", background=BG, foreground=TEXT_DIM,
                    font=("Segoe UI", 9))
        s.map("TRadiobutton",
              background=[("active", BG)],
              foreground=[("active", TEXT)])

        s.configure("TCheckbutton", background=BG, foreground=TEXT_DIM,
                    font=("Segoe UI", 9))
        s.map("TCheckbutton",
              background=[("active", BG)],
              foreground=[("active", TEXT)])

        s.configure("Horizontal.TScale",
                    background=BG, troughcolor=SURFACE_2,
                    bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT)

        s.configure("Horizontal.TProgressbar",
                    background=ACCENT, troughcolor=SURFACE,
                    borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=24, style="App.TFrame")
        main.pack(fill="both", expand=True)

        # 헤더
        header = ttk.Frame(main, style="App.TFrame")
        header.pack(fill="x", pady=(0, 16))

        title_row = ttk.Frame(header, style="App.TFrame")
        title_row.pack(fill="x")
        dot = tk.Canvas(title_row, width=14, height=14, bg=BG, highlightthickness=0)
        dot.create_oval(2, 2, 12, 12, fill=ACCENT, outline="")
        dot.pack(side="left", padx=(0, 8))
        ttk.Label(title_row, text="Scene Splitter", style="Title.TLabel").pack(side="left")
        ttk.Label(title_row, text="AI 기반", style="Badge.TLabel").pack(side="left", padx=(8, 0))

        ttk.Label(header,
                  text="딥러닝 기반 장면 편집 탐지 · Premiere Pro Scene Edit Detection 대체",
                  style="Sub.TLabel").pack(anchor="w", pady=(6, 0))

        # 입력 영상
        ttk.Label(main, text="입력 영상 파일", style="Field.TLabel").pack(anchor="w", pady=(0, 6))
        in_frame = ttk.Frame(main, style="App.TFrame")
        in_frame.pack(fill="x", pady=(0, 12))
        ttk.Entry(in_frame, textvariable=self.input_path).pack(
            side="left", fill="x", expand=True, padx=(0, 8), ipady=4)
        ttk.Button(in_frame, text="찾아보기", command=self._browse_input).pack(side="right")

        # 출력 폴더
        ttk.Label(main, text="출력 폴더", style="Field.TLabel").pack(anchor="w", pady=(0, 6))
        out_frame = ttk.Frame(main, style="App.TFrame")
        out_frame.pack(fill="x", pady=(0, 12))
        ttk.Entry(out_frame, textvariable=self.output_dir).pack(
            side="left", fill="x", expand=True, padx=(0, 8), ipady=4)
        ttk.Button(out_frame, text="찾아보기", command=self._browse_output).pack(side="right")

        # 탐지 엔진
        ttk.Label(main, text="탐지 엔진", style="Field.TLabel").pack(anchor="w", pady=(0, 6))
        mode_frame = ttk.Frame(main, style="App.TFrame")
        mode_frame.pack(fill="x", pady=(0, 12))
        ttk.Radiobutton(mode_frame,
                        text="TransNetV2 (딥러닝 SOTA · Premiere Pro 급 정확도, 권장)",
                        variable=self.mode, value="transnet",
                        command=self._on_mode_change).pack(anchor="w", pady=2)
        ttk.Radiobutton(mode_frame,
                        text="PySceneDetect (전통 방식, 빠름, 경량)",
                        variable=self.mode, value="pyscenedetect",
                        command=self._on_mode_change).pack(anchor="w", pady=2)

        # 옵션 컨테이너
        self.options_frame = ttk.Frame(main, style="App.TFrame")
        self.options_frame.pack(fill="x", pady=(0, 12))

        # TransNetV2 옵션
        self.transnet_opts = ttk.Frame(self.options_frame, style="App.TFrame")

        # 1) Threshold
        trow = ttk.Frame(self.transnet_opts, style="App.TFrame")
        trow.pack(fill="x", pady=(0, 2))
        ttk.Label(trow, text="Threshold (cut 감지 강도)",
                  style="Field.TLabel").pack(side="left")
        ttk.Label(trow, textvariable=self.transnet_threshold_text,
                  style="Value.TLabel").pack(side="right")
        ttk.Scale(self.transnet_opts, from_=0.1, to=0.9,
                  variable=self.transnet_threshold, orient="horizontal",
                  command=lambda v: self.transnet_threshold_text.set(f"{float(v):.2f}")).pack(
                      fill="x", pady=(2, 2))
        ttk.Label(self.transnet_opts,
                  text="높을수록 엄격 (False Positive 감소). 권장 0.5~0.7",
                  style="Hint.TLabel").pack(anchor="w")

        # 2) 최소 장면 길이 — False Positive 억제용
        mrow = ttk.Frame(self.transnet_opts, style="App.TFrame")
        mrow.pack(fill="x", pady=(10, 2))
        ttk.Label(mrow, text="최소 장면 길이", style="Field.TLabel").pack(side="left")
        ttk.Label(mrow, textvariable=self.min_scene_sec_text,
                  style="Value.TLabel").pack(side="right")
        ttk.Scale(self.transnet_opts, from_=0.1, to=3.0,
                  variable=self.min_scene_sec, orient="horizontal",
                  command=lambda v: self.min_scene_sec_text.set(f"{float(v):.1f}s")).pack(
                      fill="x", pady=(2, 2))
        ttk.Label(self.transnet_opts,
                  text="이 값보다 짧은 장면은 자동 병합. 과분할(컷 아닌데 잘림) 방지.",
                  style="Hint.TLabel").pack(anchor="w")

        # PySceneDetect 옵션
        self.pyscene_opts = ttk.Frame(self.options_frame, style="App.TFrame")
        det_row = ttk.Frame(self.pyscene_opts, style="App.TFrame")
        det_row.pack(fill="x", pady=(0, 6))
        for label, value in [
            ("Content (일반)", "content"),
            ("Adaptive (조명)", "adaptive"),
            ("Threshold (페이드)", "threshold"),
        ]:
            ttk.Radiobutton(det_row, text=label, variable=self.detector_type,
                            value=value).pack(side="left", padx=(0, 12))
        thresh_row = ttk.Frame(self.pyscene_opts, style="App.TFrame")
        thresh_row.pack(fill="x", pady=(0, 4))
        ttk.Label(thresh_row, text="임계값", style="Field.TLabel").pack(side="left")
        ttk.Label(thresh_row, textvariable=self.threshold_text,
                  style="Value.TLabel").pack(side="right")
        ttk.Scale(self.pyscene_opts, from_=5, to=60, variable=self.threshold,
                  orient="horizontal",
                  command=lambda v: self.threshold_text.set(f"{float(v):.1f}")).pack(
                      fill="x", pady=(4, 4))
        ttk.Label(self.pyscene_opts,
                  text="낮을수록 더 많이 자름 (기본 27)",
                  style="Hint.TLabel").pack(anchor="w")

        self._on_mode_change()

        # 섬네일 옵션
        ttk.Checkbutton(main, text="각 컷의 첫 프레임을 JPEG 섬네일로 저장",
                        variable=self.save_thumbnails).pack(anchor="w", pady=(0, 16))

        # 실행 버튼
        self.run_btn = ttk.Button(main, text="▶  분할 시작",
                                   command=self._start_split, style="Accent.TButton")
        self.run_btn.pack(fill="x", pady=(0, 12))

        # 진행바
        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 10))

        # 로그
        log_wrap = tk.Frame(main, bg=BORDER, bd=0)
        log_wrap.pack(fill="both", expand=True)
        self.log = tk.Text(log_wrap, bg=SURFACE, fg=TEXT_DIM,
                           font=("Consolas", 9), bd=0, relief="flat",
                           padx=12, pady=10, wrap="word",
                           insertbackground=TEXT,
                           selectbackground=ACCENT, selectforeground="#1a1815")
        scroll = tk.Scrollbar(log_wrap, command=self.log.yview, bg=SURFACE)
        self.log.config(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True, padx=1, pady=1)

        self.log.tag_config("info", foreground=TEXT_DIM)
        self.log.tag_config("success", foreground=SUCCESS)
        self.log.tag_config("error", foreground=ERROR)
        self.log.tag_config("accent", foreground=ACCENT, font=("Consolas", 9, "bold"))

    def _on_mode_change(self):
        for child in self.options_frame.winfo_children():
            child.pack_forget()
        if self.mode.get() == "transnet":
            self.transnet_opts.pack(fill="x")
        else:
            self.pyscene_opts.pack(fill="x")

    def _check_environment(self):
        ok = True
        if not check_ffmpeg():
            self._log("⚠ ffmpeg가 PATH에 없습니다 (필수).", "error")
            self._log("  Windows: winget install Gyan.FFmpeg", "info")
            ok = False

        self._log("의존성 체크:", "accent")
        self._log(f"  numpy:              {'✓' if NUMPY_AVAILABLE else '✗ (pip install numpy)'}",
                  "success" if NUMPY_AVAILABLE else "error")
        self._log(f"  torch:              {'✓' if TORCH_AVAILABLE else '✗ (pip install torch)'}",
                  "success" if TORCH_AVAILABLE else "error")
        self._log(f"  transnetv2-pytorch: {'✓' if TRANSNET_AVAILABLE else '✗ (pip install transnetv2-pytorch)'}",
                  "success" if TRANSNET_AVAILABLE else "error")
        self._log(f"  scenedetect:        {'✓' if PYSCENEDETECT_AVAILABLE else '✗ (pip install scenedetect[opencv])'}",
                  "success" if PYSCENEDETECT_AVAILABLE else "info")

        if TORCH_AVAILABLE:
            try:
                gpu = "CUDA 사용 가능" if torch.cuda.is_available() else "CPU 모드"
                self._log(f"  디바이스: {gpu}", "info")
            except Exception:
                pass

        if ok:
            self._log("\nScene Splitter 준비 완료", "success")
            self._log(f"기본 출력 폴더: {self.output_dir.get()}", "info")
            self._log("영상을 선택하고 '분할 시작'을 누르세요.\n", "info")
        else:
            self.run_btn.config(state="disabled")

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="분할할 영상 선택",
            filetypes=[
                ("영상 파일", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv *.flv"),
                ("모든 파일", "*.*"),
            ],
        )
        if path:
            self.input_path.set(path)

    def _browse_output(self):
        path = filedialog.askdirectory(
            title="출력 폴더 선택",
            initialdir=self.output_dir.get(),
        )
        if path:
            self.output_dir.set(path)

    def _log(self, message, tag="info"):
        self.log.insert("end", message + "\n", tag)
        self.log.see("end")
        self.root.update_idletasks()

    def _start_split(self):
        if self.is_running:
            return
        input_path = self.input_path.get().strip()
        output_dir = self.output_dir.get().strip()

        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror("오류", "유효한 입력 영상을 선택하세요.")
            return
        if not output_dir or not os.path.isdir(output_dir):
            messagebox.showerror("오류", "유효한 출력 폴더를 선택하세요.")
            return

        video_name = Path(input_path).stem
        scene_dir = Path(output_dir) / f"{video_name}_scenes"
        scene_dir.mkdir(parents=True, exist_ok=True)
        if self.save_thumbnails.get():
            (scene_dir / "thumbnails").mkdir(exist_ok=True)

        self.is_running = True
        self.run_btn.config(state="disabled", text="처리 중...")
        self.progress.start(10)

        threading.Thread(
            target=self._split_worker,
            args=(input_path, scene_dir),
            daemon=True,
        ).start()

    def _split_worker(self, input_path: str, scene_dir: Path):
        try:
            self._log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "accent")
            self._log(f"입력: {Path(input_path).name}", "info")
            self._log(f"출력: {scene_dir}", "info")
            self._log(f"엔진: {self.mode.get()}", "info")

            # 1. 컷 탐지
            t0 = time.time()
            if self.mode.get() == "transnet":
                try:
                    cuts = detect_scenes_transnet(
                        input_path,
                        self.transnet_threshold.get(),
                        self.min_scene_sec.get(),
                        self._log)
                except Exception as e:
                    self._log(f"✗ TransNetV2 실패: {e}", "error")
                    if PYSCENEDETECT_AVAILABLE:
                        self._log("→ PySceneDetect로 자동 폴백", "info")
                        cuts = detect_scenes_pyscenedetect(
                            input_path, self.detector_type.get(),
                            self.threshold.get(), self._log)
                    else:
                        return
            else:
                cuts = detect_scenes_pyscenedetect(
                    input_path, self.detector_type.get(),
                    self.threshold.get(), self._log)

            if not cuts:
                self._log("⚠ 컷이 감지되지 않았습니다.", "error")
                return

            self._log(f"  감지 소요: {time.time()-t0:.1f}초", "info")

            # 미리보기
            for i, (s, e) in enumerate(cuts[:8], 1):
                self._log(f"  {i:3d}. {s:8.2f}s → {e:8.2f}s  ({e-s:.2f}s)", "info")
            if len(cuts) > 8:
                self._log(f"  ... 외 {len(cuts) - 8}개", "info")

            # 2. 컷별 영상 + 섬네일 저장
            self._log("\n영상 분할 + 섬네일 저장 중...", "info")
            video_name = Path(input_path).stem
            saved = 0
            failed = 0
            thumb_dir = scene_dir / "thumbnails"

            for idx, (start, end) in enumerate(cuts, 1):
                num = f"{idx:03d}"
                clip_path = scene_dir / f"{video_name}-Scene-{num}.mp4"
                ok = split_video_segment(input_path, start, end, str(clip_path))

                thumb_ok = True
                if self.save_thumbnails.get():
                    thumb_path = thumb_dir / f"{video_name}-Scene-{num}.jpg"
                    # 시작 +0.05s 프레임 캡처 (검은 프레임/페이드 회피)
                    thumb_time = start + 0.05
                    thumb_ok = extract_jpeg_frame(input_path, thumb_time, str(thumb_path))

                if ok and thumb_ok:
                    saved += 1
                else:
                    failed += 1
                    self._log(f"  ✗ Scene {num} 실패", "error")

                if idx % 10 == 0 or idx == len(cuts):
                    self._log(f"  진행: {idx}/{len(cuts)}", "info")

            self._log(f"\n✓ 완료: {saved}개 저장 / {failed}개 실패", "success")
            self._log(f"📁 영상: {scene_dir}", "accent")
            if self.save_thumbnails.get():
                self._log(f"🖼  섬네일: {thumb_dir}", "accent")

            if sys.platform == "win32":
                self.root.after(0, lambda: self._ask_open_folder(str(scene_dir)))

        except Exception as e:
            self._log(f"\n✗ 오류: {e}", "error")
            import traceback
            self._log(traceback.format_exc(), "error")
        finally:
            self.is_running = False
            self.root.after(0, lambda: self.run_btn.config(state="normal", text="▶  분할 시작"))
            self.root.after(0, self.progress.stop)

    def _ask_open_folder(self, folder):
        if messagebox.askyesno("완료", "분할이 완료되었습니다. 폴더를 열까요?"):
            os.startfile(folder)


def main():
    root = tk.Tk()
    SceneSplitterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
