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
#
# 근본 문제 분석:
# - Adobe Sensei 기반 Scene Edit Detection은 비동기 ML 작업
# - 단일 JSX 호출 내에서 $.sleep으로 대기하면 ExtendScript가 메인 UI 스레드를 점유해
#   백그라운드 ML 처리까지 멈춰버림
# - 따라서 여러 Python 호출로 쪼개 Premiere가 실제 처리할 시간을 확보해야 함
#
# 전략:
#   STEP 1 (setup):     프로젝트 확보 → 영상 임포트 → 시퀀스 생성 → 클립 선택
#   STEP 2 (diagnose):  QE DOM 메서드 enumerate — setSceneEditDetection 존재 확인
#   STEP 3 (trigger):   setSceneEditDetection 호출. 즉시 return
#   STEP 4 (poll loop): Python이 주기적으로 클립 수를 조회 → 안정화 감지
#   STEP 5 (read):      최종 컷 경계 읽기

# ── STEP 1: 프로젝트/시퀀스/선택 준비 ──
JSX_SETUP = r"""
(function() {
    try {
        var videoPath = "__VIDEO_PATH__";

        // 프로젝트가 없으면 생성 (엉뚱한 상태 방지)
        if (!app.project || !app.project.rootItem) {
            return JSON.stringify({error: "열린 프로젝트 없음. Premiere에서 프로젝트를 먼저 여세요."});
        }

        // 1. 영상 임포트
        var beforeCount = app.project.rootItem.children.numItems;
        var ok = app.project.importFiles([videoPath], true, app.project.rootItem, false);
        if (!ok) { return JSON.stringify({error: "importFiles 반환값 false"}); }

        // 2. 임포트된 아이템 찾기
        var imported = null;
        var children = app.project.rootItem.children;
        for (var i = beforeCount; i < children.numItems; i++) {
            var child = children[i];
            if (child && child.type !== undefined && child.type !== 3 /* BIN */) {
                imported = child;
                break;
            }
        }
        if (!imported && children.numItems > beforeCount) {
            imported = children[beforeCount];
        }
        if (!imported) { return JSON.stringify({error: "임포트된 아이템을 못 찾음"}); }

        // 3. 미디어 분석 완료 대기 (최대 10초)
        //    importFiles 직후엔 메타데이터가 아직 준비 안 될 수 있음
        var mediaWait = 0;
        while (mediaWait < 20) {
            try {
                var mp = imported.getMediaPath();
                if (mp && mp.length > 0) break;
            } catch (mpErr) {}
            $.sleep(500);
            mediaWait++;
        }

        // 4. 시퀀스 생성
        var seqName = "SceneDetect_" + (new Date()).getTime();
        app.project.createNewSequenceFromClips(seqName, [imported], app.project.rootItem);
        var seq = app.project.activeSequence;
        if (!seq) { return JSON.stringify({error: "시퀀스 생성 실패"}); }

        // 5. 시퀀스를 명시적으로 active로 설정
        app.project.activeSequence = seq;

        // 6. 비디오 트랙 클립 선택
        var track = seq.videoTracks[0];
        if (!track || track.clips.numItems === 0) {
            return JSON.stringify({error: "비디오 트랙에 클립 없음"});
        }
        for (var k = 0; k < track.clips.numItems; k++) {
            track.clips[k].setSelected(true, k === 0);
        }

        return JSON.stringify({
            ok: true,
            sequenceName: seqName,
            initialCount: track.clips.numItems,
            mediaWaitSec: mediaWait * 0.5,
            pproVersion: app.version
        });
    } catch (e) {
        return JSON.stringify({error: "SETUP 예외: " + e.toString(), line: (e.line || "?")});
    }
})();
"""

