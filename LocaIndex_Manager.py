import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import csv, os, math, json, unicodedata
from PIL import Image, ImageTk, ImageDraw, ImageFont
from io import BytesIO

# 定数（緯度は -90～90、経度は -180～180）
LAT_MIN, LAT_MAX = -90, 90
LON_MIN, LON_MAX = -180, 180

STATE_FILE = "app_state.json"
DEFAULT_FONT_PATH = "meiryo.ttc"  # デフォルトフォントパス
DEFAULT_PIN_COLOR = "blue"         # デフォルトピンの色
PIN_COLORS = ["black", "red", "blue", "green", "yellow", "purple", "orange"]
RESOLUTION_OPTIONS = {"1x": 1, "2x": 2, "3x": 3}

# --- 表示文字列の幅調整用ヘルパー関数 ---
def get_display_width(s):
    width = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width

def pad_string(s, target_width):
    current = get_display_width(s)
    if current >= target_width:
        return s
    else:
        return s + " " * (target_width - current)

def format_pin_entry(name, distance):
    margin = "  "  # 左余白2スペース
    target_name_width = 20  # 名前部分の固定幅（半角換算）
    padded_name = pad_string(name, target_name_width)
    # 距離は右寄せで、末尾に " km" を付与。全体を12文字幅に揃える
    distance_str = f"{distance:.1f} km"
    target_distance_width = 12
    distance_padded = distance_str.rjust(target_distance_width)
    return margin + padded_name + distance_padded

