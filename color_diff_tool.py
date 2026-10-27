"""
三色灯色差分析工具 v2.0
图形界面：加载两张图片（样品 vs 对标品），支持圆形点采样和矩形框选采样
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk


# ── 色彩空间转换 ──────────────────────────────────────────────

def rgb_to_lab(rgb):
    rgb_norm = np.array(rgb, dtype=float) / 255.0
    mask = rgb_norm > 0.04045
    rgb_lin = np.where(mask, ((rgb_norm + 0.055) / 1.055) ** 2.4, rgb_norm / 12.92)
    M = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ])
    xyz = rgb_lin @ M.T
    Xn, Yn, Zn = 0.95047, 1.00000, 1.08883
    xyz_norm = np.array([xyz[..., 0] / Xn, xyz[..., 1] / Yn, xyz[..., 2] / Zn])
    delta = 6 / 29
    f = np.where(xyz_norm > delta**3, xyz_norm ** (1/3), xyz_norm / (3 * delta**2) + 4/29)
    L = 116 * f[1] - 16
    a = 500 * (f[0] - f[1])
    b = 200 * (f[1] - f[2])
    return float(L), float(a), float(b)


def delta_e_cie2000(lab1, lab2):
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1 = np.sqrt(a1**2 + b1**2)
    C2 = np.sqrt(a2**2 + b2**2)
    C_mean = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(C_mean**7 / (C_mean**7 + 25**7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p = np.sqrt(a1p**2 + b1**2)
    C2p = np.sqrt(a2p**2 + b2**2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2))
    Lp_mean = (L1 + L2) / 2
    Cp_mean = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hp_mean = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_mean = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hp_mean = (h1p + h2p + 360) / 2
    else:
        hp_mean = (h1p + h2p - 360) / 2
    T = (1 - 0.17 * np.cos(np.radians(hp_mean - 30))
         + 0.24 * np.cos(np.radians(2 * hp_mean))
         + 0.32 * np.cos(np.radians(3 * hp_mean + 6))
         - 0.20 * np.cos(np.radians(4 * hp_mean - 63)))
    SL = 1 + 0.015 * (Lp_mean - 50)**2 / np.sqrt(20 + (Lp_mean - 50)**2)
    SC = 1 + 0.045 * Cp_mean
    SH = 1 + 0.015 * Cp_mean * T
    RT = (-2 * np.sqrt(Cp_mean**7 / (Cp_mean**7 + 25**7))
          * np.sin(np.radians(60 * np.exp(-((hp_mean - 275) / 25)**2))))
    de = np.sqrt((dLp / SL)**2 + (dCp / SC)**2 + (dHp / SH)**2
                 + RT * (dCp / SC) * (dHp / SH))
    return float(de)


def get_evaluation(de):
    if de < 1:
        return "人眼几乎无法察觉差异（优秀）", "#00AA00"
    elif de < 2:
        return "人眼难以察觉差异（良好）", "#44BB44"
    elif de < 3.5:
        return "人眼可察觉轻微差异（可接受）", "#AAAA00"
    elif de < 5:
        return "人眼明显可察觉差异（需注意）", "#DD8800"
    elif de < 10:
        return "人眼明显看到不同颜色（差异较大）", "#DD4400"
    else:
        return "完全不同的颜色（差异很大）", "#CC0000"


# ── 主界面 ────────────────────────────────────────────────────

class ColorDiffApp:
    def __init__(self, root):
        self.root = root
        self.root.title("三色灯色差分析工具 v2.0")
        self.root.geometry("1300x850")
        self.root.configure(bg="#f0f0f0")

        self.img_left = None
        self.img_right = None
        self.img_left_cv = None
        self.img_right_cv = None

        self.sample_rgb = None
        self.ref_rgb = None

        # 采样模式: "circle" 或 "rect"
        self.sample_mode = tk.StringVar(value="circle")
        # 框选拖拽状态
        self._drag_start = None
        self._drag_side = None

        self._build_ui()

    def _build_ui(self):
        # ── 顶部工具栏 ──
        toolbar = ttk.Frame(self.root, padding=5)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="加载样品图片（左）", command=lambda: self._load_image("left")).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="加载对标品图片（右）", command=lambda: self._load_image("right")).pack(side=tk.LEFT, padx=3)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        # 采样模式切换
        ttk.Label(toolbar, text="采样模式:").pack(side=tk.LEFT)
        mode_frame = ttk.Frame(toolbar)
        mode_frame.pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="圆形点击", variable=self.sample_mode, value="circle",
                        command=self._on_mode_change).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(mode_frame, text="矩形框选", variable=self.sample_mode, value="rect",
                        command=self._on_mode_change).pack(side=tk.LEFT, padx=2)

        ttk.Label(toolbar, text="圆半径:").pack(side=tk.LEFT, padx=(10, 0))
        self.radius_var = tk.IntVar(value=15)
        self.radius_spin = ttk.Spinbox(toolbar, from_=3, to=100, textvariable=self.radius_var, width=5)
        self.radius_spin.pack(side=tk.LEFT, padx=3)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(toolbar, text="自动检测两灯并分析", command=self._auto_analyze).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="清除结果", command=self._clear_results).pack(side=tk.LEFT, padx=5)

        # ── 图片显示区 ──
        img_frame = ttk.Frame(self.root)
        img_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_frame = ttk.LabelFrame(img_frame, text="样品", padding=5)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        self.left_mode_label = ttk.Label(left_frame, text="[模式: 圆形点击]", foreground="#666")
        self.left_mode_label.pack(anchor=tk.W)
        self.left_canvas = tk.Canvas(left_frame, bg="#333333")
        self.left_canvas.pack(fill=tk.BOTH, expand=True)
        # 圆形模式: 点击采样;  矩形模式: 左键按下拖拽
        self.left_canvas.bind("<Button-1>", lambda e: self._on_canvas_press(e, "left"))
        self.left_canvas.bind("<B1-Motion>", lambda e: self._on_canvas_drag(e, "left"))
        self.left_canvas.bind("<ButtonRelease-1>", lambda e: self._on_canvas_release(e, "left"))
        # 右键: 框选模式下清除选框
        self.left_canvas.bind("<Button-3>", lambda e: self._on_right_click(e, "left"))

        right_frame = ttk.LabelFrame(img_frame, text="对标品", padding=5)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=2)
        self.right_mode_label = ttk.Label(right_frame, text="[模式: 圆形点击]", foreground="#666")
        self.right_mode_label.pack(anchor=tk.W)
        self.right_canvas = tk.Canvas(right_frame, bg="#333333")
        self.right_canvas.pack(fill=tk.BOTH, expand=True)
        self.right_canvas.bind("<Button-1>", lambda e: self._on_canvas_press(e, "right"))
        self.right_canvas.bind("<B1-Motion>", lambda e: self._on_canvas_drag(e, "right"))
        self.right_canvas.bind("<ButtonRelease-1>", lambda e: self._on_canvas_release(e, "right"))
        self.right_canvas.bind("<Button-3>", lambda e: self._on_right_click(e, "right"))

        # ── 底部结果区 ──
        result_frame = ttk.LabelFrame(self.root, text="分析结果", padding=10)
        result_frame.pack(fill=tk.X, padx=5, pady=5)

        info_frame = ttk.Frame(result_frame)
        info_frame.pack(fill=tk.X)

        # 样品颜色
        sample_frame = ttk.Frame(info_frame)
        sample_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.sample_swatch = tk.Canvas(sample_frame, width=60, height=60, bg="#888888", highlightthickness=2)
        self.sample_swatch.pack(side=tk.LEFT, padx=5)
        ttk.Label(sample_frame, text="样品颜色", font=("", 10, "bold")).pack()
        self.sample_rgb_label = ttk.Label(sample_frame, text="RGB: ---", font=("Consolas", 10))
        self.sample_rgb_label.pack()
        self.sample_lab_label = ttk.Label(sample_frame, text="LAB: ---", font=("Consolas", 10))
        self.sample_lab_label.pack()

        ttk.Label(info_frame, text="  <->  ", font=("", 14)).pack(side=tk.LEFT)

        # 对标品颜色
        ref_frame = ttk.Frame(info_frame)
        ref_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.ref_swatch = tk.Canvas(ref_frame, width=60, height=60, bg="#888888", highlightthickness=2)
        self.ref_swatch.pack(side=tk.LEFT, padx=5)
        ttk.Label(ref_frame, text="对标品颜色", font=("", 10, "bold")).pack()
        self.ref_rgb_label = ttk.Label(ref_frame, text="RGB: ---", font=("Consolas", 10))
        self.ref_rgb_label.pack()
        self.ref_lab_label = ttk.Label(ref_frame, text="LAB: ---", font=("Consolas", 10))
        self.ref_lab_label.pack()

        # 色差结果
        de_frame = ttk.Frame(result_frame)
        de_frame.pack(fill=tk.X, pady=(10, 0))

        self.de_label = ttk.Label(de_frame, text="Delta E (CIE 2000): ---", font=("", 14, "bold"))
        self.de_label.pack(side=tk.LEFT, padx=20)

        self.eval_label = ttk.Label(de_frame, text="", font=("", 12))
        self.eval_label.pack(side=tk.LEFT, padx=10)

        self.region_info_label = ttk.Label(result_frame, text="", font=("Consolas", 9), foreground="#888888")
        self.region_info_label.pack(anchor=tk.W, pady=(5, 0))

        self.detail_label = ttk.Label(result_frame, text="", font=("Consolas", 9), foreground="#666666")
        self.detail_label.pack(anchor=tk.W)

        # ── 历史记录 ──
        history_frame = ttk.LabelFrame(self.root, text="历史记录", padding=5)
        history_frame.pack(fill=tk.X, padx=5, pady=5)

        self.history_tree = ttk.Treeview(history_frame,
                                         columns=("模式", "样品", "对标品", "DeltaE", "评价"),
                                         show="headings", height=4)
        self.history_tree.heading("模式", text="采样模式")
        self.history_tree.heading("样品", text="样品 RGB")
        self.history_tree.heading("对标品", text="对标品 RGB")
        self.history_tree.heading("DeltaE", text="Delta E")
        self.history_tree.heading("评价", text="评价")
        self.history_tree.column("模式", width=80)
        self.history_tree.column("样品", width=140)
        self.history_tree.column("对标品", width=140)
        self.history_tree.column("DeltaE", width=70)
        self.history_tree.column("评价", width=220)
        self.history_tree.pack(fill=tk.X)

    def _on_mode_change(self):
        mode = self.sample_mode.get()
        hint = "[模式: 圆形点击]" if mode == "circle" else "[模式: 矩形框选 (右键取消)]"
        self.left_mode_label.config(text=hint)
        self.right_mode_label.config(text=hint)

    # ── 图片加载 ──────────────────────────────────────────────

    def _load_image(self, side):
        path = filedialog.askopenfilename(
            title=f"选择{'样品' if side == 'left' else '对标品'}图片",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"), ("所有文件", "*.*")]
        )
        if not path:
            return
        pil_img = Image.open(path).convert("RGB")
        cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        if side == "left":
            self.img_left = pil_img
            self.img_left_cv = cv_img
            self._display_image(self.left_canvas, pil_img)
        else:
            self.img_right = pil_img
            self.img_right_cv = cv_img
            self._display_image(self.right_canvas, pil_img)

    def _display_image(self, canvas, pil_img):
        canvas.update_idletasks()
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw < 10 or ch < 10:
            cw, ch = 500, 400
        iw, ih = pil_img.size
        scale = min(cw / iw, ch / ih, 1.0)
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
        resized = pil_img.resize((nw, nh), Image.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(resized)
        canvas.delete("all")
        canvas.create_image(cw // 2, ch // 2, image=self._tk_img, anchor=tk.CENTER)
        canvas.image_ref = self._tk_img
        canvas._scale = scale
        canvas._offset_x = (cw - nw) // 2
        canvas._offset_y = (ch - nh) // 2
        canvas._orig_size = (iw, ih)

    def _canvas_to_image_coords(self, canvas, event):
        scale = canvas._scale
        ox = canvas._offset_x
        oy = canvas._offset_y
        x = int((event.x - ox) / scale)
        y = int((event.y - oy) / scale)
        iw, ih = canvas._orig_size
        return max(0, min(x, iw - 1)), max(0, min(y, ih - 1))

    def _image_to_canvas_coords(self, canvas, ix, iy):
        scale = canvas._scale
        ox = canvas._offset_x
        oy = canvas._offset_y
        return int(ix * scale) + ox, int(iy * scale) + oy

    # ── 鼠标事件 ──────────────────────────────────────────────

    def _on_canvas_press(self, event, side):
        mode = self.sample_mode.get()
        if mode == "circle":
            self._do_circle_sample(event, side)
        else:
            # 矩形框选开始
            canvas = self.left_canvas if side == "left" else self.right_canvas
            cv_img = self.img_left_cv if side == "left" else self.img_right_cv
            if cv_img is None:
                return
            self._drag_start = self._canvas_to_image_coords(canvas, event)
            self._drag_side = side
            # 清除旧选框
            canvas.delete("rect_marker")

    def _on_canvas_drag(self, event, side):
        if self._drag_start is None or side != self._drag_side:
            return
        canvas = self.left_canvas if side == "left" else self.right_canvas
        # 实时绘制虚线矩形
        x1, y1 = self._image_to_canvas_coords(canvas, self._drag_start[0], self._drag_start[1])
        x2, y2 = self._image_to_canvas_coords(canvas, *self._canvas_to_image_coords(canvas, event))
        canvas.delete("rect_marker")
        canvas.create_rectangle(x1, y1, x2, y2, outline="yellow", width=2, dash=(5, 3), tags="rect_marker")

    def _on_canvas_release(self, event, side):
        if self._drag_start is None:
            return
        canvas = self.left_canvas if side == "left" else self.right_canvas
        end = self._canvas_to_image_coords(canvas, event)
        x1 = min(self._drag_start[0], end[0])
        y1 = min(self._drag_start[1], end[1])
        x2 = max(self._drag_start[0], end[0])
        y2 = max(self._drag_start[1], end[1])

        # 框太小（<5px）忽略
        if (x2 - x1) < 5 or (y2 - y1) < 5:
            self._drag_start = None
            self._drag_side = None
            canvas.delete("rect_marker")
            return

        self._do_rect_sample(x1, y1, x2, y2, side)
        self._drag_start = None
        self._drag_side = None

    def _on_right_click(self, event, side):
        """右键清除选框"""
        canvas = self.left_canvas if side == "left" else self.right_canvas
        canvas.delete("rect_marker")
        self._drag_start = None

    # ── 采样逻辑 ──────────────────────────────────────────────

    def _do_circle_sample(self, event, side):
        if side == "left" and self.img_left_cv is None:
            messagebox.showinfo("提示", "请先加载样品图片")
            return
        if side == "right" and self.img_right_cv is None:
            messagebox.showinfo("提示", "请先加载对标品图片")
            return

        canvas = self.left_canvas if side == "left" else self.right_canvas
        cv_img = self.img_left_cv if side == "left" else self.img_right_cv
        x, y = self._canvas_to_image_coords(canvas, event)
        radius = self.radius_var.get()

        # 圆形 mask 采样
        h, w = cv_img.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(mask, (x, y), radius, 255, -1)
        pixels = cv_img[mask == 255]
        if len(pixels) == 0:
            return
        avg_bgr = np.mean(pixels, axis=0)
        rgb = (int(avg_bgr[2]), int(avg_bgr[1]), int(avg_bgr[0]))

        # 画圆形标记
        canvas.delete("sample_marker", "rect_marker")
        c1, c2 = self._image_to_canvas_coords(canvas, x, y)
        r = max(1, int(radius * canvas._scale))
        canvas.create_oval(c1 - r, c2 - r, c1 + r, c2 + r, outline="white", width=2, tags="sample_marker")
        canvas.create_oval(c1 - r - 3, c2 - r - 3, c1 + r + 3, c2 + r + 3, outline="yellow", width=1, tags="sample_marker")

        self._update_color(side, rgb, f"圆形(r={radius}, {len(pixels)}px)")

    def _do_rect_sample(self, x1, y1, x2, y2, side):
        canvas = self.left_canvas if side == "left" else self.right_canvas
        cv_img = self.img_left_cv if side == "left" else self.img_right_cv

        # 矩形区域所有像素
        crop = cv_img[y1:y2, x1:x2]
        if crop.size == 0:
            return
        pixels = crop.reshape(-1, 3)
        avg_bgr = np.mean(pixels, axis=0)
        rgb = (int(avg_bgr[2]), int(avg_bgr[1]), int(avg_bgr[0]))

        # 画矩形标记
        canvas.delete("sample_marker", "rect_marker")
        c1, c2 = self._image_to_canvas_coords(canvas, x1, y1)
        c3, c4 = self._image_to_canvas_coords(canvas, x2, y2)
        canvas.create_rectangle(c1, c2, c3, c4, outline="#00FF00", width=2, tags="sample_marker")
        canvas.create_text(c1 + 5, c2 + 5, anchor=tk.NW, text=f"{x2-x1}x{y2-y1}",
                           fill="#00FF00", font=("", 8), tags="sample_marker")

        count = (x2 - x1) * (y2 - y1)
        self._update_color(side, rgb, f"矩形({x2-x1}x{y2-y1}, {count}px)")

    def _update_color(self, side, rgb, region_desc):
        if side == "left":
            self.sample_rgb = rgb
            self._update_swatch(self.sample_swatch, rgb)
            self.sample_rgb_label.config(text=f"RGB: ({rgb[0]}, {rgb[1]}, {rgb[2]})")
            lab = rgb_to_lab(rgb)
            self.sample_lab_label.config(text=f"LAB: ({lab[0]:.1f}, {lab[1]:.1f}, {lab[2]:.1f})")
        else:
            self.ref_rgb = rgb
            self._update_swatch(self.ref_swatch, rgb)
            self.ref_rgb_label.config(text=f"RGB: ({rgb[0]}, {rgb[1]}, {rgb[2]})")
            lab = rgb_to_lab(rgb)
            self.ref_lab_label.config(text=f"LAB: ({lab[0]:.1f}, {lab[1]:.1f}, {lab[2]:.1f})")

        self.region_info_label.config(text=f"采样区域: {region_desc}")

        if self.sample_rgb and self.ref_rgb:
            self._calc_diff(region_desc)

    def _update_swatch(self, canvas, rgb):
        color = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        canvas.configure(bg=color)

    def _calc_diff(self, region_desc=""):
        if self.sample_rgb is None or self.ref_rgb is None:
            return
        lab1 = rgb_to_lab(self.sample_rgb)
        lab2 = rgb_to_lab(self.ref_rgb)
        de = delta_e_cie2000(lab1, lab2)
        eval_text, eval_color = get_evaluation(de)

        self.de_label.config(text=f"Delta E (CIE 2000): {de:.2f}")
        self.eval_label.config(text=eval_text, foreground=eval_color)

        dr = abs(self.sample_rgb[0] - self.ref_rgb[0])
        dg = abs(self.sample_rgb[1] - self.ref_rgb[1])
        db = abs(self.sample_rgb[2] - self.ref_rgb[2])
        lum1 = 0.299 * self.sample_rgb[0] + 0.587 * self.sample_rgb[1] + 0.114 * self.sample_rgb[2]
        lum2 = 0.299 * self.ref_rgb[0] + 0.587 * self.ref_rgb[1] + 0.114 * self.ref_rgb[2]

        self.detail_label.config(
            text=f"RGB差异: R={dr}, G={dg}, B={db}  |  "
                 f"亮度: 样品={lum1:.1f}, 对标品={lum2:.1f}, 差异={abs(lum1 - lum2):.1f}  |  "
                 f"LAB差异: dL={abs(lab1[0]-lab2[0]):.1f}, da={abs(lab1[1]-lab2[1]):.1f}, db={abs(lab1[2]-lab2[2]):.1f}"
        )

        mode = "矩形框选" if self.sample_mode.get() == "rect" else "圆形点击"
        status = "OK" if de < 3.5 else "WARNING" if de < 5 else "FAIL"
        self.history_tree.insert("", tk.END, values=(
            mode,
            f"({self.sample_rgb[0]},{self.sample_rgb[1]},{self.sample_rgb[2]})",
            f"({self.ref_rgb[0]},{self.ref_rgb[1]},{self.ref_rgb[2]})",
            f"{de:.2f}",
            f"{eval_text} [{status}]"
        ))

    # ── 自动分析 ──────────────────────────────────────────────

    def _auto_analyze(self):
        if self.img_left_cv is None or self.img_right_cv is None:
            messagebox.showinfo("提示", "请先加载两张图片")
            return
        self._auto_analyze_one("left", self.img_left_cv)
        self._auto_analyze_one("right", self.img_right_cv)
        if self.sample_rgb and self.ref_rgb:
            self._calc_diff("[自动]")

    def _auto_analyze_one(self, side, cv_img):
        h, w = cv_img.shape[:2]
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        threshold = np.percentile(gray, 85)
        bright_mask = (gray >= threshold).astype(np.uint8)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(bright_mask)

        components = []
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area > 500:
                components.append({
                    'centroid': (int(centroids[i][0]), int(centroids[i][1])),
                    'bbox': (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                             stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]),
                    'area': area
                })

        components.sort(key=lambda c: c['area'], reverse=True)

        if len(components) >= 2:
            components.sort(key=lambda c: c['centroid'][0])
            if abs(components[0]['centroid'][0] - components[1]['centroid'][0]) <= 30:
                c = components[0]
                x, y, bw, bh = c['bbox']
                cy = c['centroid'][1]
                components = [
                    {'centroid': (x + bw // 4, cy), 'bbox': (x, y, bw // 2, bh), 'area': c['area'] // 2},
                    {'centroid': (x + 3 * bw // 4, cy), 'bbox': (x + bw // 2, y, bw - bw // 2, bh), 'area': c['area'] // 2},
                ]
        elif len(components) == 1:
            c = components[0]
            x, y, bw, bh = c['bbox']
            cy = c['centroid'][1]
            components = [
                {'centroid': (x + bw // 4, cy), 'bbox': (x, y, bw // 2, bh), 'area': c['area'] // 2},
                {'centroid': (x + 3 * bw // 4, cy), 'bbox': (x + bw // 2, y, bw - bw // 2, bh), 'area': c['area'] // 2},
            ]
        else:
            return

        hsv = cv2.cvtColor(cv_img, cv2.COLOR_BGR2HSV)
        colors = []
        for comp in components[:2]:
            x, y, bw, bh = comp['bbox']
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(w, x + bw), min(h, y + bh)
            crop_bgr = cv_img[y1:y2, x1:x2]
            crop_hsv = hsv[y1:y2, x1:x2]
            s_ch = crop_hsv[..., 1]
            v_ch = crop_hsv[..., 2]
            valid = ~((v_ch > 240) & (s_ch < 30)) & (v_ch > 30)
            pixels = crop_bgr[valid]
            if len(pixels) > 0:
                avg = np.median(pixels, axis=0)
                colors.append((int(avg[2]), int(avg[1]), int(avg[0])))

        if not colors:
            return

        avg_rgb = tuple(int(np.mean([c[i] for c in colors])) for i in range(3))
        if side == "left":
            self.sample_rgb = avg_rgb
            self._update_swatch(self.sample_swatch, avg_rgb)
            self.sample_rgb_label.config(text=f"RGB: ({avg_rgb[0]}, {avg_rgb[1]}, {avg_rgb[2]})  [自动]")
            lab = rgb_to_lab(avg_rgb)
            self.sample_lab_label.config(text=f"LAB: ({lab[0]:.1f}, {lab[1]:.1f}, {lab[2]:.1f})")
        else:
            self.ref_rgb = avg_rgb
            self._update_swatch(self.ref_swatch, avg_rgb)
            self.ref_rgb_label.config(text=f"RGB: ({avg_rgb[0]}, {avg_rgb[1]}, {avg_rgb[2]})  [自动]")
            lab = rgb_to_lab(avg_rgb)
            self.ref_lab_label.config(text=f"LAB: ({lab[0]:.1f}, {lab[1]:.1f}, {lab[2]:.1f})")

    # ── 清除 ──────────────────────────────────────────────────

    def _clear_results(self):
        self.sample_rgb = None
        self.ref_rgb = None
        self.sample_swatch.configure(bg="#888888")
        self.ref_swatch.configure(bg="#888888")
        self.sample_rgb_label.config(text="RGB: ---")
        self.sample_lab_label.config(text="LAB: ---")
        self.ref_rgb_label.config(text="RGB: ---")
        self.ref_lab_label.config(text="LAB: ---")
        self.de_label.config(text="Delta E (CIE 2000): ---")
        self.eval_label.config(text="")
        self.region_info_label.config(text="")
        self.detail_label.config(text="")
        self.left_canvas.delete("sample_marker", "rect_marker")
        self.right_canvas.delete("sample_marker", "rect_marker")
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)


def main():
    root = tk.Tk()
    ColorDiffApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
