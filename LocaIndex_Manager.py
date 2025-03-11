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

# --- メインコード ---
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
        self.map_gen_button = ttk.Button(self.detail_panel, text="正距方位図法生成", command=self.export_azimuthal_map)
        self.map_gen_button.pack(pady=5)


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

    def draw_pin(self, pin):
        x = self.lon_to_x(pin["lon"]) % self.eff_width + self.margin_left
        y = self.lat_to_y(pin["lat"])
        pts = [x - 3, y - 4, x + 3, y - 4, x, y]
        if "marker_id" in pin:
            self.canvas.delete(pin["marker_id"])
        marker = self.canvas.create_polygon(pts, fill="black", outline="black", tags="pin")
        pin["marker_id"] = marker
        if "text_id" in pin:
            self.canvas.delete(pin["text_id"])
        pin_color = pin.get("color", DEFAULT_PIN_COLOR)
        text_id = self.canvas.create_text(x, y - 4, text=pin["name"], fill=pin_color, tags="pin", anchor="s")
        pin["text_id"] = text_id

    def update_pin_preview(self):
        self.canvas.delete("preview_pin")
        if not self.editing_mode:
            return
        try:
            lat = float(self.lat_var.get())
            lon = float(self.lon_var.get())
        except Exception:
            return
        x = self.lon_to_x(lon) % self.eff_width + self.margin_left
        y = self.lat_to_y(lat)
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
            x = self.lon_to_x(pin["lon"]) % self.eff_width + self.margin_left
            y = self.lat_to_y(pin["lat"])
            if (event.x - x) ** 2 + (event.y - y) ** 2 < 100:
                clicked = pin
                break
        if clicked:
            self.current_pin = clicked
            self.show_pin_detail(clicked)
            self.update_pin_list()  # 一覧表示の更新
            # 一覧内で選択されたピンをハイライト
            for i, p in enumerate(self.pins):
                if p == clicked:
                    self.pin_listbox.selection_clear(0, tk.END)
                    self.pin_listbox.selection_set(i)
                    break

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
        multiplier = self.resolution_multiplier
        scaled_width = int(self.eff_width * multiplier)
        scaled_height = int(self.eff_height * multiplier)
        scaled_margin_left = int(self.margin_left * multiplier)
        scaled_margin_top = int(self.margin_top * multiplier)

        img = Image.new("RGB", (scaled_width, scaled_height), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (scaled_width, scaled_height)], fill="#e0e0e0")

        if self.bg_image_original:
            try:
                alpha = self.bg_alpha.get() / 100.0
            except Exception:
                alpha = 1.0
            img_bg = self.bg_image_original.copy().convert("RGBA")
            alpha_mask = Image.new("L", img_bg.size, int(alpha * 255))
            img_bg.putalpha(alpha_mask)
            scaled_bg_image = img_bg.resize((scaled_width, scaled_height), Image.LANCZOS)
            offset = int((self.offset_x * multiplier) % scaled_width)
            for dx in (-scaled_width, 0, scaled_width):
                pos = (-offset + dx, 0)
                img.paste(scaled_bg_image, pos, scaled_bg_image)

        fixed_font = self.font.font_variant(size=14)
        for lon in range(-180, 181, 30):
            rel = (lon - LON_MIN) / (LON_MAX - LON_MIN)
            x = int(rel * scaled_width + (self.offset_x * multiplier) % scaled_width)
            for dx in (-scaled_width, 0, scaled_width):
                x_pos = x + dx
                draw.line([(x_pos, 0), (x_pos, scaled_height)], fill="gray")
        for lat in range(LAT_MIN, LAT_MAX + 1, 15):
            rel = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN)
            y = int(rel * scaled_height)
            draw.line([(0, y), (scaled_width, y)], fill="gray")
        for pin in self.pins:
            rel_x = (pin["lon"] - LON_MIN) / (LON_MAX - LON_MIN)
            x = int(scaled_margin_left + rel_x * self.eff_width * multiplier + (self.offset_x * multiplier)) % scaled_width
            rel_y = (LAT_MAX - pin["lat"]) / (LAT_MAX - LAT_MIN)
            y = int(scaled_margin_top + rel_y * self.eff_height * multiplier)
            pts = [(x - 2, y - 4), (x + 2, y - 4), (x, y)]
            draw.polygon(pts, fill="black")
            pin_color = pin.get("color", DEFAULT_PIN_COLOR)
            draw.text((x, y - 8), pin["name"], fill=pin_color, font=fixed_font, anchor="mb")
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







if __name__ == "__main__":
    root = tk.Tk()
    app = MapMakerApp(root)
    root.mainloop()