# --- メインアプリ ---
class MapMakerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LocaIndex_Manager")
        self.root.resizable(False, False)

        # キャンバスサイズ＋マージン設定
        self.canvas_width = 1200
        self.canvas_height = 750
        self.margin_left = 40
        self.margin_right = 40
        self.margin_top = 40
        self.margin_bottom = 40
        self.eff_width = self.canvas_width - self.margin_left - self.margin_right
        self.eff_height = self.canvas_height - self.margin_top - self.margin_bottom

        self.offset_x = 0
        self.pins = []  # 各ピン: {"lat", "lon", "name", "remark", "color", marker_id, text_id}
        self.current_file = ""
        self.editing_pin = None
        self.editing_mode = False
        self.resolution_multiplier = 1

        # 背景画像関連
        self.bg_image_original = None  # PIL Image（透明度未適用）
        self.bg_image = None           # ImageTk.PhotoImage（透明度適用済み）

        # フォント設定
        self.font = self.load_font()
        self.create_widgets()
        self.load_state()  # STATE_FILEから状態読み込み（任意）
        self.load_bg_image_from_folder()
        self.draw_map()
        self.drag_start = None

    def load_font(self):
        try:
            return ImageFont.truetype(DEFAULT_FONT_PATH, 16)
        except IOError:
            messagebox.showerror("エラー", f"フォントファイル {DEFAULT_FONT_PATH} が見つかりません。デフォルトフォントを使用します。")
            return ImageFont.load_default()

    def create_widgets(self):
        top_frame = ttk.Frame(self.root)
        top_frame.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(top_frame, text="マップデータを開く", command=self.load_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="保存", command=self.save_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="保存して閉じる", command=self.save_and_close).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="背景画像設定", command=self.set_bg_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="背景画像削除", command=self.clear_bg_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="新しいマップ", command=self.create_new_map).pack(side=tk.LEFT, padx=5)
        ttk.Label(top_frame, text="マップ名:").pack(side=tk.LEFT, padx=5)
        self.map_name_entry = ttk.Entry(top_frame, width=15)
        self.map_name_entry.pack(side=tk.LEFT)
        self.map_name_entry.insert(0, "my_map")

        # 解像度選択コンボボックス
        ttk.Label(top_frame, text="出力解像度:").pack(side=tk.LEFT, padx=5)
        self.resolution_var = tk.StringVar(value="1x")
        self.resolution_combo = ttk.Combobox(top_frame, textvariable=self.resolution_var, values=list(RESOLUTION_OPTIONS.keys()), width=5)
        self.resolution_combo.pack(side=tk.LEFT, padx=5)
        self.resolution_combo.bind("<<ComboboxSelected>>", self.on_resolution_change)

        ttk.Button(top_frame, text="画像生成", command=self.export_image).pack(side=tk.LEFT, padx=5)

        # 大圏航路表示トグルボタン
        self.gc_route_mode = 0  # 0: 表示なし, 1: 全ピンへの大圏航路表示
        self.gc_route_button = ttk.Button(top_frame, text="大圏航路表示: 無効", command=self.toggle_gc_route)
        self.gc_route_button.pack(side=tk.LEFT, padx=5)

        # 中央領域：キャンバス＋右側パネル
        center_frame = ttk.Frame(self.root)
        center_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(center_frame, width=self.canvas_width, height=self.canvas_height, bg="white")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Button-3>", self.on_pin_click)

        self.detail_panel = ttk.Frame(center_frame, relief=tk.SUNKEN, padding=5)
        self.detail_panel.pack(side=tk.RIGHT, fill=tk.Y)

        # ★ 星の直径 (km) 設定ウィジェット
        star_frame = ttk.Frame(self.detail_panel)
        star_frame.pack(anchor="nw", pady=(0, 5))
        ttk.Label(star_frame, text="星の直径 (km):").pack(side=tk.LEFT)
        self.star_diameter = tk.DoubleVar(value=12742.0)
        self.star_entry = ttk.Entry(star_frame, textvariable=self.star_diameter, width=10)
        self.star_entry.pack(side=tk.LEFT, padx=5)

        # ★ 背景画像透明度 (%) 設定ウィジェット
        trans_frame = ttk.Frame(self.detail_panel)
        trans_frame.pack(anchor="nw", pady=(0, 5))
        ttk.Label(trans_frame, text="背景透明度 (%):").pack(side=tk.LEFT)
        self.bg_alpha = tk.DoubleVar(value=100.0)
        self.bg_alpha_entry = ttk.Entry(trans_frame, textvariable=self.bg_alpha, width=10)
        self.bg_alpha_entry.pack(side=tk.LEFT, padx=5)
        # 入力欄の右にスライダーを追加（0～100の範囲）
        self.bg_alpha_slider = ttk.Scale(trans_frame, from_=0, to=100, orient=tk.HORIZONTAL,
                                         variable=self.bg_alpha, command=lambda v: self.draw_map())
        self.bg_alpha_slider.pack(side=tk.LEFT, padx=5)
        # 変数が変化したら背景再描画
        self.bg_alpha.trace("w", lambda *args: self.draw_map())

        ttk.Label(self.detail_panel, text="ピン一覧").pack(anchor="nw")
        self.pin_listbox = tk.Listbox(self.detail_panel, height=25, font=("ＭＳ ゴシック", 10))
        self.pin_listbox.pack(fill=tk.X, pady=2)
        self.pin_listbox.bind("<<ListboxSelect>>", self.on_pin_list_select)
        ttk.Label(self.detail_panel, text="ピン詳細").pack(anchor="nw", pady=(10, 0))
        self.detail_text = tk.Text(self.detail_panel, width=45, height=15, state="disabled")
        self.detail_text.pack(pady=5)
        button_frame = ttk.Frame(self.detail_panel)
        button_frame.pack(pady=5)
        self.edit_button = ttk.Button(button_frame, text="編集", command=self.edit_current_pin)
        self.edit_button.pack(side=tk.LEFT, padx=5)
        self.delete_button = ttk.Button(button_frame, text="削除", command=self.delete_current_pin)
        self.delete_button.pack(side=tk.LEFT, padx=5)
        # 編集・削除ボタンの下にマップ生成ボタンを配置
        lower_button_frame = ttk.Frame(self.detail_panel)
        lower_button_frame.pack(pady=5)
        self.map_gen_button = ttk.Button(lower_button_frame, text="正距方位図生成", command=self.export_azimuthal_map)
        self.map_gen_button.pack(side=tk.LEFT, padx=5)
        self.bg_edit_button = ttk.Button(lower_button_frame, text="背景画像編集", command=self.open_bg_paint_tool)
        self.bg_edit_button.pack(side=tk.LEFT, padx=5)


        self.edit_button.pack_forget()
        self.delete_button.pack_forget()
        self.current_pin = None

        # 下部：ピン作成／編集入力領域
        self.pin_frame = ttk.Frame(self.root, relief=tk.RIDGE, padding=5)
        self.pin_frame.pack(side=tk.BOTTOM, fill=tk.X)
        for i in range(4):
            self.pin_frame.columnconfigure(i, weight=1)
        self.pin_create_button = ttk.Button(self.pin_frame, text="ピン作成", command=self.show_pin_input_new)
        self.pin_create_button.grid(row=0, column=0, rowspan=4, padx=5, pady=5, sticky="n")
        col1_frame = ttk.Frame(self.pin_frame)
        col1_frame.grid(row=0, column=1, rowspan=4, sticky="n", padx=5)
        ttk.Label(col1_frame, text="緯度(°):").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.lat_var = tk.DoubleVar(value=0.0)
        self.lat_entry = ttk.Entry(col1_frame, textvariable=self.lat_var, width=20)
        self.lat_entry.grid(row=0, column=1, sticky="e", padx=2, pady=2)
        ttk.Label(col1_frame, text="経度(°):").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        self.lon_var = tk.DoubleVar(value=0.0)
        self.lon_entry = ttk.Entry(col1_frame, textvariable=self.lon_var, width=20)
        self.lon_entry.grid(row=1, column=1, sticky="e", padx=2, pady=2)
        ttk.Label(col1_frame, text="地名:").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(col1_frame, textvariable=self.name_var, width=20)
        self.name_entry.grid(row=2, column=1, sticky="e", padx=2, pady=2)
        ttk.Label(col1_frame, text="色:").grid(row=3, column=0, sticky="w", padx=2, pady=2)
        self.color_var = tk.StringVar(value=DEFAULT_PIN_COLOR)
        self.color_combo = ttk.Combobox(col1_frame, textvariable=self.color_var, values=PIN_COLORS, width=13)
        self.color_combo.grid(row=3, column=1, sticky="e", padx=2, pady=2)
        ttk.Label(self.pin_frame, text="備考:").grid(row=0, column=2, sticky="nw", padx=5, pady=2)
        self.remark_text = tk.Text(self.pin_frame, width=50, height=5)
        self.remark_text.grid(row=1, column=2, rowspan=3, sticky="n", padx=5, pady=2)
        ttk.Label(self.pin_frame, text="スライダー:").grid(row=0, column=3, sticky="w", padx=5, pady=2)
        self.lat_scale = ttk.Scale(self.pin_frame, from_=LAT_MIN, to=LAT_MAX,
                                   orient=tk.HORIZONTAL, length=600,
                                   variable=self.lat_var, command=lambda v: self.update_pin_preview())
        self.lat_scale.grid(row=1, column=3, padx=5, pady=5)
        self.lon_scale = ttk.Scale(self.pin_frame, from_=LON_MIN, to=LON_MAX,
                                   orient=tk.HORIZONTAL, length=600,
                                   variable=self.lon_var, command=lambda v: self.update_pin_preview())
        self.lon_scale.grid(row=2, column=3, padx=5, pady=5)
        button_frame_bottom = ttk.Frame(self.pin_frame)
        button_frame_bottom.grid(row=4, column=0, columnspan=4, pady=5)
        self.pin_action_button = ttk.Button(button_frame_bottom, text="作成", command=self.create_or_update_pin)
        self.pin_action_button.pack(side=tk.LEFT, padx=10)
        self.cancel_button = ttk.Button(button_frame_bottom, text="キャンセル", command=self.cancel_pin_input)
        self.cancel_button.pack(side=tk.LEFT, padx=10)
        self.set_pin_input_state("disabled")
        for var in (self.lat_var, self.lon_var, self.name_var):
            var.trace("w", lambda *args: self.update_pin_preview())

    def set_pin_input_state(self, state):
        self.lat_entry.config(state=state)
        self.lat_scale.config(state=state)
        self.lon_entry.config(state=state)
        self.lon_scale.config(state=state)
        self.name_entry.config(state=state)
        self.remark_text.config(state=state)
        self.color_combo.config(state=state)
        self.pin_action_button.config(state=state)
        self.cancel_button.config(state=state)
        bg = "#f0f0f0" if state == "disabled" else "white"
        for widget in (self.lat_entry, self.lon_entry, self.name_entry, self.remark_text, self.color_combo):
            widget.config(background=bg)

    def on_resolution_change(self, event):
        selected_resolution = self.resolution_var.get()
        self.resolution_multiplier = RESOLUTION_OPTIONS[selected_resolution]

    def lon_to_x(self, lon):
        relative = (lon - LON_MIN) / (LON_MAX - LON_MIN)
        x = self.margin_left + relative * self.eff_width + self.offset_x
        return x

    def lat_to_y(self, lat):
        relative = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN)
        y = self.margin_top + relative * self.eff_height
        return y

    def update_bg_image_with_alpha(self):
        if self.bg_image_original:
            try:
                alpha = self.bg_alpha.get() / 100.0
            except Exception:
                alpha = 1.0
            # PIL Image にアルファチャンネルを付与
            img = self.bg_image_original.copy().convert("RGBA")
            alpha_mask = Image.new("L", img.size, int(alpha * 255))
            img.putalpha(alpha_mask)
            self.bg_image = ImageTk.PhotoImage(img)



    def draw_map(self):
        self.canvas.delete("all")
        # 背景画像が未設定の場合のみ、グレーの背景を描画
        if not self.bg_image_original:
            self.canvas.create_rectangle(self.margin_left, self.margin_top,
                                        self.margin_left + self.eff_width, self.margin_top + self.eff_height,
                                        fill="#e0e0e0", outline="")
        else:
            # 背景画像が設定されている場合は、その画像を描画（透明度も反映）
            self.update_bg_image_with_alpha()
            offset = self.offset_x % self.eff_width
            for dx in (-self.eff_width, 0, self.eff_width):
                self.canvas.create_image(self.margin_left + offset + dx,
                                        self.margin_top,
                                        anchor="nw", image=self.bg_image)
        for lon in range(-180, 181, 30):
            x = self.lon_to_x(lon)
            for dx in (-self.eff_width, 0, self.eff_width):
                if lon == 180 and dx != 0:
                    continue
                x_pos = x + dx
                self.canvas.create_line(x_pos, self.margin_top, x_pos, self.margin_top + self.eff_height, fill="gray")
                self.canvas.create_text(x_pos, self.margin_top - 15, text=f"{lon}°", fill="gray")

        for lat in range(LAT_MIN, LAT_MAX + 1, 15):
            y = self.lat_to_y(lat)
            line_color = "rosybrown" if lat == 0 else "gray"
            self.canvas.create_line(self.margin_left, y, self.margin_left + self.eff_width, y, fill=line_color)
            self.canvas.create_text(self.margin_left - 20, y, text=f"{lat}°", fill="gray")

        for pin in self.pins:
            self.draw_pin(pin)
        if self.editing_mode:
            self.update_pin_preview()
        self.update_pin_list()

        # 大圏航路の描画（gc_route_mode が 0 以外の場合）

        if self.gc_route_mode != 0 and self.current_pin:
            # 現在選択中のピンから他のすべてのピンへ大圏航路を描画
            for pin in self.pins:
                if pin != self.current_pin:
                    pts = self.get_gc_points_raw(self.current_pin["lat"], self.current_pin["lon"],
                                                pin["lat"], pin["lon"])
                    self.canvas.create_line(pts, fill="blue", dash=(4, 4))
                    self.canvas.create_line([(x + self.eff_width, y) for (x, y) in pts],
                                            fill="blue", dash=(4, 4))
                    self.canvas.create_line([(x - self.eff_width, y) for (x, y) in pts],
                                            fill="blue", dash=(4, 4))




    def draw_pin(self, pin):
        base_x = self.lon_to_x(pin["lon"])  # ここではモジュロ演算を使わない
        y = self.lat_to_y(pin["lat"])
        # タイルとして左・中央・右側にそれぞれ描画
        for dx in (-self.eff_width, 0, self.eff_width):
            x = base_x + dx
            pts = [x - 3, y - 4, x + 3, y - 4, x, y]
            self.canvas.create_polygon(pts, fill="black", outline="black", tags="pin")
            pin_color = pin.get("color", DEFAULT_PIN_COLOR)
            self.canvas.create_text(x, y - 4, text=pin["name"], fill=pin_color, tags="pin", anchor="s")


    def update_pin_preview(self):
        self.canvas.delete("preview_pin")
        if not self.editing_mode:
            return
        try:
            lat = float(self.lat_var.get())
            lon = float(self.lon_var.get())
        except Exception:
            return
        # キャンバス表示時の変換関数をそのまま使用
        base_x = self.lon_to_x(lon)
        y = self.lat_to_y(lat)
        # 左・中央・右側のタイルに対して描画
        for dx in (-self.eff_width, 0, self.eff_width):
            x = base_x + dx
            pts = [x - 3, y - 4, x + 3, y - 4, x, y]
            self.canvas.create_polygon(pts, fill="red", outline="red", tags="preview_pin")


    def on_canvas_press(self, event):
        self.drag_start = event.x

    def on_canvas_drag(self, event):
        if self.drag_start is not None:
            dx = event.x - self.drag_start
            self.offset_x += dx
            self.offset_x %= self.eff_width
            self.drag_start = event.x
            self.draw_map()

    def on_canvas_release(self, event):
        self.drag_start = None

    def on_pin_click(self, event):
        clicked = None
        for pin in self.pins:
            base_x = self.lon_to_x(pin["lon"])  # 基準となるx座標（タイル分の補正は後で）
            y = self.lat_to_y(pin["lat"])
            # 左・中央・右側のタイルそれぞれでクリック判定
            for dx in (-self.eff_width, 0, self.eff_width):
                x = base_x + dx
                if (event.x - x) ** 2 + (event.y - y) ** 2 < 100:
                    clicked = pin
                    break
            if clicked:
                break
        if clicked:
            # 直前ピン関連の処理は削除
            self.current_pin = clicked
            self.show_pin_detail(clicked)
            self.update_pin_list()
            for i, p in enumerate(self.pins):
                if p == clicked:
                    self.pin_listbox.selection_clear(0, tk.END)
                    self.pin_listbox.selection_set(i)
                    break
            self.draw_map()



    def show_pin_detail(self, pin):
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", tk.END)
        info = f"緯度: {pin['lat']}\n経度: {pin['lon']}\n地名: {pin['name']}\n備考: {pin['remark']}\n色: {pin.get('color', DEFAULT_PIN_COLOR)}"
        self.detail_text.insert(tk.END, info)
        self.detail_text.config(state="disabled")
        self.edit_button.pack(side=tk.LEFT, padx=5)
        self.delete_button.pack(side=tk.LEFT, padx=5)

    def on_pin_list_select(self, event):
        if not self.pin_listbox.curselection():
            return
        index = self.pin_listbox.curselection()[0]
        pin = self.pins[index]
        self.current_pin = pin
        self.show_pin_detail(pin)
        self.update_pin_list()
        self.draw_map()

    def update_pin_list(self):
        self.pin_listbox.delete(0, tk.END)
        self.pins.sort(key=lambda pin: pin['name'])
        selected_pin = self.current_pin
        for pin in self.pins:
            if selected_pin and pin != selected_pin:
                try:
                    distance = self.compute_distance(selected_pin["lat"], selected_pin["lon"], pin["lat"], pin["lon"])
                    display_text = format_pin_entry(pin["name"], distance)
                except Exception:
                    display_text = "  " + pin["name"]
            else:
                display_text = "  " + pin["name"]
            self.pin_listbox.insert(tk.END, display_text)

    def compute_distance(self, lat1, lon1, lat2, lon2):
        # ユーザー設定の星の直径から半径（直径÷2）を取得して計算
        R = self.star_diameter.get() / 2.0  
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return R * c

    def edit_current_pin(self):
        if self.current_pin:
            self.show_pin_input_edit(self.current_pin)

    def delete_current_pin(self):
        if self.current_pin and messagebox.askyesno("確認", "このピンを削除しますか？"):
            self.pins.remove(self.current_pin)
            self.canvas.delete(self.current_pin["marker_id"])
            self.canvas.delete(self.current_pin["text_id"])
            self.current_pin = None
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", tk.END)
            self.detail_text.config(state="disabled")
            self.edit_button.pack_forget()
            self.delete_button.pack_forget()
            self.update_pin_list()

    def show_pin_input_new(self):
        self.editing_pin = None
        self.pin_action_button.config(text="作成")
        self.lat_var.set(0.0)
        self.lon_var.set(0.0)
        self.name_var.set("")
        self.remark_text.config(state="normal")
        self.remark_text.delete("1.0", tk.END)
        self.color_var.set(DEFAULT_PIN_COLOR)
        self.editing_mode = True
        self.set_pin_input_state("normal")
        self.draw_map()

    def show_pin_input_edit(self, pin):
        self.editing_pin = pin
        self.pin_action_button.config(text="更新")
        self.lat_var.set(pin["lat"])
        self.lon_var.set(pin["lon"])
        self.name_var.set(pin["name"])
        self.remark_text.config(state="normal")
        self.remark_text.delete("1.0", tk.END)
        self.remark_text.insert("1.0", pin["remark"])
        self.color_var.set(pin.get("color", DEFAULT_PIN_COLOR))
        self.editing_mode = True
        self.set_pin_input_state("normal")
        self.draw_map()

    def cancel_pin_input(self):
        self.editing_mode = False
        self.set_pin_input_state("disabled")
        self.draw_map()

    def create_or_update_pin(self):
        try:
            lat = float(self.lat_var.get())
            lon = float(self.lon_var.get())
        except ValueError:
            messagebox.showerror("入力エラー", "緯度・経度は数値で入力してください")
            return
        name = self.name_var.get()
        remark = self.remark_text.get("1.0", tk.END).strip()
        pin_color = self.color_var.get()
        if self.editing_pin:
            self.editing_pin.update({"lat": lat, "lon": lon, "name": name, "remark": remark, "color": pin_color})
        else:
            new_pin = {"lat": lat, "lon": lon, "name": name, "remark": remark, "color": pin_color}
            self.pins.append(new_pin)
        self.editing_mode = False
        self.set_pin_input_state("disabled")
        self.draw_map()

    def save_data(self):
        map_name = self.map_name_entry.get().strip()
        if not map_name:
            folder = filedialog.askdirectory(title="保存先フォルダを選択")
            if not folder:
                return
            map_name = os.path.basename(folder)
            self.map_name_entry.delete(0, tk.END)
            self.map_name_entry.insert(0, map_name)
        else:
            folder = map_name
        os.makedirs(folder, exist_ok=True)
        # ピン情報の保存
        filepath = os.path.join(folder, "pins.csv")
        with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["lat", "lon", "name", "remark", "color"])
            for pin in self.pins:
                writer.writerow([pin["lat"], pin["lon"], pin["name"], pin["remark"], pin.get("color", DEFAULT_PIN_COLOR)])
        # settings.json に背景透明度と星の直径を保存（マップ毎）
        self.save_settings(folder)
        self.save_state()

    def save_settings(self, folder):
        settings = {
            "star_diameter": self.star_diameter.get(),
            "bg_alpha": self.bg_alpha.get()
        }
        settings_path = os.path.join(folder, "settings.json")
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

    def load_data(self):
        folder = filedialog.askdirectory(title="マップデータのフォルダを選択")
        if not folder:
            return
        # 選択されたフォルダ名をマップ名として反映
        map_name = os.path.basename(folder)
        self.map_name_entry.delete(0, tk.END)
        self.map_name_entry.insert(0, map_name)

        filepath = os.path.join(folder, "pins.csv")
        if not os.path.exists(filepath):
            messagebox.showerror("エラー", "選択フォルダに pins.csv が見つかりません")
            return
        with open(filepath, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            self.pins.clear()
            for row in reader:
                try:
                    pin = {"lat": float(row["lat"]), "lon": float(row["lon"]),
                        "name": row["name"], "remark": row["remark"],
                        "color": row.get("color", DEFAULT_PIN_COLOR)}
                    self.pins.append(pin)
                except Exception:
                    continue
        settings_path = os.path.join(folder, "settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                if "star_diameter" in settings:
                    self.star_diameter.set(settings["star_diameter"])
                if "bg_alpha" in settings:
                    self.bg_alpha.set(settings["bg_alpha"])
            except Exception:
                pass

        # 背景画像も確実に読み込む
        self.load_bg_image_from_folder()
        self.draw_map()


    def save_state(self):
        state = {
            "map_name": self.map_name_entry.get().strip(),
            "offset_x": self.offset_x,
            "pins": [{"lat": p["lat"], "lon": p["lon"], "name": p["name"], "remark": p["remark"], "color": p.get("color", DEFAULT_PIN_COLOR)} for p in self.pins],
            "resolution_multiplier": self.resolution_multiplier,
            "star_diameter": self.star_diameter.get(),
            "bg_alpha": self.bg_alpha.get()
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
                self.map_name_entry.delete(0, tk.END)
                self.map_name_entry.insert(0, state.get("map_name", "my_map"))
                self.offset_x = state.get("offset_x", 0)
                self.pins = state.get("pins", [])
                for pin in self.pins:
                    if "color" not in pin:
                        pin["color"] = DEFAULT_PIN_COLOR
                self.resolution_multiplier = state.get("resolution_multiplier", 1)
                resolution_text = [key for key, value in RESOLUTION_OPTIONS.items() if value == self.resolution_multiplier][0]
                self.resolution_var.set(resolution_text)
                if "star_diameter" in state:
                    self.star_diameter.set(state["star_diameter"])
                if "bg_alpha" in state:
                    self.bg_alpha.set(state["bg_alpha"])
            except Exception as e:
                messagebox.showerror("読み込みエラー", f"状態の読み込みに失敗しました: {e}")

    def save_and_close(self):
        self.save_data()
        self.root.destroy()









    def generate_map_image(self):
        import math
        multiplier = self.resolution_multiplier
        # 効果領域（マージン除く）サイズ
        export_width = self.eff_width
        export_height = self.eff_height
        scaled_width = int(export_width * multiplier)
        scaled_height = int(export_height * multiplier)

        # 新規画像作成（背景塗りつぶし）
        img = Image.new("RGB", (scaled_width, scaled_height), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (scaled_width, scaled_height)], fill="#e0e0e0")

        # 背景画像描画（タイル貼り）
        if self.bg_image_original:
            try:
                alpha = self.bg_alpha.get() / 100.0
            except Exception:
                alpha = 1.0
            bg = self.bg_image_original.copy().convert("RGBA")
            alpha_mask = Image.new("L", bg.size, int(alpha * 255))
            bg.putalpha(alpha_mask)
            bg_scaled = bg.resize((scaled_width, scaled_height), Image.LANCZOS)
            # 背景はキャンバスと同様に、(offset_x*multiplier) を使い左右タイル状に配置
            offset = int((self.offset_x * multiplier) % scaled_width)
            for dx in (-scaled_width, 0, scaled_width):
                pos = (-offset + dx, 0)
                img.paste(bg_scaled, pos, bg_scaled)

        # グリッド描画（キャンバスと同様）
        for lon in range(-180, 181, 30):
            rel = (lon - LON_MIN) / (LON_MAX - LON_MIN)
            x_eff = (rel * self.eff_width + self.offset_x) % self.eff_width
            x_scaled = int(x_eff * multiplier)
            draw.line([(x_scaled, 0), (x_scaled, scaled_height)], fill="gray")
        for lat in range(LAT_MIN, LAT_MAX + 1, 15):
            rel = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN)
            y_scaled = int(rel * self.eff_height * multiplier)
            draw.line([(0, y_scaled), (scaled_width, y_scaled)], fill="gray")

        # エクスポート用の座標変換（大圏航路用、ラップせず「生の」座標）
        def exp_lat_to_y(lat):
            rel = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN)
            return rel * self.eff_height * multiplier

        def raw_exp_lon_to_x(lon):
            rel = (lon - LON_MIN) / (LON_MAX - LON_MIN)
            # ラップせず、offset_x分をそのまま加算
            return rel * self.eff_width * multiplier + (self.offset_x * multiplier)

        # 大圏航路座標列を求める（ラップせず算出し、連続性を調整）
        def get_raw_export_gc_points(lat1, lon1, lat2, lon2, n=100):
            pts = []
            phi1 = math.radians(lat1)
            phi2 = math.radians(lat2)
            lambda1 = math.radians(lon1)
            lambda2 = math.radians(lon2)
            delta = 2 * math.asin(math.sqrt(math.sin((phi2 - phi1) / 2)**2 +
                                            math.cos(phi1) * math.cos(phi2) * math.sin((lambda2 - lambda1) / 2)**2))
            if delta == 0:
                x = raw_exp_lon_to_x(lon1)
                y = exp_lat_to_y(lat1)
                return [(x, y)] * (n + 1)
            for i in range(n + 1):
                f = i / n
                A = math.sin((1 - f) * delta) / math.sin(delta)
                B = math.sin(f * delta) / math.sin(delta)
                x_val = A * math.cos(phi1) * math.cos(lambda1) + B * math.cos(phi2) * math.cos(lambda2)
                y_val = A * math.cos(phi1) * math.sin(lambda1) + B * math.cos(phi2) * math.sin(lambda2)
                z = A * math.sin(phi1) + B * math.sin(phi2)
                phi = math.atan2(z, math.sqrt(x_val * x_val + y_val * y_val))
                lambda_ = math.atan2(y_val, x_val)
                lat_ = math.degrees(phi)
                lon_ = math.degrees(lambda_)
                pts.append((raw_exp_lon_to_x(lon_), exp_lat_to_y(lat_)))
            # 調整：連続性が保たれるよう、隣接点間の差が scaled_width/2 以上なら scaled_width を加減
            adjusted = [pts[0]]
            for p in pts[1:]:
                prev_x = adjusted[-1][0]
                x, y = p
                while x - prev_x > scaled_width / 2:
                    x -= scaled_width
                while x - prev_x < -scaled_width / 2:
                    x += scaled_width
                adjusted.append((x, y))
            return adjusted

        # 大圏航路描画
        if self.gc_route_mode != 0 and self.current_pin:
            for pin in self.pins:
                if pin == self.current_pin:
                    continue
                pts = get_raw_export_gc_points(self.current_pin["lat"], self.current_pin["lon"],
                                            pin["lat"], pin["lon"])
                # 中央コピー：そのまま描画
                draw.line(pts, fill="blue", width=1)
                # タイリング：線が出口している側に対して、出力画像幅分だけシフトしたコピーを描画
                xs = [x for (x, _) in pts]
                if min(xs) < 0:
                    pts_copy = [(x + scaled_width, y) for (x, y) in pts]
                    draw.line(pts_copy, fill="blue", width=1)
                if max(xs) > scaled_width:
                    pts_copy = [(x - scaled_width, y) for (x, y) in pts]
                    draw.line(pts_copy, fill="blue", width=1)

        # ピン描画（キャンバスと同じ計算、タイル処理）
        fixed_font = self.font.font_variant(size=14)
        for pin in self.pins:
            rel = (pin["lon"] - LON_MIN) / (LON_MAX - LON_MIN)
            x_eff = (rel * self.eff_width + self.offset_x) % self.eff_width
            y_eff = ((LAT_MAX - pin["lat"]) / (LAT_MAX - LAT_MIN)) * self.eff_height
            x_scaled = int(x_eff * multiplier)
            y_scaled = int(y_eff * multiplier)
            pts = [(x_scaled - 3, y_scaled - 4), (x_scaled + 3, y_scaled - 4), (x_scaled, y_scaled)]
            draw.polygon(pts, fill="black")
            pin_color = pin.get("color", DEFAULT_PIN_COLOR)
            draw.text((x_scaled, y_scaled - 8), pin["name"],
                    fill=pin_color, font=fixed_font, anchor="mb")

        return img

















    def export_image(self):
        img = self.generate_map_image()
        save_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Files", "*.png")])
        if save_path:
            img.save(save_path)

    def set_bg_image(self):
        file_path = filedialog.askopenfilename(filetypes=[("画像ファイル", "*.png;*.jpg;*.jpeg;*.bmp"), ("All Files", "*.*")])
        if not file_path:
            return
        try:
            img = Image.open(file_path).convert("RGB")
            img_resized = img.resize((self.eff_width, self.eff_height), Image.LANCZOS)
            folder = self.map_name_entry.get().strip() or "my_map"
            os.makedirs(folder, exist_ok=True)
            save_bg = os.path.join(folder, "map.png")
            img_resized.save(save_bg)
            self.bg_image_original = img_resized
            self.update_bg_image_with_alpha()
            self.draw_map()
        except Exception as e:
            messagebox.showerror("エラー", f"背景画像の読み込みに失敗しました: {e}")

    def load_bg_image_from_folder(self):
        # マップ名欄に入力されている内容をフォルダ名として使用
        folder = self.map_name_entry.get().strip() or "my_map"
        save_bg = os.path.join(folder, "map.png")
        if os.path.exists(save_bg):
            try:
                img = Image.open(save_bg).convert("RGB")
                # キャンバスサイズに合わせてリサイズ
                self.bg_image_original = img.resize((self.eff_width, self.eff_height), Image.LANCZOS)
                self.update_bg_image_with_alpha()
            except Exception as e:
                messagebox.showerror("エラー", f"背景画像の読み込みに失敗しました: {e}")
        else:
            # 背景画像が存在しない場合は変数をクリア
            self.bg_image_original = None
            self.bg_image = None

    def clear_bg_image(self):
        folder = self.map_name_entry.get().strip() or "my_map"
        save_bg = os.path.join(folder, "map.png")
        if os.path.exists(save_bg):
            try:
                os.remove(save_bg)
            except Exception as e:
                messagebox.showerror("エラー", f"背景画像の削除に失敗しました: {e}")
        self.bg_image_original = None
        self.bg_image = None
        self.draw_map()

    def create_new_map(self):
        new_map_name = simpledialog.askstring("新しいマップ", "新しいマップ名を入力してください")
        if new_map_name:
            self.map_name_entry.delete(0, tk.END)
            self.map_name_entry.insert(0, new_map_name)
            self.pins.clear()
            self.offset_x = 0
            self.bg_image_original = None
            self.bg_image = None
            self.current_file = ""
            self.draw_map()
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)

