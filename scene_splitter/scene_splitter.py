"""
Scene Splitter — 장면 편집 탐지로 영상을 컷 단위로 분할
Premiere Pro 없이 PySceneDetect + ffmpeg만으로 동작합니다.
"""

import os
import sys
import io
import threading
import shutil
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# UTF-8 출력 (Windows cp949 호환)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# 의존성 체크
try:
    from scenedetect import detect, ContentDetector, AdaptiveDetector, ThresholdDetector
    from scenedetect.video_splitter import split_video_ffmpeg
except ImportError as e:
    print(f"[오류] PySceneDetect가 설치되어 있지 않습니다: {e}")
    print("설치: pip install scenedetect[opencv]")
    input("종료하려면 Enter...")
    sys.exit(1)


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


class SceneSplitterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Scene Splitter")
        self.root.geometry("700x680")
        self.root.minsize(580, 560)
        self.root.configure(bg=BG)

        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(get_desktop_path()))
        self.threshold = tk.DoubleVar(value=27.0)
        self.threshold_text = tk.StringVar(value="27.0")
        self.detector_type = tk.StringVar(value="content")
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
        header.pack(fill="x", pady=(0, 18))

        title_row = ttk.Frame(header, style="App.TFrame")
        title_row.pack(fill="x")

        dot = tk.Canvas(title_row, width=14, height=14, bg=BG, highlightthickness=0)
        dot.create_oval(2, 2, 12, 12, fill=ACCENT, outline="")
        dot.pack(side="left", padx=(0, 8))

        ttk.Label(title_row, text="Scene Splitter", style="Title.TLabel").pack(side="left")

        ttk.Label(header,
                  text="장면 편집 탐지로 영상을 컷별로 자동 분할합니다",
                  style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

        # 입력 영상
        ttk.Label(main, text="입력 영상 파일", style="Field.TLabel").pack(anchor="w", pady=(0, 6))
        in_frame = ttk.Frame(main, style="App.TFrame")
        in_frame.pack(fill="x", pady=(0, 14))
        ttk.Entry(in_frame, textvariable=self.input_path).pack(
            side="left", fill="x", expand=True, padx=(0, 8), ipady=4)
        ttk.Button(in_frame, text="찾아보기", command=self._browse_input).pack(side="right")

        # 출력 폴더
        ttk.Label(main, text="출력 폴더", style="Field.TLabel").pack(anchor="w", pady=(0, 6))
        out_frame = ttk.Frame(main, style="App.TFrame")
        out_frame.pack(fill="x", pady=(0, 14))
        ttk.Entry(out_frame, textvariable=self.output_dir).pack(
            side="left", fill="x", expand=True, padx=(0, 8), ipady=4)
        ttk.Button(out_frame, text="찾아보기", command=self._browse_output).pack(side="right")

        # 탐지기
        ttk.Label(main, text="탐지 방식", style="Field.TLabel").pack(anchor="w", pady=(0, 6))
        det_frame = ttk.Frame(main, style="App.TFrame")
        det_frame.pack(fill="x", pady=(0, 14))
        for label, value in [
            ("Content — 콘텐츠 변화 (일반 권장)", "content"),
            ("Adaptive — 조명 변화에 강함", "adaptive"),
            ("Threshold — 페이드/검은 화면 감지", "threshold"),
        ]:
            ttk.Radiobutton(det_frame, text=label, variable=self.detector_type,
                            value=value).pack(anchor="w", pady=2)

        # 임계값 슬라이더
        thresh_row = ttk.Frame(main, style="App.TFrame")
        thresh_row.pack(fill="x", pady=(0, 4))
        ttk.Label(thresh_row, text="민감도 임계값", style="Field.TLabel").pack(side="left")
        ttk.Label(thresh_row, textvariable=self.threshold_text, style="Value.TLabel").pack(side="right")

        ttk.Scale(main, from_=5, to=60, variable=self.threshold,
                  orient="horizontal", command=self._on_threshold_change).pack(
                      fill="x", pady=(4, 4))
        ttk.Label(main, text="값이 낮을수록 더 많이 자릅니다 (기본 27)",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 18))

        # 실행 버튼
        self.run_btn = ttk.Button(main, text="▶  분할 시작",
                                   command=self._start_split, style="Accent.TButton")
        self.run_btn.pack(fill="x", pady=(0, 14))

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

    # ─── 이벤트 ───
    def _on_threshold_change(self, value):
        self.threshold_text.set(f"{float(value):.1f}")

    def _check_environment(self):
        if not check_ffmpeg():
            self._log("⚠ ffmpeg가 PATH에 없습니다. 설치 후 다시 실행하세요.", "error")
            self._log("  Windows: winget install Gyan.FFmpeg", "info")
            self._log("  또는 https://ffmpeg.org/download.html", "info")
            self.run_btn.config(state="disabled")
        else:
            self._log("Scene Splitter 준비 완료", "success")
            self._log(f"기본 출력 폴더: {self.output_dir.get()}", "info")
            self._log("영상 파일을 선택하고 '분할 시작'을 눌러주세요.\n", "info")

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

        # 영상 이름으로 서브폴더 생성
        video_name = Path(input_path).stem
        scene_dir = Path(output_dir) / f"{video_name}_scenes"
        scene_dir.mkdir(parents=True, exist_ok=True)

        self.is_running = True
        self.run_btn.config(state="disabled", text="처리 중...")
        self.progress.start(10)

        threading.Thread(
            target=self._split_worker,
            args=(input_path, str(scene_dir)),
            daemon=True,
        ).start()

    def _split_worker(self, input_path, output_dir):
        try:
            self._log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "accent")
            self._log(f"입력: {Path(input_path).name}", "info")
            self._log(f"출력: {output_dir}", "info")

            detector_name = self.detector_type.get()
            threshold = self.threshold.get()

            if detector_name == "content":
                detector = ContentDetector(threshold=threshold, min_scene_len=15)
            elif detector_name == "adaptive":
                # Adaptive는 별도 임계값 스케일 사용
                detector = AdaptiveDetector(adaptive_threshold=max(1.0, threshold / 9))
            else:
                detector = ThresholdDetector(threshold=threshold, min_scene_len=15)

            self._log(f"탐지기: {detector_name} (임계값 {threshold:.1f})", "info")
            self._log("장면 분석 중...", "info")

            scene_list = detect(input_path, detector, show_progress=False)

            if not scene_list:
                self._log("⚠ 장면이 감지되지 않았습니다. 임계값을 낮춰보세요.", "error")
                return

            self._log(f"✓ {len(scene_list)}개 장면 감지됨", "success")
            for i, (start, end) in enumerate(scene_list[:10], 1):
                self._log(f"  {i:3d}. {start.get_timecode()} → {end.get_timecode()}", "info")
            if len(scene_list) > 10:
                self._log(f"  ... 외 {len(scene_list) - 10}개", "info")

            # ffmpeg 분할 (스트림 카피, 무손실, 빠름)
            self._log("\n영상 분할 중 (ffmpeg)...", "info")

            video_name = Path(input_path).stem
            split_video_ffmpeg(
                input_path,
                scene_list,
                output_dir=output_dir,
                output_file_template=f"{video_name}-Scene-$SCENE_NUMBER.mp4",
                show_progress=False,
                arg_override="-c:v copy -c:a copy -map 0 -avoid_negative_ts make_zero",
            )

            self._log(f"\n✓ 완료! {len(scene_list)}개 컷 저장됨", "success")
            self._log(f"📁 {output_dir}", "accent")

            if sys.platform == "win32":
                self.root.after(0, lambda: self._ask_open_folder(output_dir))

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
