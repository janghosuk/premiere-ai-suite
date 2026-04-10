"""
Scene Splitter — 장면 편집 탐지로 영상을 컷 단위로 분할
- 모드 1: Premiere Pro의 Scene Edit Detection 사용 (Premiere Pro 실행 + Pymiere Link 필요)
- 모드 2: PySceneDetect 사용 (오프라인, ffmpeg만 있으면 됨)
각 컷의 첫 프레임은 JPEG 섬네일로 자동 저장됩니다.
"""

import os
import sys
import io
import json
import time
import threading
import shutil
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# UTF-8 출력 (Windows cp949 호환)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# PySceneDetect (오프라인 모드)
try:
    from scenedetect import detect, ContentDetector, AdaptiveDetector, ThresholdDetector
    PYSCENEDETECT_AVAILABLE = True
except ImportError:
    PYSCENEDETECT_AVAILABLE = False

# Pymiere (Premiere Pro 모드) - HTTP 직접 호출이라 requests만 있으면 됨
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


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

PYMIERE_URL = "http://127.0.0.1:3000"


def get_desktop_path() -> Path:
    """OS별 데스크탑 경로 (한국어 Windows 포함)"""
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "바탕 화면",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "바탕 화면",
    ]
    for p in candidates:
        if p.exists():
            return p
    return home


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def run_ffmpeg(args: list, timeout: int = 120) -> tuple:
    """ffmpeg 실행. (success, stderr) 반환."""
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
    """주어진 시간 지점의 프레임을 고품질 JPEG로 저장"""
    args = [
        "-ss", f"{time_sec:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",  # 고품질 (1=최고, 31=최저)
        output_path,
    ]
    ok, _ = run_ffmpeg(args, timeout=30)
    return ok


def split_video_segment(video_path: str, start_sec: float, end_sec: float, output_path: str) -> bool:
    """ffmpeg 스트림 카피로 영상 구간 추출 (무손실, 빠름)"""
    args = [
        "-ss", f"{start_sec:.3f}",
        "-to", f"{end_sec:.3f}",
        "-i", video_path,
        "-c", "copy",
        "-map", "0",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ]
    ok, _ = run_ffmpeg(args, timeout=120)
    return ok


