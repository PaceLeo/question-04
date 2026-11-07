#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面小宠物 v3 —— 带「应用感知」

在 v2（已修坐标浮点 & emoji 问题）基础上新增：
  · 定时读取当前前台窗口的进程名/窗口标题（Win32 API，零依赖）
  · 根据焦点应用（浏览器 / 编辑器 / 聊天 / 终端 / 办公 / 桌面…）说不同的话
  · 切换应用 → 触发首次反应；久待同一应用 → 偶尔闲聊
  · 右键菜单可开关「应用感知」
  · 非 Windows 平台自动禁用该能力，其余功能不受影响
"""

import os
import math
import random
import platform
import time
import traceback
import tkinter as tk

# ==================== 平台 / Win32 API ====================
IS_WIN = platform.system() == "Windows"

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetForegroundWindow.argtypes = []

    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]

    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]

    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def _get_foreground():
        """返回 (pid, exe名小写, 窗口标题)；失败返回 (None, None, None)"""
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None, None, None

        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        length = _user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, title_buf, length + 1)
        title = title_buf.value

        exe = None
        h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if h:
            try:
                size = wintypes.DWORD(1024)
                path_buf = ctypes.create_unicode_buffer(1024)
                if _kernel32.QueryFullProcessImageNameW(h, 0, path_buf, ctypes.byref(size)):
                    exe = path_buf.value.rsplit("\\", 1)[-1].lower()
            finally:
                _kernel32.CloseHandle(h)

        return pid.value, exe, title

else:
    def _get_foreground():
        return None, None, None


# ==================== 应用规则表 ====================
# exe：精确匹配的小写进程名
# first：切到这个应用时说的话
# idle：在这个应用上待久了偶尔说的话
APP_RULES = [
    {
        "exe": ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
                "360se.exe", "qqbrowser.exe"),
        "name": "浏览器",
        "first": ["又在上网冲浪呀～", "网上有什么好玩的？", "别刷太久啦～"],
        "idle": ["眼睛累了吧，看看远方～", "记得喝水哦～", "要不要回来摸摸我？"],
    },
    {
        "exe": ("code.exe", "code - insiders.exe", "pycharm64.exe", "pycharm.exe",
                "idea64.exe", "devenv.exe", "sublime_text.exe", "notepad++.exe",
                "vim.exe", "nvim.exe"),
        "name": "代码编辑器",
        "first": ["写代码啦！加油～", "又双叒叕在 debug？", "这个 bug 一定能搞定！"],
        "idle": ["记得保存哦！", "这段代码一定很酷～", "肩膀放松一下～", "Ctrl+S 按了吗？"],
    },
    {
        "exe": ("cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe", "mintty.exe",
                "bash.exe", "windowsterminal.exe", "wt.exe"),
        "name": "终端",
        "first": ["黑客时间到！", "命令行大佬～", "又在敲命令呀"],
        "idle": ["sudo 加权限！", "小心 rm -rf 哦～", "又卡住了？"],
    },
    {
        "exe": ("wechat.exe", "weixin.exe", "qq.exe", "tim.exe", "telegram.exe",
                "dingtalk.exe", "feishu.exe", "lark.exe", "discord.exe", "slack.exe"),
        "name": "聊天软件",
        "first": ["在聊天呀～", "别聊太久哦", "有人找我吗？"],
        "idle": ["我也想参与！", "聊什么呢？", "记得回我消息～"],
    },
    {
        "exe": ("winword.exe", "excel.exe", "powerpnt.exe", "wps.exe", "et.exe",
                "wpp.exe", "acrobat.exe"),
        "name": "办公软件",
        "first": ["在忙工作呀～", "文档写得怎么样啦？", "又要做表格…"],
        "idle": ["辛苦啦～", "记得多喝水", "做完记得休息"],
    },
    {
        "exe": ("vlc.exe", "potplayermini64.exe", "potplayermini.exe",
                "mpc-hc64.exe", "wmplayer.exe", "bilibili.exe", "iqiyi.exe", "youku.exe"),
        "name": "视频播放器",
        "first": ["看电影呀！我也要看～", "剧情怎么样？", "偷偷摸鱼被发现啦"],
        "idle": ["好看吗？", "别剧透哦～"],
    },
    {
        "exe": ("steam.exe", "epicgameslauncher.exe", "origin.exe", "uplay.exe", "wegame.exe"),
        "name": "游戏平台",
        "first": ["要玩游戏了吗？", "带我一起玩～", "游戏时间到！"],
        "idle": ["赢了吗？", "别玩太晚哦～"],
    },
    {
        "exe": ("spotify.exe", "cloudmusic.exe", "qqmusic.exe", "kugou.exe", "foobar2000.exe"),
        "name": "音乐软件",
        "first": ["听歌呀～", "什么歌这么好听？"],
        "idle": ["我也要听～", "单曲循环了吗？"],
    },
    {
        "exe": ("explorer.exe",),
        "name": "文件管理器",
        "first": ["在翻文件呀～", "找什么呢？"],
        "idle": ["要不要整理一下桌面？"],
    },
    {
        "exe": ("notepad.exe",),
        "name": "记事本",
        "first": ["记事本写啥呢？", "在记笔记呀～"],
        "idle": ["记得保存～"],
    },
    {
        "exe": ("taskmgr.exe",),
        "name": "任务管理器",
        "first": ["电脑卡了吗？", "别关掉我呀！", "别看我占多少内存…"],
        "idle": ["我占的可不多！"],
    },
    {
        "exe": ("desktop",),
        "name": "桌面",
        "first": ["在桌面上发呆呀～", "好安静～"],
        "idle": ["陪我玩一会儿嘛～", "戳戳我呀～"],
    },
]


def match_app(exe):
    if not exe:
        return None
    for rule in APP_RULES:
        if exe in rule["exe"]:
            return rule
    return None


# ==================== 配置 ====================
TRANS = "#FF00FE"
FONT = ("Microsoft YaHei", 11)
FPS_MS = 45
WALK_SPEED = 3.2
CHECK_INTERVAL = 30          # 每 30 帧（约 1.35s）读一次前台应用

CLICK_TALK = [
    "哎呀，别戳我～", "痒痒的！", "你好呀！", "在呢在呢～",
    "要摸摸头吗？", "嘿！我在工作呢～",
]
CHAT = [
    "今天也要加油哦！", "记得喝水呀～", "坐久了要起来动一动",
    "我陪你一起～", "嘿嘿～", "天气怎么样呀？",
]


class DesktopPet:
    W, H = 220, 250
    CX = 110

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        bg = TRANS
        if IS_WIN:
            self.root.configure(bg=TRANS)
            try:
                self.root.wm_attributes("-transparentcolor", TRANS)
            except tk.TclError:
                self.root.attributes("-alpha", 0.96)
                bg = "#EFEFEF"
        else:
            try:
                self.root.wm_attributes("-transparent", True)
                bg = "systemTransparent"
            except tk.TclError:
                self.root.attributes("-alpha", 0.96)
                bg = "#EFEFEF"
                self.root.configure(bg=bg)

        self.sw = self.root.winfo_screenwidth()
        self.sh = self.root.winfo_screenheight()

        self.x = self.sw - self.W - 100
        self.y = self.sh - self.H - 90
        self.root.geometry(f"{self.W}x{self.H}+{int(self.x)}+{int(self.y)}")

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H,
                                bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack()

        # 动画状态
        self.facing = -1
        self.mode = "idle"
        self.phase = 0.0
        self.timer = 90
        self.frame = 0
        self.blinking = False
        self.blink_left = 0
        self.blink_cd = random.randint(40, 120)
        self.talking = False
        self.talk_until = 0.0
        self.dragging = False
        self._moved = 0
        self._err_shown = False

        # 应用感知状态
        self.my_pid = os.getpid()
        self.app_aware = IS_WIN
        self._check_cd = 0
        self.cur_app = None       # {"exe":..., "rule":..., "since":...}
        self.idle_cd = 0          # 帧

        self._build()
        self._bind()

    # ==================== 绘制 ====================
    def _build(self):
        c = self.canvas
        it = self.it = {}
        OUT, BODY, INNER = "#C98A3E", "#FFC97A", "#FF9B9B"
        EYE, BLUSH = "#3A2A20", "#FFA6B8"

        it["tail_o"] = c.create_line(0, 0, 0, 0, 0, 0, smooth=True, width=16,
                                     fill=OUT, capstyle="round", joinstyle="round")
        it["tail_f"] = c.create_line(0, 0, 0, 0, 0, 0, smooth=True, width=10,
                                     fill=BODY, capstyle="round", joinstyle="round")

        it["ear_l"] = c.create_polygon(0, 0, 0, 0, 0, 0, fill=BODY, outline=OUT, width=3)
        it["ear_r"] = c.create_polygon(0, 0, 0, 0, 0, 0, fill=BODY, outline=OUT, width=3)
        it["ear_in_l"] = c.create_polygon(0, 0, 0, 0, 0, 0, fill=INNER, outline="")
        it["ear_in_r"] = c.create_polygon(0, 0, 0, 0, 0, 0, fill=INNER, outline="")

        it["foot_l"] = c.create_oval(0, 0, 0, 0, fill=BODY, outline=OUT, width=3)
        it["foot_r"] = c.create_oval(0, 0, 0, 0, fill=BODY, outline=OUT, width=3)
        it["body"] = c.create_oval(0, 0, 0, 0, fill=BODY, outline=OUT, width=3)

        it["eye_l"] = c.create_oval(0, 0, 0, 0, fill=EYE, outline="")
        it["eye_r"] = c.create_oval(0, 0, 0, 0, fill=EYE, outline="")
        it["hl_l"] = c.create_oval(0, 0, 0, 0, fill="white", outline="")
        it["hl_r"] = c.create_oval(0, 0, 0, 0, fill="white", outline="")

        it["blush_l"] = c.create_oval(0, 0, 0, 0, fill=BLUSH, outline="")
        it["blush_r"] = c.create_oval(0, 0, 0, 0, fill=BLUSH, outline="")
        it["nose"] = c.create_polygon(0, 0, 0, 0, 0, 0, fill=OUT, outline="")
        it["mouth"] = c.create_line(0, 0, 0, 0, 0, 0, smooth=True, width=3,
                                    fill=OUT, capstyle="round")
        it["mouth_open"] = c.create_oval(0, 0, 0, 0, fill="#8B4A3B", outline=OUT,
                                         width=2, state="hidden")

        it["b_tail"] = c.create_polygon(96, 72, 124, 72, 110, 90,
                                        fill="white", outline="", state="hidden")
        rect = self._round_rect(14, 8, 206, 74, 16)
        it["b_bg"] = c.create_polygon(*[v for p in rect for v in p], smooth=True,
                                      fill="white", outline="", state="hidden")
        it["b_text"] = c.create_text(110, 41, text="", font=FONT, fill="#3A3A3A",
                                     width=168, justify="center", state="hidden")

    @staticmethod
    def _round_rect(x1, y1, x2, y2, r):
        return [
            (x1 + r, y1), (x2 - r, y1), (x2, y1), (x2, y1 + r),
            (x2, y2 - r), (x2, y2), (x2 - r, y2), (x1 + r, y2),
            (x1, y2), (x1, y2 - r), (x1, y1 + r), (x1, y1),
        ]

    def _render(self):
        c, it = self.canvas, self.it
        mir = self.facing < 0

        def set_(key, pts):
            flat = []
            for x, y in pts:
                flat.append(self.W - x if mir else x)
                flat.append(y)
            c.coords(it[key], *flat)

        walking = (self.mode == "walk" and not self.dragging)
        bob = -abs(math.sin(self.phase)) * 2.5 if walking else math.sin(self.phase) * 1.2
        tw = math.sin(self.phase * 0.8) * 5

        if walking:
            fl = max(0.0, math.sin(self.phase)) * 7
            fr = max(0.0, -math.sin(self.phase)) * 7
        else:
            fl = fr = 0.0
        b = bob

        tail = [(150, 206 + b), (190, 200 + b), (198 + tw, 174 + b), (184 + tw, 158 + b)]
        set_("tail_o", tail)
        set_("tail_f", tail)

        set_("ear_l", [(74, 146 + b), (58, 92 + b), (108, 116 + b)])
        set_("ear_r", [(146, 146 + b), (162, 92 + b), (112, 116 + b)])
        set_("ear_in_l", [(78, 128 + b), (72, 109 + b), (90, 117 + b)])
        set_("ear_in_r", [(142, 128 + b), (148, 109 + b), (130, 117 + b)])

        set_("foot_l", [(78, 222 - fl), (106, 244 - fl)])
        set_("foot_r", [(114, 222 - fr), (142, 244 - fr)])
        set_("body", [(58, 124 + b), (162, 234 + b)])

        if self.blinking:
            ey1, ey2 = 165 + b, 171 + b
        else:
            ey1, ey2 = 159 + b, 177 + b
        set_("eye_l", [(85, ey1), (99, ey2)])
        set_("eye_r", [(121, ey1), (135, ey2)])
        st = "hidden" if self.blinking else "normal"
        c.itemconfigure(it["hl_l"], state=st)
        c.itemconfigure(it["hl_r"], state=st)
        set_("hl_l", [(88, 162 + b), (93, 167 + b)])
        set_("hl_r", [(124, 162 + b), (129, 167 + b)])

        set_("blush_l", [(66, 182 + b), (88, 194 + b)])
        set_("blush_r", [(132, 182 + b), (154, 194 + b)])
        set_("nose", [(106, 184 + b), (114, 184 + b), (110, 189 + b)])

        speaking = self.talking and (self.frame // 5) % 2 == 0
        c.itemconfigure(it["mouth"], state="hidden" if speaking else "normal")
        c.itemconfigure(it["mouth_open"], state="normal" if speaking else "hidden")
        set_("mouth", [(101, 194 + b), (110, 200 + b), (119, 194 + b)])
        set_("mouth_open", [(103, 192 + b), (117, 204 + b)])

        bst = "normal" if self.talking else "hidden"
        for k in ("b_bg", "b_tail", "b_text"):
            c.itemconfigure(it[k], state=bst)

    # ==================== 事件 ====================
    def _bind(self):
        c = self.canvas
        c.bind("<Button-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Button-3>", self._on_menu)

    def _on_press(self, e):
        self.dragging = True
        self._press = (e.x_root, e.y_root)
        self._win = (self.x, self.y)
        self._moved = 0
        self.mode = "idle"
        self.timer = random.randint(60, 150)

    def _on_drag(self, e):
        if not self.dragging:
            return
        dx = e.x_root - self._press[0]
        dy = e.y_root - self._press[1]
        self._moved = max(self._moved, abs(dx) + abs(dy))
        self.x = self._win[0] + dx
        self.y = self._win[1] + dy
        self.x = max(-20, min(self.x, self.sw - self.W + 20))
        self.y = max(-10, min(self.y, self.sh - self.H + 10))
        self.root.geometry(f"+{int(round(self.x))}+{int(round(self.y))}")

    def _on_release(self, e):
        if not self.dragging:
            return
        self.dragging = False
        if self._moved < 6:
            self.say(random.choice(CLICK_TALK))

    def _on_menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="说句话",   command=lambda: self.say(random.choice(CLICK_TALK)))
        m.add_command(label="走一走",   command=self.start_walk)
        m.add_command(label="休息一下", command=self.rest)
        m.add_separator()
        aware_txt = "应用感知：开" if self.app_aware else "应用感知：关"
        m.add_command(label=aware_txt,  command=self._toggle_aware)
        m.add_separator()
        m.add_command(label="退出",     command=self.root.destroy)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # ==================== 行为 ====================
    def say(self, text, dur=2.6):
        self.talking = True
        self.talk_until = time.time() + dur
        self.canvas.itemconfigure(self.it["b_text"], text=text)

    def _speak(self, text, dur=2.6):
        """应用感知专用：正在说话就不打断"""
        if self.talking:
            return
        self.say(text, dur)

    def start_walk(self):
        self.mode = "walk"
        self.facing = random.choice((-1, 1))
        self.timer = random.randint(90, 240)

    def rest(self):
        self.mode = "idle"
        self.timer = random.randint(120, 260)
        self.say("呼…休息一下～", 2.0)

    def _toggle_aware(self):
        self.app_aware = not self.app_aware
        if not self.app_aware:
            self.cur_app = None
        self.say("应用感知已" + ("开启" if self.app_aware else "关闭"), 1.8)

    # ---------- 应用感知核心 ----------
    def _poll_foreground(self):
        try:
            pid, exe, title = _get_foreground()
        except Exception:
            return
        if not exe:
            return
        if pid == self.my_pid:      # 焦点在自己身上（拖拽时可能发生），忽略
            return

        # explorer.exe 也可能是桌面，需要看标题来区分
        if exe == "explorer.exe" and title in ("", "Program Manager", "桌面"):
            exe = "desktop"

        rule = match_app(exe)
        if rule is None:
            self.cur_app = None
            return

        if self.cur_app is None or self.cur_app["exe"] != exe:
            # —— 切换到新应用 ——
            self.cur_app = {"exe": exe, "rule": rule, "since": time.time()}
            self.idle_cd = random.randint(300, 600)      # 首次说完后 ~13~27s 内不闲聊
            self._speak(random.choice(rule["first"]), 3.0)
        else:
            # —— 停留同一应用，偶尔闲聊 ——
            self.idle_cd -= CHECK_INTERVAL
            if self.idle_cd <= 0:
                self.idle_cd = random.randint(400, 800)
                idle_lines = rule.get("idle") or []
                if idle_lines and random.random() < 0.55:
                    self._speak(random.choice(idle_lines), 2.6)

    # ==================== 主循环 ====================
    def _update(self):
        self.frame += 1
        now = time.time()

        if self.talking and now > self.talk_until:
            self.talking = False

        if self.blinking:
            self.blink_left -= 1
            if self.blink_left <= 0:
                self.blinking = False
                self.blink_cd = random.randint(40, 140)
        else:
            self.blink_cd -= 1
            if self.blink_cd <= 0:
                self.blinking = True
                self.blink_left = 5

        if not self.dragging:
            self.timer -= 1
            if self.timer <= 0:
                if self.mode == "walk":
                    self.mode = "idle"
                    self.timer = random.randint(80, 220)
                else:
                    self.start_walk()
                    if random.random() < 0.3:
                        self._speak(random.choice(CHAT))

        if self.mode == "walk" and not self.dragging:
            self.x += WALK_SPEED * self.facing
            if self.x < 0:
                self.x = 0
                self.facing = 1
            elif self.x > self.sw - self.W:
                self.x = self.sw - self.W
                self.facing = -1
            self.root.geometry(f"+{int(round(self.x))}+{int(round(self.y))}")
            self.phase += 0.38
        else:
            self.phase += 0.09

        # ---- 应用感知轮询 ----
        if self.app_aware:
            self._check_cd -= 1
            if self._check_cd <= 0:
                self._check_cd = CHECK_INTERVAL
                self._poll_foreground()

        self._render()

    def _tick(self):
        try:
            self._update()
        except Exception:
            if not self._err_shown:
                self._err_shown = True
                traceback.print_exc()
        finally:
            self.root.after(FPS_MS, self._tick)

    def run(self):
        self._tick()
        self.root.mainloop()


if __name__ == "__main__":
    DesktopPet().run()