import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import csv, os, math, json
from PIL import Image, ImageTk, ImageDraw, ImageOps, ImageFont  # ImageFont をインポート
from io import BytesIO

# 定数（緯度は -90～90、経度は -180～180）
LAT_MIN, LAT_MAX = -90, 90
LON_MIN, LON_MAX = -180, 180

STATE_FILE = "app_state.json"
DEFAULT_FONT_PATH = "meiryo.ttc"  # デフォルトフォントパス
DEFAULT_PIN_COLOR = "blue" # デフォルトピンの色
PIN_COLORS = ["black", "red", "blue", "green", "yellow", "purple", "orange"] # ピンの色候補
RESOLUTION_OPTIONS = {"1x": 1, "2x": 2, "3x": 3} # 解像度選択肢と倍率

class MapMakerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LocaIndex_Manager")
        self.root.resizable(False, False)  # 画面サイズ固定

        # キャンバスサイズ＋マージン設定
        self.canvas_width = 1200
        self.canvas_height = 750
        self.margin_left = 40
        self.margin_right = 40
        self.margin_top = 40
        self.margin_bottom = 40
        self.eff_width = self.canvas_width - self.margin_left - self.margin_right
        self.eff_height = self.canvas_height - self.margin_top - self.margin_bottom

        self.offset_x = 0    # 経度方向スクロール（効果領域）
        self.pins = []      # 各ピン: {"lat", "lon", "name", "remark", "color", marker_id, text_id} # color を追加
        self.current_file = ""  # JSON状態保存用
        self.editing_pin = None  # ピン作成／編集中の対象
        self.editing_mode = False  # 編集領域有効かどうか
        self.resolution_multiplier = 1 # 解像度倍率の初期値 (1x)

        # 背景画像：PhotoImage 用と元の PIL Image（タイリング・画像生成用）
        self.bg_image = None
        self.bg_image_original = None

        # フォント設定
        self.font = self.load_font()

        self.create_widgets()
        self.load_state()  # 前回の状態があれば読み込み
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
        # 上部：操作ボタン
        top_frame = ttk.Frame(self.root)
        top_frame.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(top_frame, text="ピン作成", command=self.show_pin_input_new).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(top_frame, text="マップデータを開く", command=self.load_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="保存", command=self.save_data).pack(side=tk.LEFT, padx=5)  # 統合された保存ボタン
        ttk.Button(top_frame, text="保存して閉じる", command=self.save_and_close).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="背景画像設定", command=self.set_bg_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="背景画像削除", command=self.clear_bg_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="新しいマップ", command=self.create_new_map).pack(side=tk.LEFT, padx=5)
        ttk.Label(top_frame, text="マップ名:").pack(side=tk.LEFT, padx=5)
        self.map_name_entry = ttk.Entry(top_frame, width=15)
        self.map_name_entry.pack(side=tk.LEFT)
        self.map_name_entry.insert(0, "my_map")

        # 解像度選択コンボボックス
        ttk.Label(top_frame, text="出力解像度:").pack(side=tk.LEFT, padx=5) # ラベルテキストを修正
        self.resolution_var = tk.StringVar(value="1x") # 初期値を 1x に設定
        self.resolution_combo = ttk.Combobox(top_frame, textvariable=self.resolution_var, values=list(RESOLUTION_OPTIONS.keys()), width=5)
        self.resolution_combo.pack(side=tk.LEFT, padx=5)
        self.resolution_combo.bind("<<ComboboxSelected>>", self.on_resolution_change)

        ttk.Button(top_frame, text="画像生成", command=self.export_image).pack(side=tk.LEFT, padx=5) # ボタンを移動


        # 中央領域：左側はキャンバス、右側はピン一覧＋詳細パネル
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
        ttk.Label(self.detail_panel, text="ピン一覧").pack(anchor="nw")
        self.pin_listbox = tk.Listbox(self.detail_panel, height=30)
        self.pin_listbox.pack(fill=tk.X, pady=2)
        self.pin_listbox.bind("<<ListboxSelect>>", self.on_pin_list_select)
        ttk.Label(self.detail_panel, text="ピン詳細").pack(anchor="nw", pady=(10, 0))
        self.detail_text = tk.Text(self.detail_panel, width=30, height=8, state="disabled")
        self.detail_text.pack(pady=5)
        button_frame = ttk.Frame(self.detail_panel)
        button_frame.pack(pady=5)
        self.edit_button = ttk.Button(button_frame, text="編集", command=self.edit_current_pin)
        self.edit_button.pack(side=tk.LEFT, padx=5)
        self.delete_button = ttk.Button(button_frame, text="削除", command=self.delete_current_pin)
        self.delete_button.pack(side=tk.LEFT, padx=5)
        self.edit_button.pack_forget()
        self.delete_button.pack_forget()
        self.current_pin = None

        # 下部：ピン作成／編集入力領域（初期は無効＝暗転）
        self.pin_frame = ttk.Frame(self.root, relief=tk.RIDGE, padding=5)
        self.pin_frame.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(self.pin_frame, text="【ピン作成／編集】").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 5))
        ttk.Label(self.pin_frame, text="緯度(°):").grid(row=1, column=0, padx=5, sticky="e")
        self.lat_var = tk.DoubleVar(value=0.0)
        self.lat_entry = ttk.Entry(self.pin_frame, textvariable=self.lat_var, width=28)  # 幅
        self.lat_entry.grid(row=1, column=1, padx=5, sticky="w")
        self.lat_scale = ttk.Scale(self.pin_frame, from_=LAT_MIN, to=LAT_MAX, orient=tk.HORIZONTAL, length=700, variable=self.lat_var, command=lambda v: self.update_pin_preview())
        self.lat_scale.grid(row=1, column=2, padx=5)
        ttk.Label(self.pin_frame, text="経度(°):").grid(row=2, column=0, padx=5, sticky="e")
        self.lon_var = tk.DoubleVar(value=0.0)
        self.lon_entry = ttk.Entry(self.pin_frame, textvariable=self.lon_var, width=28)  # 幅
        self.lon_entry.grid(row=2, column=1, padx=5, sticky="w")
        self.lon_scale = ttk.Scale(self.pin_frame, from_=LON_MIN, to=LON_MAX, orient=tk.HORIZONTAL, length=700, variable=self.lon_var, command=lambda v: self.update_pin_preview())
        self.lon_scale.grid(row=2, column=2, padx=5)
        ttk.Label(self.pin_frame, text="地名:").grid(row=3, column=0, padx=5, sticky="e")
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(self.pin_frame, textvariable=self.name_var, width=20)
        self.name_entry.grid(row=3, column=1, columnspan=2, padx=5, sticky="w")
        ttk.Label(self.pin_frame, text="備考:").grid(row=4, column=0, padx=5, sticky="e")
        self.remark_var = tk.StringVar()
        self.remark_entry = ttk.Entry(self.pin_frame, textvariable=self.remark_var, width=20)
        self.remark_entry.grid(row=4, column=1, columnspan=2, padx=5, sticky="w")

        # ピンの色選択 ComboBox を追加
        ttk.Label(self.pin_frame, text="色:").grid(row=5, column=0, padx=5, sticky="e")  # 行番号を修正
        self.color_var = tk.StringVar(value=DEFAULT_PIN_COLOR)  # デフォルト値を設定
        self.color_combo = ttk.Combobox(self.pin_frame, textvariable=self.color_var, values=PIN_COLORS, width=18)  # 幅を調整
        self.color_combo.grid(row=5, column=1, columnspan=2, padx=5, sticky="w")  # 行番号を修正

        self.pin_action_button = ttk.Button(self.pin_frame, text="作成", command=self.create_or_update_pin)
        self.pin_action_button.grid(row=6, column=0, columnspan=2, pady=5)  # 行番号を修正
        self.cancel_button = ttk.Button(self.pin_frame, text="キャンセル", command=self.cancel_pin_input)
        self.cancel_button.grid(row=6, column=2, pady=5)  # 行番号を修正
        self.set_pin_input_state("disabled")
        for var in (self.lat_var, self.lon_var, self.name_var):
            var.trace("w", lambda *args: self.update_pin_preview())

    def set_pin_input_state(self, state):
        self.lat_entry.config(state=state)
        self.lat_scale.config(state=state)
        self.lon_entry.config(state=state)
        self.lon_scale.config(state=state)
        self.name_entry.config(state=state)
        self.remark_entry.config(state=state)
        self.color_combo.config(state=state) # 色選択コンボボックスの状態設定
        self.pin_action_button.config(state=state)
        self.cancel_button.config(state=state)
        bg = "#f0f0f0" if state == "disabled" else "white"
        for widget in (self.lat_entry, self.lon_entry, self.name_entry, self.remark_entry, self.color_combo): # 色選択コンボボックスをループに追加
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

    def draw_map(self):
        self.canvas.delete("all")
        self.canvas.create_rectangle(self.margin_left, self.margin_top,
                                     self.margin_left + self.eff_width, self.margin_top + self.eff_height,
                                     fill="#e0e0e0", outline="")
        if self.bg_image:
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
                self.canvas.create_text(x_pos, self.margin_top - 15, text=f"{lon}°", fill="gray") # 経度ラベルを再表示
        for lat in range(LAT_MIN, LAT_MAX + 1, 15):
            y = self.lat_to_y(lat)
            self.canvas.create_line(self.margin_left, y, self.margin_left + self.eff_width, y, fill="gray")
            self.canvas.create_text(self.margin_left - 20, y, text=f"{lat}°", fill="gray") # 緯度ラベルを再表示
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
        pin_color = pin.get("color", DEFAULT_PIN_COLOR) # デフォルト色を使用
        text_id = self.canvas.create_text(x, y - 4, text=pin["name"], fill=pin_color, tags="pin", anchor="s") # 色指定、アンカーは "s"
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

    def show_pin_detail(self, pin):
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", tk.END)
        info = f"緯度: {pin['lat']}\n経度: {pin['lon']}\n地名: {pin['name']}\n備考: {pin['remark']}\n色: {pin.get('color', DEFAULT_PIN_COLOR)}" # 色情報を表示
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

    def update_pin_list(self):
        self.pin_listbox.delete(0, tk.END)
        self.pins.sort(key=lambda pin: pin['name']) # 名前順にソート
        for pin in self.pins:
            self.pin_listbox.insert(tk.END, pin["name"])

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
        self.remark_var.set("")
        self.color_var.set(DEFAULT_PIN_COLOR) # デフォルト色を設定
        self.editing_mode = True
        self.set_pin_input_state("normal")
        self.draw_map()

    def show_pin_input_edit(self, pin):
        self.editing_pin = pin
        self.pin_action_button.config(text="更新")
        self.lat_var.set(pin["lat"])
        self.lon_var.set(pin["lon"])
        self.name_var.set(pin["name"])
        self.remark_var.set(pin["remark"])
        self.color_var.set(pin.get("color", DEFAULT_PIN_COLOR)) # 色を読み込み、デフォルト値を設定
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
        remark = self.remark_var.get()
        pin_color = self.color_var.get() # 色を取得

        if self.editing_pin:
            self.editing_pin.update({"lat": lat, "lon": lon, "name": name, "remark": remark, "color": pin_color}) # 色を更新
        else:
            new_pin = {"lat": lat, "lon": lon, "name": name, "remark": remark, "color": pin_color} # 色を保存
            self.pins.append(new_pin)
        self.editing_mode = False
        self.set_pin_input_state("disabled")
        self.draw_map()

    def save_data(self):
        map_name = self.map_name_entry.get().strip()
        if not map_name:
            # マップ名が未指定の場合、ファイルダイアログを開く
            folder = filedialog.askdirectory(title="保存先フォルダを選択")
            if not folder:
                return
            map_name = os.path.basename(folder)
            self.map_name_entry.delete(0, tk.END)
            self.map_name_entry.insert(0, map_name)
        else:
            # 既存のマップ名で保存
            folder = map_name
        os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, "pins.csv")
        with open(filepath, "w", newline="", encoding="utf-8") as csvfile: # encoding="utf-8" を明示的に指定
            writer = csv.writer(csvfile)
            writer.writerow(["lat", "lon", "name", "remark", "color"]) # ヘッダーに color を追加
            for pin in self.pins:
                writer.writerow([pin["lat"], pin["lon"], pin["name"], pin["remark"], pin.get("color", DEFAULT_PIN_COLOR)]) # 色を保存
        # 状態を保存
        self.save_state()

    def load_data(self):
        folder = filedialog.askdirectory(title="マップデータのフォルダを選択")
        if not folder:
            return
        filepath = os.path.join(folder, "pins.csv")
        if not os.path.exists(filepath):
            messagebox.showerror("エラー", "選択フォルダに pins.csv が見つかりません")
            return
        with open(filepath, "r", encoding="utf-8") as csvfile: # encoding="utf-8" を明示的に指定
            reader = csv.DictReader(csvfile)
            self.pins.clear()
            for row in reader:
                try:
                    pin = {"lat": float(row["lat"]), "lon": float(row["lon"]),
                           "name": row["name"], "remark": row["remark"], "color": row.get("color", DEFAULT_PIN_COLOR)} # 色を読み込み、デフォルト値を設定
                    self.pins.append(pin)
                except Exception:
                    continue
        self.draw_map()

    def save_state(self):
        state = {
            "map_name": self.map_name_entry.get().strip(),
            "offset_x": self.offset_x,
            "pins": [{"lat": p["lat"], "lon": p["lon"], "name": p["name"], "remark": p["remark"], "color": p.get("color", DEFAULT_PIN_COLOR)} for p in self.pins], # 色を保存
            "resolution_multiplier": self.resolution_multiplier, # 解像度倍率を保存
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
                for pin in self.pins: # 色が保存されていない場合のデフォルト値設定
                    if "color" not in pin:
                        pin["color"] = DEFAULT_PIN_COLOR
                self.resolution_multiplier = state.get("resolution_multiplier", 1) # 解像度倍率を読み込み、デフォルト値を設定
                resolution_text = [key for key, value in RESOLUTION_OPTIONS.items() if value == self.resolution_multiplier][0] # 倍率から表示テキストに変換
                self.resolution_var.set(resolution_text) # コンボボックスに設定
            except Exception as e:
                messagebox.showerror("読み込みエラー", f"状態の読み込みに失敗しました: {e}")

    def save_and_close(self):
        self.save_data()
        self.root.destroy()

    def generate_map_image(self):
            multiplier = self.resolution_multiplier # 解像度倍率を取得
            scaled_width = int(self.eff_width * multiplier) # スケール後の幅
            scaled_height = int(self.eff_height * multiplier) # スケール後の高さ
            scaled_margin_left = int(self.margin_left * multiplier) # スケール後の左マージン
            scaled_margin_top = int(self.margin_top * multiplier) # スケール後の上マージン

            img = Image.new("RGB", (scaled_width, scaled_height), "white") # スケール後のサイズで画像作成
            draw = ImageDraw.Draw(img) # ImageDraw オブジェクトを取得
            draw.rectangle([(0, 0), (scaled_width, scaled_height)], fill="#e0e0e0") # スケール後のサイズで背景描画

            if self.bg_image_original:
                scaled_bg_image = self.bg_image_original.resize((scaled_width, scaled_height), Image.LANCZOS) # 背景画像もスケール
                offset = int((self.offset_x * multiplier) % scaled_width) # オフセットもスケール
                for dx in (-scaled_width, 0, scaled_width): # スケール後の幅でタイリング
                    pos = (-offset + dx, 0)
                    img.paste(scaled_bg_image, pos)

            fixed_font = self.font.font_variant(size=14) # 固定フォントサイズを14ピクセルで生成


            for lon in range(-180, 181, 30):
                rel = (lon - LON_MIN) / (LON_MAX - LON_MIN)
                x = int(rel * scaled_width + (self.offset_x * multiplier) % scaled_width) # X座標をスケール
                for dx in (-scaled_width, 0, scaled_width): # スケール後の幅で繰り返し
                    x_pos = x + dx
                    draw.line([(x_pos, 0), (x_pos, scaled_height)], fill="gray") # スケール後の高さまで線描画
                    # draw.text((x_pos, scaled_margin_top - int(15*multiplier)), f"{lon}°", fill="gray", font=scaled_font, anchor="ms") # 経度ラベルを削除

            for lat in range(LAT_MIN, LAT_MAX + 1, 15):
                rel = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN)
                y = int(rel * scaled_height) # Y座標をスケール
                draw.line([(0, y), (scaled_width, y)], fill="gray") # スケール後の幅まで線描画
                # draw.text((scaled_margin_left - int(20*multiplier)), f"{lat}°", fill="gray", font=scaled_font, anchor="rm") # 緯度ラベルを削除


            for pin in self.pins:
                rel_x = (pin["lon"] - LON_MIN) / (LON_MAX - LON_MIN)
                x = int(scaled_margin_left + rel_x * self.eff_width * multiplier + (self.offset_x * multiplier)) % scaled_width # ピンのX座標をスケール
                rel_y = (LAT_MAX - pin["lat"]) / (LAT_MAX - LAT_MIN)
                y = int(scaled_margin_top + rel_y * self.eff_height * multiplier) # ピンのY座標をスケール
                pts = [(x - 2, y - 4), (x + 2, y - 4), (x, y)] # ピンマーカーの頂点座標は固定値
                draw.polygon(pts, fill="black")
                pin_color = pin.get("color", DEFAULT_PIN_COLOR) # ピンの色を取得
                draw.text((x, y - 8), pin["name"], fill=pin_color, font=fixed_font, anchor="mb") # ピン名を固定フォントサイズで描画、アンカーを mb に修正

            return img

    def export_image(self):
        img = self.generate_map_image() # generate_map_image() でスケール済みの画像が生成される
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
            self.bg_image = ImageTk.PhotoImage(img_resized)
            self.draw_map()
        except Exception as e:
            messagebox.showerror("エラー", f"背景画像の読み込みに失敗しました: {e}")

    def load_bg_image_from_folder(self):
        folder = self.map_name_entry.get().strip() or "my_map"
        save_bg = os.path.join(folder, "map.png")
        if os.path.exists(save_bg):
            try:
                img = Image.open(save_bg).convert("RGB")
                self.bg_image_original = img.resize((self.eff_width, self.eff_height), Image.LANCZOS)
                self.bg_image = ImageTk.PhotoImage(self.bg_image_original)
            except Exception as e:
                messagebox.showerror("エラー", f"背景画像の読み込みに失敗しました: {e}")

    def clear_bg_image(self):
        folder = self.map_name_entry.get().strip() or "my_map"
        save_bg = os.path.join(folder, "map.png")
        if os.path.exists(save_bg):
            try:
                os.remove(save_bg)
            except Exception as e:
                messagebox.showerror("エラー", f"背景画像の削除に失敗しました: {e}")
        self.bg_image = None
        self.bg_image_original = None
        self.draw_map()

    def create_new_map(self):
        new_map_name = simpledialog.askstring("新しいマップ", "新しいマップ名を入力してください")
        if new_map_name:
            self.map_name_entry.delete(0, tk.END)
            self.map_name_entry.insert(0, new_map_name)
            self.pins.clear()
            self.offset_x = 0
            self.bg_image = None
            self.bg_image_original = None
            self.current_file = ""
            self.draw_map()
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)


if __name__ == "__main__":
    root = tk.Tk()
    app = MapMakerApp(root)
    root.mainloop()