# ─── Pymiere Link HTTP 클라이언트 ───
def pymiere_eval(script: str, timeout: int = 60) -> str:
    """Premiere Pro에 ExtendScript 실행 요청"""
    if not REQUESTS_AVAILABLE:
        raise RuntimeError("requests 라이브러리가 필요합니다: pip install requests")
    response = requests.post(
        PYMIERE_URL,
        json={"to_eval": script},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def pymiere_check_connection() -> bool:
    """Premiere Pro에 연결 가능한지 확인"""
    if not REQUESTS_AVAILABLE:
        return False
    try:
        result = pymiere_eval("app.version", timeout=5)
        return bool(result and result.strip())
    except Exception:
        return False


# ─── Premiere Pro Scene Edit Detection ───
PREMIERE_DETECT_JSX = r"""
(function() {
    try {
        var videoPath = "__VIDEO_PATH__";
        var sensitivity = __SENSITIVITY__;

        // 1. 영상 임포트
        var beforeCount = app.project.rootItem.children.numItems;
        var ok = app.project.importFiles([videoPath], true, app.project.rootItem, false);
        if (!ok) { return JSON.stringify({error: "임포트 실패"}); }

        // 2. 임포트된 아이템 찾기
        var imported = null;
        var children = app.project.rootItem.children;
        for (var i = beforeCount; i < children.numItems; i++) {
            imported = children[i];
            break;
        }
        if (!imported) { return JSON.stringify({error: "임포트된 아이템을 찾을 수 없음"}); }

        // 3. 시퀀스 생성 (영상 클릭으로 자동 매칭)
        var seqName = "SceneDetect_" + (new Date()).getTime();
        app.project.createNewSequenceFromClips(seqName, [imported], app.project.rootItem);
        var seq = app.project.activeSequence;
        if (!seq) { return JSON.stringify({error: "시퀀스 생성 실패"}); }

        // 4. QE DOM으로 Scene Edit Detection 실행
        app.enableQE();
        var qeSeq = qe.project.getActiveSequence();
        if (!qeSeq) { return JSON.stringify({error: "QE 시퀀스 접근 실패"}); }

        // 첫 비디오 트랙의 첫 클립에 Scene Edit Detection 적용
        var qeTrack = qeSeq.getVideoTrackAt(0);
        if (!qeTrack || qeTrack.numItems === 0) {
            return JSON.stringify({error: "비디오 트랙에 클립 없음"});
        }
        var qeClip = qeTrack.getItemAt(0);
        // applyCutsToTimeline=true, generateClipMarkers=false, sensitivity=0~1
        qeClip.setSceneEditDetection(true, false, sensitivity);

        // 5. 결과 읽기 - 시퀀스의 모든 클립 in/out 시간
        var fps = seq.getSettings().videoFrameRate.seconds;
        // ticksPerSecond = 254016000000 (Adobe 표준)
        var TPS = 254016000000;
        var track = seq.videoTracks[0];
        var cuts = [];
        for (var j = 0; j < track.clips.numItems; j++) {
            var c = track.clips[j];
            var startSec = c.start.ticks / TPS;
            var endSec = c.end.ticks / TPS;
            cuts.push({start: startSec, end: endSec});
        }

        return JSON.stringify({
            ok: true,
            cuts: cuts,
            sequenceName: seqName,
            count: cuts.length
        });
    } catch (e) {
        return JSON.stringify({error: e.toString()});
    }
})();
"""


def detect_scenes_premiere(video_path: str, sensitivity: float, log_fn) -> list:
    """Premiere Pro의 Scene Edit Detection 실행. [(start_sec, end_sec), ...] 반환"""
    log_fn("Premiere Pro에 연결 중...", "info")
    if not pymiere_check_connection():
        raise RuntimeError(
            "Premiere Pro에 연결할 수 없습니다.\n"
            "1) Premiere Pro가 실행 중인지 확인\n"
            "2) Pymiere Link CEP 확장이 설치/활성화되었는지 확인"
        )
    log_fn("✓ Premiere Pro 연결됨", "success")

    # JSX 스크립트의 경로 이스케이프
    safe_path = video_path.replace("\\", "\\\\").replace('"', '\\"')
    script = PREMIERE_DETECT_JSX.replace("__VIDEO_PATH__", safe_path)
    script = script.replace("__SENSITIVITY__", f"{sensitivity:.3f}")

    log_fn("Scene Edit Detection 실행 중... (수십 초 ~ 수 분 소요)", "info")
    log_fn("⚠ Premiere Pro 화면이 잠시 멈춘 것처럼 보일 수 있습니다.", "info")

    # 매우 긴 타임아웃 - Scene Edit Detection은 영상 길이에 비례
    raw = pymiere_eval(script, timeout=1800)
    raw = (raw or "").strip()

    if not raw:
        raise RuntimeError("Premiere Pro에서 빈 응답")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"응답 파싱 실패: {raw[:300]}")

    if "error" in data:
        raise RuntimeError(f"Premiere 오류: {data['error']}")

    cuts = [(c["start"], c["end"]) for c in data.get("cuts", [])]
    log_fn(f"✓ Premiere가 {len(cuts)}개 컷 감지", "success")
    return cuts


# ─── PySceneDetect ───
def detect_scenes_pyscenedetect(video_path: str, detector_type: str,
                                  threshold: float, log_fn) -> list:
    """PySceneDetect 실행. [(start_sec, end_sec), ...] 반환"""
    if not PYSCENEDETECT_AVAILABLE:
        raise RuntimeError("PySceneDetect가 설치되지 않음: pip install scenedetect[opencv]")

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


class SceneSplitterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Scene Splitter")
        self.root.geometry("720x780")
        self.root.minsize(600, 640)
        self.root.configure(bg=BG)

        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(get_desktop_path()))
        self.mode = tk.StringVar(value="premiere")  # premiere | pyscenedetect
        self.threshold = tk.DoubleVar(value=27.0)
        self.threshold_text = tk.StringVar(value="27.0")
        self.sensitivity = tk.DoubleVar(value=0.5)
        self.sensitivity_text = tk.StringVar(value="0.50")
        self.detector_type = tk.StringVar(value="content")
        self.save_thumbnails = tk.BooleanVar(value=True)
        self.is_running = False

        self._setup_styles()
        self._build_ui()
        self._check_environment()

    # ─── 스타일 ───
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

    # ─── UI ───
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

        ttk.Label(header,
                  text="장면 편집 탐지로 영상을 컷별로 자동 분할 + JPEG 섬네일 저장",
                  style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

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

        # 탐지 모드
        ttk.Label(main, text="탐지 모드", style="Field.TLabel").pack(anchor="w", pady=(0, 6))
        mode_frame = ttk.Frame(main, style="App.TFrame")
        mode_frame.pack(fill="x", pady=(0, 12))
        ttk.Radiobutton(mode_frame,
                        text="Premiere Pro Scene Edit Detection (Premiere 실행 필요)",
                        variable=self.mode, value="premiere",
                        command=self._on_mode_change).pack(anchor="w", pady=2)
        ttk.Radiobutton(mode_frame,
                        text="PySceneDetect (오프라인, ffmpeg만 필요)",
                        variable=self.mode, value="pyscenedetect",
                        command=self._on_mode_change).pack(anchor="w", pady=2)

        # 옵션 컨테이너 (모드별 전환)
        self.options_frame = ttk.Frame(main, style="App.TFrame")
        self.options_frame.pack(fill="x", pady=(0, 12))

        # Premiere 옵션 (민감도)
        self.premiere_opts = ttk.Frame(self.options_frame, style="App.TFrame")
        sens_row = ttk.Frame(self.premiere_opts, style="App.TFrame")
        sens_row.pack(fill="x", pady=(0, 4))
        ttk.Label(sens_row, text="민감도 (Premiere)", style="Field.TLabel").pack(side="left")
        ttk.Label(sens_row, textvariable=self.sensitivity_text, style="Value.TLabel").pack(side="right")
        ttk.Scale(self.premiere_opts, from_=0.1, to=1.0, variable=self.sensitivity,
                  orient="horizontal",
                  command=lambda v: self.sensitivity_text.set(f"{float(v):.2f}")).pack(
                      fill="x", pady=(4, 4))
        ttk.Label(self.premiere_opts,
                  text="값이 높을수록 더 많이 자릅니다 (기본 0.5)",
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
        ttk.Label(thresh_row, textvariable=self.threshold_text, style="Value.TLabel").pack(side="right")
        ttk.Scale(self.pyscene_opts, from_=5, to=60, variable=self.threshold,
                  orient="horizontal",
                  command=lambda v: self.threshold_text.set(f"{float(v):.1f}")).pack(
                      fill="x", pady=(4, 4))
        ttk.Label(self.pyscene_opts,
                  text="값이 낮을수록 더 많이 자릅니다 (기본 27)",
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

        # 로그 영역
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
        if self.mode.get() == "premiere":
            self.premiere_opts.pack(fill="x")
        else:
            self.pyscene_opts.pack(fill="x")

    def _check_environment(self):
        ok = True
        if not check_ffmpeg():
            self._log("⚠ ffmpeg가 PATH에 없습니다 (필수).", "error")
            self._log("  Windows: winget install Gyan.FFmpeg", "info")
            ok = False
        if not REQUESTS_AVAILABLE:
            self._log("⚠ requests가 없습니다 (Premiere 모드에 필요): pip install requests", "error")
        if not PYSCENEDETECT_AVAILABLE:
            self._log("⚠ PySceneDetect 미설치 (오프라인 모드에 필요): pip install scenedetect[opencv]", "info")

        if ok:
            self._log("Scene Splitter 준비 완료", "success")
            self._log(f"기본 출력 폴더: {self.output_dir.get()}", "info")
            self._log("영상을 선택하고 모드를 고른 뒤 '분할 시작'을 누르세요.\n", "info")
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

    # ─── 분할 실행 ───
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
            self._log(f"모드: {self.mode.get()}", "info")

            # 1. 컷 탐지
            t0 = time.time()
            if self.mode.get() == "premiere":
                try:
                    cuts = detect_scenes_premiere(
                        input_path, self.sensitivity.get(), self._log)
                except Exception as e:
                    self._log(f"✗ Premiere Pro 모드 실패: {e}", "error")
                    if PYSCENEDETECT_AVAILABLE:
                        self._log("→ PySceneDetect로 폴백합니다.", "info")
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
                    # 컷 시작에서 약간 안쪽 (0.05초 후) 프레임 추출 — 검은 프레임 회피
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