#ここから正距方位図生成

    def export_azimuthal_map(self):
        import pandas as pd
        import matplotlib.pyplot as plt
        import matplotlib.image as mpimg
        import cartopy.crs as ccrs
        import matplotlib.font_manager as fm
        import numpy as np

        jp_font = fm.FontProperties(family="Meiryo", size=8)

        # 選択中のピンがない場合はエラー表示
        if not self.current_pin:
            messagebox.showerror("エラー", "正距方位図法で生成するためにはピンを選択してください")
            return

        # 選択中のピンの座標を中心とする
        central_lat = self.current_pin["lat"]
        central_lon = self.current_pin["lon"]

        # self.pins リストから DataFrame を作成
        df = pd.DataFrame(self.pins)

        # 正距方位図法の投影設定
        proj = ccrs.AzimuthalEquidistant(central_longitude=central_lon, central_latitude=central_lat)

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={"projection": proj})
        ax.gridlines(draw_labels=True)

        # マップフォルダ内の背景画像ファイルを指定（例："map.png"）
        folder = self.map_name_entry.get().strip() or "my_map"
        img_path = os.path.join(folder, "map.png")
        try:
            img = mpimg.imread(img_path)
        except FileNotFoundError:
            print(f"背景画像 {img_path} が見つかりません")
            # ダミーの白い画像を生成（720x1440ピクセル、RGB）
            img = np.ones((720, 1440, 3), dtype=np.uint8) * 255

        # 背景画像の透明度は self.bg_alpha (0～100)
        alpha = self.bg_alpha.get() / 100.0
        ax.imshow(img, extent=[-180, 180, -90, 90],
                transform=ccrs.PlateCarree(), alpha=alpha)

        # ピンのプロット（markersize は3）
        for _, row in df.iterrows():
            ax.plot(row["lon"], row["lat"], marker="o", color=row["color"],
                    markersize=3, transform=ccrs.PlateCarree())
            ax.text(row["lon"], row["lat"] + 2, row["name"],
                    transform=ccrs.PlateCarree(), fontproperties=jp_font, ha="center", color="black")

        plt.show()

