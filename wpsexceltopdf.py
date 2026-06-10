import os
import sys
import time
import io
import threading
import queue
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import sv_ttk                                  # Win11 风格主题
import win32clipboard
import win32ui
import win32gui
import win32con
from PIL import Image, ImageDraw

from pystray import Icon, Menu, MenuItem

# ----------------------------- 剪贴板工具函数 -----------------------------
def get_clipboard_format_names():
    names = []
    try:
        win32clipboard.OpenClipboard()
        fmt = 0
        while True:
            fmt = win32clipboard.EnumClipboardFormats(fmt)
            if fmt == 0:
                break
            try:
                name = win32clipboard.GetClipboardFormatName(fmt)
            except:
                name = ""
            if name:
                names.append(name)
    finally:
        win32clipboard.CloseClipboard()
    return names

def is_wps_clipboard():
    for name in get_clipboard_format_names():
        upper = name.upper()
        if "KINGSOFT" in upper or "WPS" in upper:
            return True
    return False

def hbitmap_to_pil(hbitmap):
    bmp = win32ui.CreateBitmap()
    bmp.Attach(hbitmap)
    info = bmp.GetInfo()
    width, height = info['bmWidth'], info['bmHeight']
    bmp.Detach()

    hdc = win32gui.GetDC(0)
    mfc_dc = win32ui.CreateDCFromHandle(hdc)
    mem_dc = mfc_dc.CreateCompatibleDC()
    bmi = win32gui.GetObject(hbitmap, win32con.BITMAP)
    bits = bytearray(bmi.bmWidthBytes * bmi.bmHeight)
    win32gui.GetBitmapBits(hbitmap, len(bits), bits)
    mem_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(0, hdc)

    return Image.frombuffer('RGB', (width, height), bytes(bits), 'raw', 'BGRX', 0, 1)

def get_image_from_clipboard():
    try:
        win32clipboard.OpenClipboard()
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIBV5):
            data = win32clipboard.GetClipboardData(win32clipboard.CF_DIBV5)
            win32clipboard.CloseClipboard()
            return Image.open(io.BytesIO(data))
        elif win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
            data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
            win32clipboard.CloseClipboard()
            return Image.open(io.BytesIO(data))
        elif win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_BITMAP):
            hbitmap = win32clipboard.GetClipboardData(win32clipboard.CF_BITMAP)
            win32clipboard.CloseClipboard()
            return hbitmap_to_pil(hbitmap)
        else:
            win32clipboard.CloseClipboard()
            return None
    except:
        try:
            win32clipboard.CloseClipboard()
        except:
            pass
        return None

# ----------------------------- 自定义文件名对话框 -----------------------------
class FilenameDialog(tk.Toplevel):
    def __init__(self, parent, extension=".png"):
        super().__init__(parent)
        self.result = None
        self.extension = extension
        self.title("保存图片" if extension == ".png" else "保存 PDF")
        self.geometry("380x150")
        self.resizable(False, False)
        self.configure(bg="#2B2B2B" if sv_ttk.get_theme() == "dark" else "#F3F3F3")

        self.attributes('-topmost', True)
        self.grab_set()
        self.focus_force()

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        prompt = f"请输入文件名（不含扩展名，留空则自动命名）：\n（将自动添加 {self.extension}）"
        ttk.Label(frame, text=prompt).pack(anchor=tk.W, pady=(0,5))

        self.name_var = tk.StringVar(value="")
        self.entry = ttk.Entry(frame, textvariable=self.name_var, width=40)
        self.entry.pack(fill=tk.X, pady=(0,15))
        self.entry.focus_set()

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="确定", command=self._on_confirm, style="Accent.TButton").pack(side=tk.RIGHT, padx=(5,0))
        ttk.Button(btn_frame, text="取消", command=self._on_cancel).pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", lambda e: self._on_confirm())
        self.bind("<Escape>", lambda e: self._on_cancel())

        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _on_confirm(self):
        name = self.name_var.get().strip()
        self.result = name if name else None
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()