# ── STEP 2: QE DOM 메서드 enumerate (진단용) ──
JSX_DIAGNOSE = r"""
(function() {
    try {
        app.enableQE();
        if (typeof qe === "undefined" || !qe) {
            return JSON.stringify({error: "qe 객체 자체가 없음. QE DOM 미지원 버전."});
        }
        var qeSeq = qe.project.getActiveSequence();
        if (!qeSeq) { return JSON.stringify({error: "qe.project.getActiveSequence() null"}); }

        var qeTrack = qeSeq.getVideoTrackAt(0);
        if (!qeTrack) { return JSON.stringify({error: "qe 비디오 트랙 null"}); }

        var numItems = qeTrack.numItems;
        var qeClip = qeTrack.getItemAt(0);
        if (!qeClip) { return JSON.stringify({error: "qe 클립 null", numItems: numItems}); }

        // 클립에서 setSceneEditDetection 메서드 존재 확인
        var hasMethod = (typeof qeClip.setSceneEditDetection === "function");

        // 사용 가능한 메서드 리스트
        var methods = [];
        for (var key in qeClip) {
            try {
                if (typeof qeClip[key] === "function") methods.push(key);
            } catch (_) {}
        }

        return JSON.stringify({
            ok: true,
            hasSetSceneEditDetection: hasMethod,
            qeTrackNumItems: numItems,
            qeClipType: (qeClip.type || "?"),
            qeClipName: (qeClip.name || "?"),
            methods: methods.join(",")
        });
    } catch (e) {
        return JSON.stringify({error: "DIAGNOSE 예외: " + e.toString()});
    }
})();
"""

# ── STEP 3: Scene Edit Detection 호출 (여러 시그니처 시도) ──
JSX_TRIGGER = r"""
(function() {
    try {
        var applyCuts = __APPLY_CUTS__;
        var createBins = __CREATE_BINS__;
        var createMarkers = __CREATE_MARKERS__;

        app.enableQE();
        var qeSeq = qe.project.getActiveSequence();
        if (!qeSeq) { return JSON.stringify({error: "active qe sequence 없음"}); }

        var qeTrack = qeSeq.getVideoTrackAt(0);
        var qeClip = qeTrack.getItemAt(0);
        if (!qeClip) { return JSON.stringify({error: "qe 클립 없음"}); }

        if (typeof qeClip.setSceneEditDetection !== "function") {
            return JSON.stringify({
                error: "setSceneEditDetection 메서드가 QE 클립에 존재하지 않음",
                hint: "Premiere Pro 2020 (14.3) 이상 + 호환 GPU 필요"
            });
        }

        // 호출 시도 — 3-arg 형식
        var called = false;
        var lastErr = null;
        var usedSignature = null;

        try {
            qeClip.setSceneEditDetection(applyCuts, createBins, createMarkers);
            called = true;
            usedSignature = "3-arg";
        } catch (e3) {
            lastErr = e3.toString();
            // 1-arg 폴백
            try {
                qeClip.setSceneEditDetection(applyCuts);
                called = true;
                usedSignature = "1-arg";
            } catch (e1) {
                lastErr = lastErr + " | 1-arg: " + e1.toString();
            }
        }

        if (!called) {
            return JSON.stringify({error: "호출 실패: " + lastErr});
        }

        return JSON.stringify({ok: true, usedSignature: usedSignature});
    } catch (e) {
        return JSON.stringify({error: "TRIGGER 예외: " + e.toString()});
    }
})();
"""

# ── STEP 4: 현재 타임라인 클립 수 조회 ──
JSX_POLL_COUNT = r"""
(function() {
    try {
        var seq = app.project.activeSequence;
        if (!seq) { return JSON.stringify({error: "active sequence 없음"}); }
        var track = seq.videoTracks[0];
        if (!track) { return JSON.stringify({error: "비디오 트랙 없음"}); }
        return JSON.stringify({count: track.clips.numItems});
    } catch (e) {
        return JSON.stringify({error: e.toString()});
    }
})();
"""