#ここからペイントツール

    def set_paint_color(self, color):
        self.paint_color = color
    def open_bg_paint_tool(self):
        import os
        from PIL import ImageDraw, ImageEnhance

        folder = self.map_name_entry.get().strip() or "my_map"
        map_path = os.path.join(folder, "map.png")
        try:
            if os.path.exists(map_path):
                base_img = Image.open(map_path).convert("RGB")
                edit_img = base_img.copy()
            else:
                edit_img = Image.new("RGB", (self.eff_width, self.eff_height), "white")
        except Exception as e:
            messagebox.showerror("エラー", f"背景画像の読み込みに失敗しました: {e}")
            return

        # 拡張幅（左右80px）
        ext = 80

        # タイリング画像作成：元画像を横に3回連結して必要部分を切り出す
        def create_tiled_image(offset_x, source_img):
            width, height = source_img.size
            # effective offsetを [0, width) に正規化
            eff = offset_x % width
            self.paint_eff_offset = eff  # 後の描画用に保持
            # 元画像を横に3枚連結
            tiled_all = Image.new("RGBA", (width * 3, height))
            tiled_all.paste(source_img, (0, 0))
            tiled_all.paste(source_img, (width, 0))
            tiled_all.paste(source_img, (width * 2, 0))
            # 切り出し開始位置：中央画像の左側ext分＋effective offset分を調整
            start = width - ext - eff
            return tiled_all.crop((start, 0, start + width + ext * 2, height))

        # 横スクロール用変数（スライダーから変更）
        self.paint_offset_x_var = tk.IntVar(value=0)
        self.paint_eff_offset = 0

        # ペイントツールウィンドウ作成
        paint_win = tk.Toplevel(self.root)
        paint_win.title("背景画像ペイントツール")

        # ペイント用変数
        self.paint_color = "black"
        self.paint_pen_size = tk.IntVar(value=10)
        self.paint_img = edit_img  # 編集対象の画像（RGB）
        self.paint_ext = ext

        # 透明度用変数（0～100）
        self.map_alpha_var = tk.IntVar(value=100)
        self.pins_alpha_var = tk.IntVar(value=100)

        # --- ここから undo/redo 履歴の設定 ---
        # 履歴は初期状態から開始（コピーを保存）
        paint_history = [self.paint_img.copy()]
        history_index = [0]  # リストに入れて可変な整数として扱う

        def push_history():
            # 現在の履歴の先の状態は削除
            del paint_history[history_index[0]+1:]
            paint_history.append(self.paint_img.copy())
            if len(paint_history) > 50:
                # 50を超えたら最古を削除しインデックスを調整
                paint_history.pop(0)
            else:
                history_index[0] = len(paint_history) - 1

        def undo():
            if history_index[0] > 0:
                history_index[0] -= 1
                self.paint_img = paint_history[history_index[0]].copy()
                update_paint_preview()

        def redo():
            if history_index[0] < len(paint_history) - 1:
                history_index[0] += 1
                self.paint_img = paint_history[history_index[0]].copy()
                update_paint_preview()
        # --- undo/redo 設定ここまで ---

        # コントロール領域（各種スライダー＋カラーパレット＋undo/redoボタン）
        control_frame = ttk.Frame(paint_win)
        control_frame.pack(side=tk.TOP, fill=tk.X, pady=5)

        # ペンサイズ
        ttk.Label(control_frame, text="ペンの大きさ:").pack(side=tk.LEFT, padx=5)
        pen_slider = ttk.Scale(control_frame, from_=1, to=50, orient=tk.HORIZONTAL,
                                variable=self.paint_pen_size, command=lambda e: update_paint_preview())
        pen_slider.pack(side=tk.LEFT, padx=5)

        # マップ透明度
        ttk.Label(control_frame, text="マップ透明度:").pack(side=tk.LEFT, padx=5)
        map_alpha_slider = ttk.Scale(control_frame, from_=0, to=100, orient=tk.HORIZONTAL,
                                     variable=self.map_alpha_var, command=lambda e: update_paint_preview())
        map_alpha_slider.pack(side=tk.LEFT, padx=5)

        # ピン透明度
        ttk.Label(control_frame, text="ピン透明度:").pack(side=tk.LEFT, padx=5)
        pins_alpha_slider = ttk.Scale(control_frame, from_=0, to=100, orient=tk.HORIZONTAL,
                                      variable=self.pins_alpha_var, command=lambda e: update_paint_preview())
        pins_alpha_slider.pack(side=tk.LEFT, padx=5)

        # 横スクロール（経度方向移動）
        ttk.Label(control_frame, text="横スクロール:").pack(side=tk.LEFT, padx=5)
        offset_slider = ttk.Scale(control_frame, from_=-self.eff_width, to=self.eff_width, orient=tk.HORIZONTAL,
                                  variable=self.paint_offset_x_var, command=lambda e: update_paint_preview())
        offset_slider.pack(side=tk.LEFT, padx=5)

        # カラーパレット
        palette_frame = ttk.Frame(control_frame)
        palette_frame.pack(side=tk.LEFT, padx=10)
        colors = ["red", "blue", "yellow", "black", "lightgrey", "white", "sienna", "wheat", "yellowgreen", "paleturquoise"]
        for c in colors:
            btn = tk.Button(palette_frame, bg=c, width=2, command=lambda col=c: self.set_paint_color(col))
            btn.pack(side=tk.LEFT, padx=1)

        # undo/redo ボタン
        ttk.Button(control_frame, text="Undo", command=undo).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Redo", command=redo).pack(side=tk.LEFT, padx=5)

        # キャンバス（タイリング画像表示）
        tiled = create_tiled_image(self.paint_offset_x_var.get(), self.paint_img.convert("RGBA"))
        self.paint_canvas_img = ImageTk.PhotoImage(tiled)
        canvas_width, canvas_height = tiled.size
        paint_canvas = tk.Canvas(paint_win, width=canvas_width, height=canvas_height, bg="white")
        paint_canvas.pack()
        self.paint_canvas = paint_canvas

        # 描画状態管理
        self.paint_drawing = False
        self.paint_last_x = None
        self.paint_last_y = None

        # update_paint_preview()：背景画像に透明度を適用し、タイリング＋グリッド・ピンオーバーレイを合成
        def update_paint_preview():
            offset_x = self.paint_offset_x_var.get()
            map_alpha = self.map_alpha_var.get() / 100.0
            pins_alpha = self.pins_alpha_var.get() / 100.0

            # マップ画像に透明度適用
            base_img = self.paint_img.convert("RGBA")
            if map_alpha < 1.0:
                alpha_mask = Image.new("L", base_img.size, int(map_alpha * 255))
                base_img.putalpha(alpha_mask)
            else:
                base_img.putalpha(255)

            # タイル画像再作成（背景は create_tiled_image() で生成済み）
            tiled = create_tiled_image(offset_x, base_img)

            # オーバーレイ用透明レイヤー作成
            overlay = Image.new("RGBA", tiled.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # 基本パラメータ
            W = self.paint_img.width
            H = self.paint_img.height
            ext = self.paint_ext

            # 中央コピーでの座標変換（元画像[0,W]を中央部分に配置）
            def conv_lon_to_x_base(lon):
                original_x = (lon - LON_MIN) / (LON_MAX - LON_MIN) * W
                return int(ext + self.paint_eff_offset + original_x)
            def conv_lat_to_y(lat):
                original_y = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * H
                return int(original_y)

            # 横方向に−1,0,1コピー分描画
            for copy in [-1, 0, 1]:
                # 経度グリッド：各コピーで位置ずらして描画
                for lon in range(-180, 181, 30):
                    x = conv_lon_to_x_base(lon) + copy * W
                    # 描画範囲内の場合のみ描画
                    if 0 <= x <= tiled.width:
                        draw.line([(x, 0), (x, H)], fill=(128, 128, 128, int(255 * pins_alpha)))
                # ピン描画
                for pin in self.pins:
                    x = conv_lon_to_x_base(pin["lon"]) + copy * W
                    y = conv_lat_to_y(pin["lat"])
                    pts = [(x - 3, y - 4), (x + 3, y - 4), (x, y)]
                    draw.polygon(pts, fill=(0, 0, 0, int(255 * pins_alpha)))
                    # 小さめフォント・下端中央揃え：anchor "ms"（middle, bottom）
                    draw.text((x, y - 5), pin["name"],
                              fill=(0, 0, 0, int(255 * pins_alpha)),
                              font=self.font.font_variant(size=12),
                              anchor="ms")
            # 横方向の緯度グリッド（水平線）は全体横断
            for lat in range(LAT_MIN, LAT_MAX + 1, 15):
                y = conv_lat_to_y(lat)
                draw.line([(0, y), (tiled.width, y)], fill=(128, 128, 128, int(255 * pins_alpha)))
            
            composed = Image.alpha_composite(tiled, overlay)
            self.paint_canvas_img = ImageTk.PhotoImage(composed)
            paint_canvas.delete("all")
            paint_canvas.create_image(0, 0, anchor="nw", image=self.paint_canvas_img)


        update_paint_preview()

        # 描画イベント（ペイント処理）
        def paint_start(event):
            self.paint_drawing = True
            self.paint_last_x = event.x
            self.paint_last_y = event.y

        def paint_draw(event):
            if not self.paint_drawing:
                return
            x, y = event.x, event.y
            pen = self.paint_pen_size.get()
            width = self.paint_img.width
            # オフセット：切り出し開始位置（元画像のオフセット位置）
            offset = width - self.paint_ext - self.paint_eff_offset
            # キャンバス上の座標から元画像上の「生の」x座標に変換
            raw_x1 = self.paint_last_x + offset
            raw_x2 = x + offset
            hy1 = self.paint_last_y
            hy2 = y
            # 元画像内の対応位置（シーム処理用）
            mod_x1 = raw_x1 % width
            mod_x2 = raw_x2 % width
            diff = mod_x2 - mod_x1

            draw = ImageDraw.Draw(self.paint_img)

            # 補助関数：2点間を丸いペンで描画
            def draw_round_line(x1, y1, x2, y2):
                dist = math.hypot(x2 - x1, y2 - y1)
                if dist == 0:
                    dist = 1
                steps = int(dist) + 1
                for i in range(steps + 1):
                    t = i / steps
                    xi = x1 + t * (x2 - x1)
                    yi = y1 + t * (y2 - y1)
                    r = pen / 2
                    draw.ellipse((xi - r, yi - r, xi + r, yi + r), fill=self.paint_color)

            # シームを跨ぐ場合は左右に分割して描画
            if abs(diff) <= width / 2:
                draw_round_line(mod_x1, hy1, mod_x2, hy2)
            else:
                if diff > 0:
                    draw_round_line(mod_x1, hy1, 0, hy2)
                    draw_round_line(width, hy1, mod_x2, hy2)
                else:
                    draw_round_line(mod_x1, hy1, width, hy2)
                    draw_round_line(0, hy1, mod_x2, hy2)

            self.paint_last_x = x
            self.paint_last_y = y
            update_paint_preview()



        def paint_end(event):
            self.paint_drawing = False
            self.paint_last_x = None
            self.paint_last_y = None
            # ストローク終了時に履歴を更新
            push_history()

        paint_canvas.bind("<ButtonPress-1>", paint_start)
        paint_canvas.bind("<B1-Motion>", paint_draw)
        paint_canvas.bind("<ButtonRelease-1>", paint_end)

        # 保存／キャンセルボタン
        button_frame = ttk.Frame(paint_win)
        button_frame.pack(side=tk.BOTTOM, pady=5)
        def save_paint():
            try:
                os.makedirs(folder, exist_ok=True)
                save_path = os.path.join(folder, "map.png")
                self.paint_img.convert("RGB").save(save_path)
                self.bg_image_original = self.paint_img.copy()
                self.draw_map()
                paint_win.destroy()
            except Exception as e:
                messagebox.showerror("エラー", f"保存に失敗しました: {e}")

        def cancel_paint():
            paint_win.destroy()

        ttk.Button(button_frame, text="保存", command=save_paint).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="キャンセル", command=cancel_paint).pack(side=tk.LEFT, padx=5)

