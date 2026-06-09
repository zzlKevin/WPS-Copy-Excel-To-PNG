# WPS-Copy-Excel-To-PNG

一个在wps复制表格后直接存储图片到指定位置的工具，无需中转微信复制为图片再另存为

## 功能特点

- Excel 复制的excel区域后，直接存储剪贴板的 PNG 图片到文件夹
- 支持自定义输出路径和自定义图片命名
- 图形界面操作，简单易用
- 支持托盘图标后台运行
- 支持Windows托盘气泡通知

## 技术栈

- Python 3.13
- PyInstaller 打包
- PIL/Pillow 图像处理
- pystray 系统托盘
- sv_ttk 现代化界面主题

## 安装依赖

```bash
pip install pyinstaller pillow pystray pywin32 sv-ttk
```

## 打包exe参考

```bash
& "D:\Program Files\Python313\python.exe" -m PyInstaller --onefile --noconsole --clean --collect-submodules PIL --collect-binaries PIL --hidden-import pystray --hidden-import win32clipboard --hidden-import win32ui --hidden-import win32gui --hidden-import win32con --hidden-import PIL._imaging --collect-data sv_ttk --noupx "wpsexceltopng.py"
```

