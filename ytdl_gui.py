# -*- coding: utf-8 -*-
"""
YouTube 다운로더 (Windows GUI)
yt-dlp / yl.exe 커맨드라인 프로그램을 감싸는 tkinter 앱.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, font as tkfont

APP_NAME = "YouTube 다운로더"
APP_VERSION = "1.1"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

CONFIG_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "YoutubeDownloader"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# 진행률을 파싱하기 쉽게 만드는 yt-dlp 템플릿
PROGRESS_MARK = "@@PROG@@"
PROGRESS_TEMPLATE = (
    "download:" + PROGRESS_MARK
    + "%(progress._percent_str)s@@%(progress._speed_str)s@@%(progress._eta_str)s"
)
PROGRESS_RE = re.compile(re.escape(PROGRESS_MARK) + r"([^@]*)@@([^@]*)@@([^@]*)")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PERCENT_RE = re.compile(r"([\d.]+)\s*%")

# 화질 (상 / 중 / 하)
VIDEO_FORMATS = {
    "상": "bv*[height<=2160]+ba/b[height<=2160]/bv*+ba/b",
    "중": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
    "하": "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b",
}
# 음질 (yt-dlp --audio-quality: 0=최고, 10=최저)
AUDIO_QUALITY = {"상": "0", "중": "5", "하": "9"}

QUALITY_HINT = {
    "video": {
        "상": "최대 2160p (4K) · MP4",
        "중": "최대 1080p (FHD) · MP4",
        "하": "최대 480p (SD) · MP4",
    },
    "audio": {
        "상": "MP3 최고 음질 (약 320kbps)",
        "중": "MP3 표준 음질 (약 192kbps)",
        "하": "MP3 저용량 (약 128kbps)",
    },
}

# yt-dlp 버전은 배포 날짜(YYYY.MM.DD)다. 유튜브가 자주 바뀌어 이보다 오래된 버전은
# 다운로드 도중 HTTP 403 으로 끊기곤 한다 (2026.03.17·2026.07.04 가 4.3% 지점에서 403, 2026.08.19 는 정상).
STALE_DAYS = 60

# yl.exe / yt-dlp.exe 자동 탐지 후보
EXE_CANDIDATES = [
    "yl.exe",
    "yl",
    "yt-dlp.exe",
    "yt-dlp",
]
EXTRA_EXE_PATHS = [
    r"C:\Program Files\KMPlayer 64X\yt-dlp.exe",
    r"C:\Program Files\KMPlayer\yt-dlp.exe",
]


def strip_ansi(text):
    return ANSI_RE.sub("", text)


def app_dir():
    """실행 파일(빌드본) 또는 스크립트가 있는 폴더."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def bundled_bin_dir():
    """내장 바이너리 폴더(bin). 없으면 빈 문자열."""
    d = os.path.join(app_dir(), "bin")
    return d if os.path.isdir(d) else ""


def subprocess_env():
    """내장 bin 폴더를 PATH 맨 앞에 붙인 환경변수.

    yt-dlp 가 ffmpeg/qjs 를 PATH 에서도 찾을 수 있게 해준다.
    """
    env = os.environ.copy()
    b = bundled_bin_dir()
    if b:
        env["PATH"] = b + os.pathsep + env.get("PATH", "")
    return env


def find_downloader():
    """내장 bin/ → 앱 폴더 → PATH → 알려진 설치 경로 순으로 찾는다."""
    for base in (bundled_bin_dir(), app_dir()):
        if not base:
            continue
        for name in EXE_CANDIDATES:
            path = os.path.join(base, name)
            if os.path.isfile(path):
                return path
    for name in EXE_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    for path in EXTRA_EXE_PATHS:
        if os.path.isfile(path):
            return path
    return ""


def find_ffmpeg_dir():
    """내장 ffmpeg 를 우선 사용하고, 없으면 PATH 에서 찾는다."""
    b = bundled_bin_dir()
    if b and os.path.isfile(os.path.join(b, "ffmpeg.exe")):
        return b
    found = shutil.which("ffmpeg")
    return os.path.dirname(found) if found else ""