# ── STEP 5: 최종 컷 경계 읽기 ──
JSX_READ_CUTS = r"""
(function() {
    try {
        var seq = app.project.activeSequence;
        if (!seq) { return JSON.stringify({error: "active sequence 없음"}); }
        var track = seq.videoTracks[0];
        var TPS = 254016000000;
        var cuts = [];
        for (var j = 0; j < track.clips.numItems; j++) {
            var c = track.clips[j];
            cuts.push({
                start: c.start.ticks / TPS,
                end: c.end.ticks / TPS
            });
        }
        return JSON.stringify({ok: true, cuts: cuts, count: cuts.length});
    } catch (e) {
        return JSON.stringify({error: e.toString()});
    }
})();
"""


def _jsx_call(script: str, timeout: int = 120) -> dict:
    """JSX 실행 후 JSON 파싱"""
    raw = pymiere_eval(script, timeout=timeout)
    raw = (raw or "").strip()
    if not raw:
        raise RuntimeError("Premiere가 빈 응답 반환")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"JSON 파싱 실패: {raw[:300]}")


def detect_scenes_premiere(video_path: str, apply_cuts: bool,
                           create_bins: bool, create_markers: bool,
                           log_fn) -> list:
    """
    Premiere Pro Scene Edit Detection — 멀티 스텝 폴링 방식.
    Adobe Sensei가 비동기 ML로 처리하므로 각 단계 사이에 Premiere에 시간 확보.
    """
    log_fn("Premiere Pro에 연결 중...", "info")
    if not pymiere_check_connection():
        raise RuntimeError(
            "Premiere Pro에 연결할 수 없습니다.\n"
            "1) Premiere Pro가 실행 중이고 프로젝트가 열려 있는지 확인\n"
            "2) Pymiere Link CEP 확장이 설치/활성화되었는지 확인\n"
            "   (localhost:3000에서 응답해야 함)"
        )

    # ── STEP 1: Setup ──
    log_fn("[1/5] 영상 임포트 + 시퀀스 생성...", "info")
    safe_path = video_path.replace("\\", "\\\\").replace('"', '\\"')
    setup_script = JSX_SETUP.replace("__VIDEO_PATH__", safe_path)
    data = _jsx_call(setup_script, timeout=120)
    if "error" in data:
        raise RuntimeError(f"Setup 실패: {data['error']}")
    seq_name = data.get("sequenceName", "?")
    initial = data.get("initialCount", "?")
    ppro_ver = data.get("pproVersion", "?")
    log_fn(f"  ✓ Premiere {ppro_ver} / 시퀀스: {seq_name}", "success")
    log_fn(f"  ✓ 초기 클립 수: {initial}", "info")

    # ── STEP 2: Diagnose — setSceneEditDetection이 실제로 있는지 확인 ──
    log_fn("[2/5] QE DOM 진단 중...", "info")
    data = _jsx_call(JSX_DIAGNOSE, timeout=30)
    if "error" in data:
        raise RuntimeError(f"진단 실패: {data['error']}")

    has_method = data.get("hasSetSceneEditDetection", False)
    if not has_method:
        methods = data.get("methods", "")
        raise RuntimeError(
            "setSceneEditDetection 메서드가 QE DOM 클립에 존재하지 않습니다.\n"
            f"Premiere Pro 버전 호환성 문제일 가능성이 높습니다.\n"
            f"사용 가능한 메서드: {methods[:500]}"
        )
    log_fn("  ✓ setSceneEditDetection 메서드 확인됨", "success")

    # ── STEP 3: Trigger (비동기 호출) ──
    log_fn("[3/5] Scene Edit Detection 실행 트리거...", "info")
    trigger_script = (
        JSX_TRIGGER
        .replace("__APPLY_CUTS__", "true" if apply_cuts else "false")
        .replace("__CREATE_BINS__", "true" if create_bins else "false")
        .replace("__CREATE_MARKERS__", "true" if create_markers else "false")
    )
    data = _jsx_call(trigger_script, timeout=60)
    if "error" in data:
        hint = data.get("hint", "")
        msg = f"트리거 실패: {data['error']}"
        if hint:
            msg += f"\n힌트: {hint}"
        raise RuntimeError(msg)
    log_fn(f"  ✓ 트리거 완료 (시그니처: {data.get('usedSignature', '?')})", "success")

    # ── STEP 4: Poll — 클립 수가 안정될 때까지 대기 ──
    log_fn("[4/5] 감지 진행 중 폴링...", "info")
    log_fn("  ⚠ Adobe Sensei ML 분석 중. 영상 길이에 비례해 시간 소요.", "info")

    last_count = int(initial) if isinstance(initial, int) else 1
    stable_secs = 0
    total_waited = 0
    poll_interval = 3  # seconds
    stable_threshold = 15  # 15초 이상 변화 없으면 완료로 판단
    max_wait = 1800  # 최대 30분

    while total_waited < max_wait:
        time.sleep(poll_interval)
        total_waited += poll_interval
        try:
            data = _jsx_call(JSX_POLL_COUNT, timeout=15)
        except Exception as e:
            log_fn(f"  폴링 일시 실패 ({e}), 재시도...", "info")
            continue

        if "error" in data:
            log_fn(f"  폴링 에러: {data['error']}", "info")
            continue

        current = data.get("count", 0)
        if current != last_count:
            log_fn(f"  [{total_waited}s] 클립 수: {last_count} → {current}", "info")
            last_count = current
            stable_secs = 0
        else:
            stable_secs += poll_interval
            if current > 1 and stable_secs >= stable_threshold:
                log_fn(f"  ✓ 안정화 감지 ({current}개, {stable_secs}s 안정)", "success")
                break
            if total_waited % 15 == 0:
                log_fn(f"  [{total_waited}s] 대기 중... 현재 {current}개", "info")

    if last_count <= 1:
        raise RuntimeError(
            f"{max_wait}초 동안 Scene Edit Detection이 컷을 생성하지 않았습니다.\n"
            "가능한 원인:\n"
            "1) Premiere Pro 버전이 이 기능을 지원하지 않음 (14.3 이상 필요)\n"
            "2) 영상에 실제 장면 전환이 없음\n"
            "3) Adobe Sensei ML 모델 로드 실패 — Premiere를 재시작 후 재시도\n"
            "4) GPU 가속이 비활성화되어 있음 — 환경 설정에서 확인"
        )

    # ── STEP 5: Read cuts ──
    log_fn("[5/5] 최종 컷 경계 읽기...", "info")
    data = _jsx_call(JSX_READ_CUTS, timeout=30)
    if "error" in data:
        raise RuntimeError(f"읽기 실패: {data['error']}")

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
        # Premiere Scene Edit Detection 옵션 (실제 다이얼로그와 동일)
        self.premiere_apply_cuts = tk.BooleanVar(value=True)
        self.premiere_create_bins = tk.BooleanVar(value=False)
        self.premiere_create_markers = tk.BooleanVar(value=False)
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

        # Premiere 옵션 (실제 '장면 편집 탐지' 다이얼로그와 동일한 3개 체크박스)
        self.premiere_opts = ttk.Frame(self.options_frame, style="App.TFrame")
        ttk.Label(self.premiere_opts,
                  text="Premiere '장면 편집 탐지' 옵션",
                  style="Field.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(self.premiere_opts,
                        text="각 감지된 잘라내기 포인트에 잘라내기 적용 (필수)",
                        variable=self.premiere_apply_cuts).pack(anchor="w", pady=2)
        ttk.Checkbutton(self.premiere_opts,
                        text="감지된 각 절단 지점에서 하위 클립 저장소 만들기",
                        variable=self.premiere_create_bins).pack(anchor="w", pady=2)
        ttk.Checkbutton(self.premiere_opts,
                        text="감지된 잘라내기 포인트의 각각에 클립 마커 만들기",
                        variable=self.premiere_create_markers).pack(anchor="w", pady=2)
        ttk.Label(self.premiere_opts,
                  text="Premiere Pro 2020 이상 필요. 민감도는 Premiere가 자동 결정합니다.",
                  style="Hint.TLabel").pack(anchor="w", pady=(4, 0))

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
                        input_path,
                        self.premiere_apply_cuts.get(),
                        self.premiere_create_bins.get(),
                        self.premiere_create_markers.get(),
                        self._log)
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