# ----------------------------- GUI + 托盘 主程序 -----------------------------
class WpsImageSaverApp:
    def __init__(self, root):
        self.root = root
        root.title("WPS 表格图片 / PDF 自动保存")
        root.geometry("680x580")
        root.minsize(600, 480)

        sv_ttk.set_theme("dark" if self._is_system_dark() else "light")

        self.save_dir = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Desktop", "WPS截图"))
        self.rename_enabled = tk.BooleanVar(value=False)
        self.output_format = tk.StringVar(value="PNG")   # ★ 新增：保存格式
        self.monitoring = False
        self.monitor_thread = None
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()

        self.tray_icon = None
        self.tray_running = False

        self._build_ui()
        self._poll_queue()

        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

    def _is_system_dark(self):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        except:
            return False

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- 保存设置卡片 ---
        dir_frame = ttk.LabelFrame(main_frame, text="保存设置", padding=10)
        dir_frame.pack(fill=tk.X, pady=(0,10))

        # 第一行：路径选择
        ttk.Label(dir_frame, text="图片保存路径：").grid(row=0, column=0, sticky=tk.W, pady=(0,5))
        path_entry = ttk.Entry(dir_frame, textvariable=self.save_dir, width=60)
        path_entry.grid(row=1, column=0, padx=(0,5), sticky=tk.EW)
        ttk.Button(dir_frame, text="浏览...", command=self._browse_folder).grid(row=1, column=1)
        ttk.Button(dir_frame, text="📂 打开文件夹", command=self._open_folder).grid(row=1, column=2, padx=(5,0))
        dir_frame.columnconfigure(0, weight=1)

        # 第二行：保存格式选择 ★
        fmt_frame = ttk.Frame(dir_frame)
        fmt_frame.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(10,0))
        ttk.Label(fmt_frame, text="保存格式：").pack(side=tk.LEFT)
        fmt_combo = ttk.Combobox(fmt_frame, textvariable=self.output_format,
                                 values=["PNG", "PDF"], state="readonly", width=6)
        fmt_combo.pack(side=tk.LEFT, padx=(5,15))
        # 重命名选项
        ttk.Checkbutton(
            fmt_frame,
            text="每次复制后弹出窗口自定义文件名",
            variable=self.rename_enabled
        ).pack(side=tk.LEFT)

        # --- 控制栏 ---
        ctrl_frame = ttk.Frame(main_frame)
        ctrl_frame.pack(fill=tk.X, pady=(0,10))

        self.start_btn = ttk.Button(ctrl_frame, text="开始监控", style="Accent.TButton", command=self._toggle_monitoring)
        self.start_btn.pack(side=tk.LEFT, padx=(0,10))

        self.status_label = ttk.Label(ctrl_frame, text="● 未启动", foreground="gray")
        self.status_label.pack(side=tk.LEFT)

        # --- 日志区 ---
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, height=12, width=80, state=tk.DISABLED, wrap=tk.WORD,
                                bg="#1E1E1E" if sv_ttk.get_theme() == "dark" else "#FAFAFA",
                                fg="#D4D4D4" if sv_ttk.get_theme() == "dark" else "#1E1E1E",
                                insertbackground='white', borderwidth=0)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="选择保存文件夹")
        if folder:
            self.save_dir.set(folder)

    def _open_folder(self):
        path = self.save_dir.get().strip()
        if not path:
            messagebox.showinfo("提示", "请先设置保存目录")
            return
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件夹：{e}")

    def _toggle_monitoring(self):
        if not self.monitoring:
            path = self.save_dir.get().strip()
            if not path:
                messagebox.showerror("错误", "请先设置保存目录")
                return
            try:
                os.makedirs(path, exist_ok=True)
            except:
                messagebox.showerror("错误", f"无法创建目录：{path}")
                return

            self.monitoring = True
            self.stop_event.clear()
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()

            self.start_btn.configure(text="停止监控")
            self.status_label.configure(text="● 监控中", foreground="#13A10E")
            self._log("监控已启动")
            if not self.tray_icon:
                self._start_tray()
        else:
            self.monitoring = False
            self.stop_event.set()
            self.start_btn.configure(text="开始监控")
            self.status_label.configure(text="● 已停止", foreground="gray")
            self._log("监控已停止")

    # ------------------- 托盘相关 -------------------
    def _create_tray_image(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill=(0, 200, 83))
        draw.polygon([(18, 32), (28, 44), (46, 20)], fill="white")
        return img

    def _tray_thread(self):
        menu = Menu(
            MenuItem("显示窗口", self._show_window, default=True),
            MenuItem("打开保存文件夹", self._open_folder),
            MenuItem("退出", self._quit_from_tray)
        )
        self.tray_icon = Icon("WPS_Saver", self._create_tray_image(), "WPS 表格自动保存", menu)
        self.tray_icon.run()

    def _start_tray(self):
        th = threading.Thread(target=self._tray_thread, daemon=True)
        th.start()

    def _show_window(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def _on_window_close(self):
        if self.monitoring:
            self.root.withdraw()
        else:
            self._full_quit()

    def _quit_from_tray(self, icon=None, item=None):
        self._full_quit()

    def _full_quit(self):
        self.monitoring = False
        self.stop_event.set()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()
        os._exit(0)

    # ------------------- 监控与通知 -------------------
    def _log(self, msg):
        self.msg_queue.put(("LOG", msg))

    def _send_tray_notification(self, title, message):
        if self.tray_icon:
            try:
                self.tray_icon.notify(message, title=title)
            except:
                pass

    def _request_filename(self, extension):
        """弹出命名窗口，返回用户输入的名称（可能为 None）"""
        event = threading.Event()
        result_container = []
        self.msg_queue.put(("REQUEST_FILENAME", event, result_container, extension))
        event.wait()
        if result_container:
            return result_container[0]
        return None

    def _monitor_loop(self):
        last_seq = win32clipboard.GetClipboardSequenceNumber()
        while not self.stop_event.is_set():
            time.sleep(0.2)
            if self.stop_event.is_set():
                break
            try:
                current_seq = win32clipboard.GetClipboardSequenceNumber()
                if current_seq == last_seq:
                    continue
                last_seq = current_seq

                if not is_wps_clipboard():
                    continue

                img = get_image_from_clipboard()
                if img is None:
                    self._log("检测到 WPS 复制，但未找到图片数据")
                    continue

                # 获取当前格式设置
                fmt = self.output_format.get().upper()   # PNG 或 PDF
                ext = ".png" if fmt == "PNG" else ".pdf"
                save_format = "PNG" if fmt == "PNG" else "PDF"

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                default_name = f"WPS_{timestamp}"

                base_name = default_name
                if self.rename_enabled.get():
                    user_name = self._request_filename(ext)
                    if user_name:
                        base_name = user_name.strip()

                save_path = os.path.join(self.save_dir.get(), f"{base_name}{ext}")

                # ★ 根据格式保存
                if save_format == "PNG":
                    img.save(save_path, "PNG")
                else:  # PDF
                    # Pillow 的 PDF 保存会自动将图片嵌入为整页
                    img.save(save_path, "PDF", resolution=100.0)

                self._log(f"已保存：{os.path.basename(save_path)}")
                self._send_tray_notification(
                    "文件已保存",
                    f"{os.path.basename(save_path)}"
                )

            except Exception as e:
                self._log(f"出错：{e}")

    # ------------------- 队列轮询 -------------------
    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                if msg[0] == "LOG":
                    self._write_log(msg[1])
                elif msg[0] == "REQUEST_FILENAME":
                    event, result_container, extension = msg[1], msg[2], msg[3]
                    dialog = FilenameDialog(self.root, extension)
                    self.root.wait_window(dialog)
                    result_container.append(dialog.result)
                    event.set()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _write_log(self, msg):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

# ----------------------------- 启动入口 -----------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = WpsImageSaverApp(root)
    root.mainloop()