# yt-dlp 런타임 이름 -> 실제 실행 파일 이름
JS_RUNTIMES = [("deno", "deno"), ("node", "node"), ("quickjs", "qjs")]


def find_js_runtime():
    """최신 yt-dlp 는 YouTube 추출에 JS 런타임이 필요하다.

    기본 활성화는 deno 뿐이라, 쓸 수 있는 런타임을 찾아 --js-runtimes 로 넘긴다.
    내장 bin/qjs.exe(QuickJS, 약 1.7MB)를 우선 사용하므로 별도 설치가 필요 없다.
    """
    b = bundled_bin_dir()
    if b:
        for runtime, binary in JS_RUNTIMES:
            path = os.path.join(b, binary + ".exe")
            if os.path.isfile(path):
                return runtime, path
    for runtime, binary in JS_RUNTIMES:
        found = shutil.which(binary)
        if found:
            return runtime, found
    return "", ""


def downloader_version(path):
    """다운로더의 --version 출력. 실패하면 빈 문자열."""
    try:
        out = subprocess.run(
            [path, "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW, timeout=60, env=subprocess_env(),
        )
        return (out.stdout or out.stderr).strip()
    except Exception:
        return ""


def version_age_days(version):
    """'2026.08.19' 같은 yt-dlp 버전이 며칠 전 것인지. 날짜 형식이 아니면 None."""
    m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", version or "")
    if not m:
        return None
    try:
        released = datetime.date(*(int(g) for g in m.groups()))
    except ValueError:
        return None
    return (datetime.date.today() - released).days


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()

        self.items = []           # [{'url':..., 'status':...}]
        self.worker = None
        self.proc = None
        self.stop_requested = False
        self.msg_queue = queue.Queue()

        # 설정에는 [다운로더 실행 파일 지정] 으로 직접 고른 경로만 남긴다.
        # 예전 "downloader_path" 는 자동 탐지 결과까지 저장해 한 번 잡힌 경로(예: KMPlayer 동봉본)가
        # 굳어 버렸고, 내장 bin 에 새 yt-dlp 가 있어도 쓰이지 않았다. 그래서 그 값은 읽지 않는다.
        self.custom_downloader = self.cfg.get("custom_downloader_path", "")
        if self.custom_downloader and not os.path.isfile(self.custom_downloader):
            self.custom_downloader = ""
        self.downloader_path = self.custom_downloader or find_downloader()
        self.ffmpeg_dir = find_ffmpeg_dir()
        self.js_runtime, self.js_runtime_path = find_js_runtime()

        default_dir = self.cfg.get(
            "output_dir", os.path.join(os.path.expanduser("~"), "Downloads")
        )

        self.var_url = tk.StringVar()
        self.var_mode = tk.StringVar(value=self.cfg.get("mode", "video"))
        self.var_quality = tk.StringVar(value=self.cfg.get("quality", "중"))
        self.var_playlist = tk.BooleanVar(value=self.cfg.get("playlist", False))
        self.var_outdir = tk.StringVar(value=default_dir)
        self.var_status = tk.StringVar(value="대기 중")
        self.var_progress = tk.DoubleVar(value=0.0)
        self.var_speed = tk.StringVar(value="")
        self.var_current = tk.StringVar(value="")

        self._build_ui()
        self._update_quality_hint()
        self._check_downloader()
        self.root.after(100, self._pump_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = self.root
        root.title(f"{APP_NAME} v{APP_VERSION}")
        root.geometry("820x760")
        root.minsize(720, 640)

        # 한글이 잘 보이도록 기본 폰트 지정
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family="Malgun Gothic", size=10)
            except Exception:
                pass

        self._build_menu()

        pad = {"padx": 10, "pady": 6}

        # --- 링크 추가 ---
        frm_add = ttk.LabelFrame(root, text="1. 링크 추가")
        frm_add.pack(fill="x", **pad)
        entry = ttk.Entry(frm_add, textvariable=self.var_url)
        entry.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=10)
        entry.bind("<Return>", lambda e: self.add_url())
        entry.focus_set()
        ttk.Button(frm_add, text="추가", width=10, command=self.add_url).pack(
            side="left", pady=10
        )
        ttk.Button(
            frm_add, text="클립보드에서", width=12, command=self.add_from_clipboard
        ).pack(side="left", padx=(6, 10), pady=10)

        # --- 목록 ---
        frm_list = ttk.LabelFrame(root, text="2. 다운로드 목록")
        frm_list.pack(fill="both", expand=True, **pad)

        cols = ("no", "url", "status")
        self.tree = ttk.Treeview(
            frm_list, columns=cols, show="headings", height=7, selectmode="extended"
        )
        self.tree.heading("no", text="#")
        self.tree.heading("url", text="링크")
        self.tree.heading("status", text="상태")
        self.tree.column("no", width=40, anchor="center", stretch=False)
        self.tree.column("url", width=540, anchor="w")
        self.tree.column("status", width=140, anchor="center", stretch=False)
        self.tree.tag_configure("done", foreground="#1a7f37")
        self.tree.tag_configure("error", foreground="#c22")
        self.tree.tag_configure("active", foreground="#0b57d0")

        vsb = ttk.Scrollbar(frm_list, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(10, 0))
        vsb.pack(side="left", fill="y", padx=(0, 10), pady=(10, 0))

        frm_btn = ttk.Frame(frm_list)
        frm_btn.pack(side="bottom", fill="x", padx=10, pady=8)
        ttk.Button(frm_btn, text="선택 삭제", command=self.remove_selected).pack(
            side="left"
        )
        ttk.Button(frm_btn, text="전체 삭제", command=self.clear_all).pack(
            side="left", padx=6
        )

        # --- 옵션 ---
        frm_opt = ttk.LabelFrame(root, text="3. 다운로드 옵션")
        frm_opt.pack(fill="x", **pad)

        row1 = ttk.Frame(frm_opt)
        row1.pack(fill="x", padx=10, pady=(10, 2))
        ttk.Label(row1, text="형식:", width=6).pack(side="left")
        ttk.Radiobutton(
            row1, text="비디오 (MP4)", value="video",
            variable=self.var_mode, command=self._update_quality_hint,
        ).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(
            row1, text="오디오 (MP3)", value="audio",
            variable=self.var_mode, command=self._update_quality_hint,
        ).pack(side="left")

        row2 = ttk.Frame(frm_opt)
        row2.pack(fill="x", padx=10, pady=2)
        ttk.Label(row2, text="품질:", width=6).pack(side="left")
        for q in ("상", "중", "하"):
            ttk.Radiobutton(
                row2, text=q, value=q,
                variable=self.var_quality, command=self._update_quality_hint,
            ).pack(side="left", padx=(0, 16))
        self.lbl_hint = ttk.Label(row2, text="", foreground="#555")
        self.lbl_hint.pack(side="left", padx=(10, 0))

        row3 = ttk.Frame(frm_opt)
        row3.pack(fill="x", padx=10, pady=(2, 10))
        ttk.Checkbutton(
            row3,
            text="재생목록 링크일 때 전체 다운로드 (해제 시 해당 영상 1개만)",
            variable=self.var_playlist,
        ).pack(side="left")

        # --- 저장 폴더 ---
        frm_dir = ttk.LabelFrame(root, text="4. 저장 폴더")
        frm_dir.pack(fill="x", **pad)
        ttk.Entry(frm_dir, textvariable=self.var_outdir).pack(
            side="left", fill="x", expand=True, padx=(10, 6), pady=10
        )
        ttk.Button(frm_dir, text="폴더 선택", width=10, command=self.choose_dir).pack(
            side="left", pady=10
        )
        ttk.Button(frm_dir, text="폴더 열기", width=10, command=self.open_dir).pack(
            side="left", padx=(6, 10), pady=10
        )

        # --- 진행 상황 ---
        frm_run = ttk.Frame(root)
        frm_run.pack(fill="x", **pad)

        bar_row = ttk.Frame(frm_run)
        bar_row.pack(fill="x")
        self.pbar = ttk.Progressbar(
            bar_row, variable=self.var_progress, maximum=100.0, mode="determinate"
        )
        self.pbar.pack(side="left", fill="x", expand=True)
        ttk.Label(bar_row, textvariable=self.var_speed, width=26, anchor="e").pack(
            side="left", padx=(8, 0)
        )

        info_row = ttk.Frame(frm_run)
        info_row.pack(fill="x", pady=(4, 0))
        ttk.Label(info_row, textvariable=self.var_status, foreground="#0b57d0").pack(
            side="left"
        )
        ttk.Label(
            info_row, textvariable=self.var_current, foreground="#555", anchor="w"
        ).pack(side="left", fill="x", expand=True, padx=(10, 0))

        btn_row = ttk.Frame(frm_run)
        btn_row.pack(fill="x", pady=(8, 0))
        self.btn_start = ttk.Button(
            btn_row, text="다운로드 시작", command=self.start_download
        )
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(
            btn_row, text="중지", command=self.stop_download, state="disabled"
        )
        self.btn_stop.pack(side="left", padx=6)

        # --- 로그 ---
        frm_log = ttk.LabelFrame(root, text="로그")
        frm_log.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(
            frm_log, height=9, wrap="word", state="disabled",
            font=("Consolas", 9), background="#1e1e1e", foreground="#dcdcdc",
        )
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="저장 폴더 선택...", command=self.choose_dir)
        m_file.add_command(label="저장 폴더 열기", command=self.open_dir)
        m_file.add_separator()
        m_file.add_command(label="종료", command=self.on_close)
        menubar.add_cascade(label="파일", menu=m_file)

        m_tool = tk.Menu(menubar, tearoff=0)
        m_tool.add_command(
            label="다운로더 실행 파일 지정... (yl.exe / yt-dlp.exe)",
            command=self.choose_downloader,
        )
        m_tool.add_command(
            label="다운로더 자동 탐지로 되돌리기", command=self.reset_downloader
        )
        m_tool.add_command(label="다운로더 버전 확인", command=self.show_downloader_version)
        m_tool.add_command(label="다운로더 업데이트", command=self.update_downloader)
        m_tool.add_separator()
        m_tool.add_command(label="로그 지우기", command=self.clear_log)
        menubar.add_cascade(label="도구", menu=m_tool)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="정보", command=self.show_about)
        menubar.add_cascade(label="도움말", menu=m_help)

        self.root.config(menu=menubar)

    # ------------------------------------------------------------- helpers
    def _update_quality_hint(self):
        mode = self.var_mode.get()
        q = self.var_quality.get()
        self.lbl_hint.config(text=QUALITY_HINT[mode][q])

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _check_downloader(self):
        if self.downloader_path and os.path.isfile(self.downloader_path):
            how = "직접 지정" if self.custom_downloader else "자동 탐지"
            self.write_log(f"[준비] 다운로더({how}): {self.downloader_path}")
            self._report_version_async()
            if self.ffmpeg_dir:
                self.write_log(f"[준비] ffmpeg: {self.ffmpeg_dir}")
            else:
                self.write_log(
                    "[경고] ffmpeg 을 찾지 못했습니다. 고화질 병합/MP3 변환이 실패할 수 있습니다."
                )
            if self.js_runtime:
                self.write_log(
                    f"[준비] JS 런타임: {self.js_runtime} ({self.js_runtime_path})"
                )
            else:
                self.write_log(
                    "[경고] JS 런타임(deno/node)을 찾지 못했습니다. "
                    "YouTube 에서 일부 화질이 누락될 수 있습니다."
                )
        else:
            self.write_log(
                "[오류] yl.exe / yt-dlp.exe 를 찾지 못했습니다. "
                "[도구] > [다운로더 실행 파일 지정] 에서 직접 선택하세요."
            )

    def _report_version_async(self):
        """다운로더 버전을 로그에 남기고, 오래됐으면 업데이트를 권한다.

        yt-dlp 는 단일 exe 라 --version 에도 1~2초 걸려서 창이 멈추지 않게 스레드로 돈다.
        """
        path = self.downloader_path

        def run():
            ver = downloader_version(path)
            if not ver:
                self.msg_queue.put(("log", "[경고] 다운로더 버전을 확인하지 못했습니다."))
                return
            age = version_age_days(ver)
            note = f" ({age}일 전 버전)" if age is not None else ""
            self.msg_queue.put(("log", f"[준비] 다운로더 버전: {ver}{note}"))
            if age is not None and age > STALE_DAYS:
                self.msg_queue.put((
                    "log",
                    f"[경고] 다운로더가 {age}일 된 버전입니다. 유튜브 다운로드가 "
                    "HTTP 403 으로 끊길 수 있습니다 → [도구] > [다운로더 업데이트]",
                ))

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------ 목록 조작
    def add_url(self):
        raw = self.var_url.get().strip()
        if not raw:
            return
        added = 0
        for url in raw.split():
            url = url.strip()
            if not url:
                continue
            if not url.lower().startswith(("http://", "https://")):
                messagebox.showwarning(
                    APP_NAME, f"올바른 링크가 아닙니다:\n{url}"
                )
                continue
            if any(it["url"] == url for it in self.items):
                self.write_log(f"[건너뜀] 이미 목록에 있음: {url}")
                continue
            self.items.append({"url": url, "status": "대기"})
            added += 1
        if added:
            self.var_url.set("")
            self.refresh_tree()

    def add_from_clipboard(self):
        try:
            text = self.root.clipboard_get()
        except Exception:
            messagebox.showinfo(APP_NAME, "클립보드가 비어 있습니다.")
            return
        self.var_url.set(text.strip())
        self.add_url()

    def remove_selected(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_NAME, "다운로드 중에는 목록을 수정할 수 없습니다.")
            return
        sel = self.tree.selection()
        if not sel:
            return
        idxs = sorted((int(i) for i in sel), reverse=True)
        for i in idxs:
            del self.items[i]
        self.refresh_tree()

    def clear_all(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_NAME, "다운로드 중에는 목록을 수정할 수 없습니다.")
            return
        self.items.clear()
        self.refresh_tree()

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.items):
            tag = ""
            if it["status"] == "완료":
                tag = "done"
            elif it["status"].startswith("실패") or it["status"] == "중지됨":
                tag = "error"
            elif it["status"] == "다운로드 중":
                tag = "active"
            self.tree.insert(
                "", "end", iid=str(i),
                values=(i + 1, it["url"], it["status"]),
                tags=(tag,) if tag else (),
            )

    # ------------------------------------------------------------ 폴더/설정
    def choose_dir(self):
        initial = self.var_outdir.get()
        if not os.path.isdir(initial):
            initial = os.path.expanduser("~")
        path = filedialog.askdirectory(
            title="저장 폴더 선택", initialdir=initial, mustexist=False
        )
        if path:
            self.var_outdir.set(os.path.normpath(path))
            self.persist()

    def open_dir(self):
        path = self.var_outdir.get().strip()
        if not path:
            messagebox.showinfo(APP_NAME, "저장 폴더가 지정되지 않았습니다.")
            return
        if not os.path.isdir(path):
            if not messagebox.askyesno(
                APP_NAME, f"폴더가 없습니다:\n{path}\n\n지금 만들까요?"
            ):
                return
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                messagebox.showerror(APP_NAME, f"폴더를 만들 수 없습니다:\n{e}")
                return
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"폴더를 열 수 없습니다:\n{e}")

    def choose_downloader(self):
        path = filedialog.askopenfilename(
            title="다운로더 실행 파일 선택 (yl.exe / yt-dlp.exe)",
            filetypes=[("실행 파일", "*.exe"), ("모든 파일", "*.*")],
        )
        if path:
            self.custom_downloader = os.path.normpath(path)
            self.downloader_path = self.custom_downloader
            self.persist()
            self.write_log(f"[설정] 다운로더 경로(직접 지정): {self.downloader_path}")
            self._report_version_async()

    def reset_downloader(self):
        self.custom_downloader = ""
        self.downloader_path = find_downloader()
        self.persist()
        if self.downloader_path:
            self.write_log(f"[설정] 다운로더 경로(자동 탐지): {self.downloader_path}")
            self._report_version_async()
        else:
            self.write_log("[오류] yl.exe / yt-dlp.exe 를 찾지 못했습니다.")

    def show_downloader_version(self):
        if not self._require_downloader():
            return
        ver = downloader_version(self.downloader_path)
        if not ver:
            messagebox.showerror(APP_NAME, "버전을 확인할 수 없습니다.")
            return
        age = version_age_days(ver)
        note = f" ({age}일 전 버전)" if age is not None else ""
        messagebox.showinfo(
            APP_NAME, f"실행 파일:\n{self.downloader_path}\n\n버전: {ver}{note}"
        )

    def update_downloader(self):
        if not self._require_downloader():
            return
        if not messagebox.askyesno(APP_NAME, "다운로더를 최신 버전으로 업데이트할까요?"):
            return

        def run():
            self.msg_queue.put(("log", "[업데이트] 시작..."))
            try:
                out = subprocess.run(
                    [self.downloader_path, "-U"],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", creationflags=CREATE_NO_WINDOW, timeout=300,
                    env=subprocess_env(),
                )
                for line in (out.stdout + out.stderr).splitlines():
                    if line.strip():
                        self.msg_queue.put(("log", "[업데이트] " + line.strip()))
            except Exception as e:
                self.msg_queue.put(("log", f"[업데이트] 실패: {e}"))
                return
            if out.returncode != 0:
                # C:\Program Files 아래 exe(KMPlayer 동봉본 등)는 관리자 권한 없이 덮어쓸 수 없다
                self.msg_queue.put((
                    "log",
                    "[업데이트] 실패. 프로그램 폴더의 exe 는 관리자 권한이 필요할 수 있습니다. "
                    "최신 yt-dlp.exe 를 받아 [도구] > [다운로더 실행 파일 지정] 으로 고르세요.",
                ))
            ver = downloader_version(self.downloader_path)
            if ver:
                self.msg_queue.put(("log", f"[업데이트] 현재 버전: {ver}"))

        threading.Thread(target=run, daemon=True).start()

    def show_about(self):
        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "yt-dlp / yl.exe 커맨드라인 다운로더를 사용하는 GUI 앱입니다.\n\n"
            f"다운로더: {self.downloader_path or '(미지정)'}\n"
            f"ffmpeg: {self.ffmpeg_dir or '(없음)'}\n"
            f"JS 런타임: {self.js_runtime or '(없음)'}\n"
            f"내장 bin: {bundled_bin_dir() or '(없음 - 시스템 설치본 사용)'}\n"
            f"설정 파일: {CONFIG_PATH}\n\n"
            "본인이 권한을 가진 콘텐츠에 대해서만 사용하세요.",
        )

    def persist(self):
        save_config(
            {
                "custom_downloader_path": self.custom_downloader,
                "output_dir": self.var_outdir.get(),
                "mode": self.var_mode.get(),
                "quality": self.var_quality.get(),
                "playlist": self.var_playlist.get(),
            }
        )

    def _require_downloader(self):
        if self.downloader_path and os.path.isfile(self.downloader_path):
            return True
        messagebox.showerror(
            APP_NAME,
            "다운로더 실행 파일(yl.exe / yt-dlp.exe)을 찾을 수 없습니다.\n"
            "[도구] > [다운로더 실행 파일 지정] 에서 선택하세요.",
        )
        return False

    # ------------------------------------------------------------ 다운로드
    def build_command(self, url, outdir):
        mode = self.var_mode.get()
        q = self.var_quality.get()

        cmd = [
            self.downloader_path,
            "--ignore-config",
            "--newline",
            "--no-update",
            "--color", "never",
            # 파이프로 내보낼 때 yt-dlp 는 윈도우 코드페이지(cp949)를 쓴다. 이 앱은 UTF-8 로
            # 읽으므로 맞춰 주지 않으면 로그의 한글 제목이 깨진다 (파일 이름 자체는 정상).
            "--encoding", "utf-8",
            "--progress-template", PROGRESS_TEMPLATE,
            "--windows-filenames",
            "--no-mtime",
            "-P", outdir,
        ]

        if self.js_runtime:
            cmd += ["--js-runtimes", self.js_runtime]

        if self.var_playlist.get():
            cmd += ["--yes-playlist",
                    "-o", "%(playlist_title|)s/%(playlist_index|)s%(playlist_index& - |)s%(title)s.%(ext)s"]
        else:
            cmd += ["--no-playlist", "-o", "%(title)s.%(ext)s"]

        if self.ffmpeg_dir:
            cmd += ["--ffmpeg-location", self.ffmpeg_dir]

        if mode == "video":
            cmd += [
                "-f", VIDEO_FORMATS[q],
                "--merge-output-format", "mp4",
                "--embed-metadata",
            ]
        else:
            cmd += [
                "-f", "ba/b",
                "-x",
                "--audio-format", "mp3",
                "--audio-quality", AUDIO_QUALITY[q],
                "--embed-metadata",
                "--embed-thumbnail",
            ]

        cmd.append(url)
        return cmd

    def start_download(self):
        if self.worker and self.worker.is_alive():
            return
        if not self._require_downloader():
            return
        if not self.items:
            messagebox.showinfo(APP_NAME, "다운로드할 링크를 먼저 추가하세요.")
            return

        outdir = self.var_outdir.get().strip()
        if not outdir:
            messagebox.showinfo(APP_NAME, "저장 폴더를 선택하세요.")
            return
        if not os.path.isdir(outdir):
            try:
                os.makedirs(outdir, exist_ok=True)
            except Exception as e:
                messagebox.showerror(APP_NAME, f"저장 폴더를 만들 수 없습니다:\n{e}")
                return

        self.persist()
        self.stop_requested = False
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")

        for it in self.items:
            if it["status"] in ("완료",):
                continue
            it["status"] = "대기"
        self.refresh_tree()

        self.worker = threading.Thread(
            target=self._run_all, args=(outdir,), daemon=True
        )
        self.worker.start()

    def stop_download(self):
        self.stop_requested = True
        self.msg_queue.put(("log", "[중지] 요청됨. 현재 작업을 정리하는 중..."))
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, creationflags=CREATE_NO_WINDOW,
                )
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _run_all(self, outdir):
        total = len(self.items)
        ok = failed = 0

        for idx, item in enumerate(self.items):
            if self.stop_requested:
                self.msg_queue.put(("status", idx, "중지됨"))
                continue
            if item["status"] == "완료":
                ok += 1
                continue

            self.msg_queue.put(("status", idx, "다운로드 중"))
            self.msg_queue.put(
                ("overall", f"{idx + 1}/{total} 진행 중", item["url"])
            )
            self.msg_queue.put(("progress", 0.0, ""))
            self.msg_queue.put(("log", f"\n===== [{idx + 1}/{total}] {item['url']}"))

            code = self._run_one(item["url"], outdir)

            if self.stop_requested:
                self.msg_queue.put(("status", idx, "중지됨"))
                break
            if code == 0:
                ok += 1
                self.msg_queue.put(("status", idx, "완료"))
                self.msg_queue.put(("progress", 100.0, ""))
            else:
                failed += 1
                self.msg_queue.put(("status", idx, f"실패({code})"))

        summary = f"완료 {ok}건" + (f" · 실패 {failed}건" if failed else "")
        if self.stop_requested:
            summary = "중지됨 · " + summary
        self.msg_queue.put(("done", summary))

    def _run_one(self, url, outdir):
        cmd = self.build_command(url, outdir)
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
                env=subprocess_env(),
            )
        except Exception as e:
            self.msg_queue.put(("log", f"[오류] 실행 실패: {e}"))
            return -1

        got_403 = False
        try:
            for raw in self.proc.stdout:
                line = strip_ansi(raw).rstrip()
                if not line:
                    continue

                m = PROGRESS_RE.search(line)
                if m:
                    pct_raw, speed, eta = (s.strip() for s in m.groups())
                    pm = PERCENT_RE.search(pct_raw)
                    pct = float(pm.group(1)) if pm else None
                    label = ""
                    if speed and speed not in ("Unknown", "N/A"):
                        label = speed
                    if eta and eta not in ("Unknown", "N/A"):
                        label = (label + "  ETA " + eta).strip()
                    self.msg_queue.put(("progress", pct, label))
                    continue

                self.msg_queue.put(("log", line))

                if "HTTP Error 403" in line:
                    got_403 = True
                if "[download] Destination:" in line:
                    self.msg_queue.put(
                        ("current", os.path.basename(line.split("Destination:", 1)[1].strip()))
                    )
                elif "Merging formats into" in line:
                    self.msg_queue.put(("current", "영상/음성 병합 중..."))
                elif "[ExtractAudio]" in line:
                    self.msg_queue.put(("current", "MP3 변환 중..."))
        except Exception as e:
            self.msg_queue.put(("log", f"[오류] 출력 처리 실패: {e}"))
        finally:
            try:
                self.proc.wait(timeout=30)
            except Exception:
                pass

        code = self.proc.returncode if self.proc.returncode is not None else -1
        self.proc = None
        if got_403 and code != 0:
            self.msg_queue.put((
                "log",
                "[안내] HTTP 403 은 대개 yt-dlp 가 오래돼서 생깁니다. "
                "[도구] > [다운로더 업데이트] 후 다시 시도하세요.",
            ))
        return code

    # -------------------------------------------------------- UI 메시지 펌프
    def _pump_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]

                if kind == "log":
                    self.write_log(msg[1])
                elif kind == "progress":
                    pct, label = msg[1], msg[2]
                    if pct is not None:
                        self.var_progress.set(pct)
                    self.var_speed.set(label)
                elif kind == "status":
                    idx, status = msg[1], msg[2]
                    if 0 <= idx < len(self.items):
                        self.items[idx]["status"] = status
                        self.refresh_tree()
                elif kind == "overall":
                    self.var_status.set(msg[1])
                    self.var_current.set(msg[2])
                elif kind == "current":
                    self.var_current.set(msg[1])
                elif kind == "done":
                    self.var_status.set(msg[1])
                    self.var_current.set("")
                    self.var_speed.set("")
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")
                    self.write_log(f"\n===== {msg[1]}")
        except queue.Empty:
            pass
        self.root.after(100, self._pump_queue)

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                APP_NAME, "다운로드가 진행 중입니다. 중지하고 종료할까요?"
            ):
                return
            self.stop_download()
        self.persist()
        self.root.destroy()


