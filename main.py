#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面小宠物（纯 tkinter 实现，无第三方依赖）—— 修复版

修复：
  1) 浮点坐标导致 wm_geometry 报 "bad geometry specifier"，进而让动画循环崩溃
     → 所有 geometry 参数统一取整
  2) 右键菜单 emoji 超出 Tcl 的 BMP 范围（U+0000~U+FFFF）
     → 菜单改为纯文本
  3) _tick 加 try/finally，单帧异常不会终止动画
"""

import math
import random
import platform
import time
import traceback
import tkinter as tk

# ---------------- 配置 ----------------
TRANS = "#FF00FE"              # Windows 透明色
FONT = ("Microsoft YaHei", 11)
FPS_MS = 45                    # 每帧毫秒数
WALK_SPEED = 3.2               # 走动速度 px/帧（浮点，累加后统一取整）

CLICK_TALK = [
    "哎呀，别戳我～",
    "痒痒的！",
    "你好呀！",
    "在呢在呢～",
    "要摸摸头吗？",
    "嘿！我在工作呢～",
]
CHAT = [
    "今天也要加油哦！",
    "记得喝水呀～",
    "坐久了要起来动一动",
    "我陪你一起～",
    "嘿嘿～",
    "天气怎么样呀？",
]


class DesktopPet:
    W, H = 220, 250
    CX = 110

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        bg = TRANS
        if platform.system() == "Windows":
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
        # 注意：初始也用 int，和后续保持一致
        self.root.geometry(f"{self.W}x{self.H}+{int(self.x)}+{int(self.y)}")

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H,
                                bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack()

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
        self._err_shown = False   # 防止异常刷屏

        self._build()
        self._bind()

    # ==================== 绘制图元 ====================
    def _build(self):
        c = self.canvas
        it = self.it = {}

        OUT = "#C98A3E"
        BODY = "#FFC97A"
        INNER = "#FF9B9B"
        EYE = "#3A2A20"
        BLUSH = "#FFA6B8"

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

    # ==================== 渲染 ====================
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
        # 注意：拖动时 x/y 可能是浮点（因为走动把 self.x 变成了浮点），
        # 先算好再统一取整
        self.x = self._win[0] + dx
        self.y = self._win[1] + dy
        self.x = max(-20, min(self.x, self.sw - self.W + 20))
        self.y = max(-10, min(self.y, self.sh - self.H + 10))
        # ★ 关键修复：geometry 只接受整数
        self.root.geometry(f"+{int(round(self.x))}+{int(round(self.y))}")

    def _on_release(self, e):
        if not self.dragging:
            return
        self.dragging = False
        if self._moved < 6:
            self.say(random.choice(CLICK_TALK))

    def _on_menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        # ★ 关键修复：去掉 emoji（U+1F4AC 等超出 Tcl BMP 范围）
        m.add_command(label="说句话",   command=lambda: self.say(random.choice(CLICK_TALK)))
        m.add_command(label="走一走",   command=self.start_walk)
        m.add_command(label="休息一下", command=self.rest)
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

    def start_walk(self):
        self.mode = "walk"
        self.facing = random.choice((-1, 1))
        self.timer = random.randint(90, 240)

    def rest(self):
        self.mode = "idle"
        self.timer = random.randint(120, 260)
        self.say("呼…休息一下～", 2.0)

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
                        self.say(random.choice(CHAT))

        if self.mode == "walk" and not self.dragging:
            self.x += WALK_SPEED * self.facing
            if self.x < 0:
                self.x = 0
                self.facing = 1
            elif self.x > self.sw - self.W:
                self.x = self.sw - self.W
                self.facing = -1
            # ★ 关键修复：int 化，避免 "bad geometry specifier"
            self.root.geometry(f"+{int(round(self.x))}+{int(round(self.y))}")
            self.phase += 0.38
        else:
            self.phase += 0.09

        self._render()

    def _tick(self):
        # ★ 关键修复：即使单帧出现异常，动画也能继续，宠物不会卡死
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