# 大圏航路表示

    def toggle_gc_route(self):
        # モードは0: 表示無効、1: 表示有効 の2モードに変更
        self.gc_route_mode = (self.gc_route_mode + 1) % 2
        mode_text = ["無効", "有効"]
        self.gc_route_button.config(text="大圏航路表示: " + mode_text[self.gc_route_mode])
        self.draw_map()



    # キャンバス上の「生の」座標を返す関数（タイリング前）
    def lon_to_x_raw(self, lon):
        relative = (lon - LON_MIN) / (LON_MAX - LON_MIN)
        return self.margin_left + relative * self.eff_width + self.offset_x

    def lat_to_y_raw(self, lat):
        relative = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN)
        return self.margin_top + relative * self.eff_height

    def get_gc_points_raw(self, lat1, lon1, lat2, lon2, n=100):
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        lambda1 = math.radians(lon1)
        lambda2 = math.radians(lon2)
        delta = 2 * math.asin(math.sqrt(math.sin((phi2 - phi1) / 2) ** 2 +
                                        math.cos(phi1) * math.cos(phi2) * math.sin((lambda2 - lambda1) / 2) ** 2))
        if delta == 0:
            return [(self.lon_to_x_raw(lon1), self.lat_to_y_raw(lat1))] * (n + 1)
        pts = []
        for i in range(n + 1):
            f = i / n
            A = math.sin((1 - f) * delta) / math.sin(delta)
            B = math.sin(f * delta) / math.sin(delta)
            x = A * math.cos(phi1) * math.cos(lambda1) + B * math.cos(phi2) * math.cos(lambda2)
            y = A * math.cos(phi1) * math.sin(lambda1) + B * math.cos(phi2) * math.sin(lambda2)
            z = A * math.sin(phi1) + B * math.sin(phi2)
            phi = math.atan2(z, math.sqrt(x * x + y * y))
            lambda_ = math.atan2(y, x)
            lat = math.degrees(phi)
            lon = math.degrees(lambda_)
            pts.append((self.lon_to_x_raw(lon), self.lat_to_y_raw(lat)))
        # 補正処理（連続性のため）
        adjusted = [pts[0]]
        for p in pts[1:]:
            prev_x = adjusted[-1][0]
            x, y = p
            while x - prev_x > self.eff_width / 2:
                x -= self.eff_width
            while x - prev_x < -self.eff_width / 2:
                x += self.eff_width
            adjusted.append((x, y))
        return adjusted





if __name__ == "__main__":
    root = tk.Tk()
    app = MapMakerApp(root)
    root.mainloop()