def selftest():
    """구성 요소 탐지 결과를 파일로 남긴다. (--selftest)

    windowed 빌드는 콘솔이 없어 stdout 을 볼 수 없으므로 파일로 기록한다.
    """
    import tempfile

    lines = [
        f"frozen       = {getattr(sys, 'frozen', False)}",
        f"app_dir      = {app_dir()}",
        f"bundled bin  = {bundled_bin_dir() or '(none)'}",
        f"downloader   = {find_downloader() or '(none)'}",
        f"ffmpeg dir   = {find_ffmpeg_dir() or '(none)'}",
    ]
    runtime, rt_path = find_js_runtime()
    lines.append(f"js runtime   = {runtime or '(none)'}  ({rt_path or '-'})")

    def probe(path, args, label):
        if not path:
            lines.append(f"{label}: (not found)")
            return
        try:
            out = subprocess.run(
                [path] + args, capture_output=True, text=True, encoding="utf-8",
                errors="replace", creationflags=CREATE_NO_WINDOW, timeout=60,
                env=subprocess_env(),
            )
            first = ((out.stdout or out.stderr).strip().splitlines() or ["(no output)"])[0]
            lines.append(f"{label}: {first}")
        except Exception as e:
            lines.append(f"{label}: FAILED {e}")

    probe(find_downloader(), ["--version"], "yt-dlp --version")
    ffdir = find_ffmpeg_dir()
    probe(os.path.join(ffdir, "ffmpeg.exe") if ffdir else "", ["-hide_banner", "-version"], "ffmpeg -version")
    probe(os.path.join(ffdir, "ffprobe.exe") if ffdir else "", ["-hide_banner", "-version"], "ffprobe -version")
    probe(rt_path, ["-e", "console.log('quickjs ok')"] if runtime == "quickjs" else ["--version"], "js runtime")

    report = "\n".join(lines)
    out_path = os.path.join(tempfile.gettempdir(), "ytdl_selftest.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    return out_path


def main():
    if "--selftest" in sys.argv:
        selftest()
        return

    root = tk.Tk()
    try:
        # 고DPI 화면에서 흐릿하게 보이지 않도록
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
