# MAA 作战日报

明日方舟小助手（MAA）日志解析工具，把自动化刷图记录变成一份可视化的"作战日报"。

## 功能

- 自动解析 MAA 的 `gui.log`，统计理智消耗、材料掉落、肉鸽进度
- 深色紫色风格 HTML 报告，包含：
  - 顶部统计总览（理智/战斗天数/肉鸽次数/材料种类）
  - 周度理智消耗柱状图
  - 材料仓库网格（图标 + 数量）
  - 理智消耗关卡排名
  - 肉鸽深度分析（通关率、难度分层、最近记录）
  - 每日详情（材料掉落、肉鸽记录）
- 本地 Web UI 操作界面，不需要命令行
- 单文件 exe，双击即用，不需要安装 Python

## 使用方法

### 直接运行 exe（推荐）

1. 下载 `MAA作战报告.exe`
2. 双击运行，会自动打开浏览器
3. 选择你的 MAA 日志文件（通常在 `MAA目录/debug/gui.log`）
4. 点击"生成日报"
5. 点击"打开报告"查看

> **数据安全**：所有数据都在本地处理，不会上传任何信息。历史记录保存在 `%APPDATA%\MAA作战报告\` 目录。

### 从源码运行

```bash
# 需要 Python 3.8+
pip install pillow
python maa_report.py
```

### 自行打包 exe

```bash
pip install pyinstaller pillow
pyinstaller --onefile --windowed --name "MAA作战报告" \
  --icon "images/kaltsit.ico" \
  --add-data "images;images" \
  maa_report.py
```

## 目录结构

```
├── maa_report.py    # 主程序（单文件，约55KB）
├── images/          # 材料图标（87个PNG）
├── kaltsit.ico      # 程序图标
└── README.md
```

## 数据来源

- 材料图标来自 [PRTS Wiki](https://prts.wiki/)
- 程序图标为凯尔希Q版同人图

## 免责声明

本工具为第三方辅助程序，与鹰角网络、MAA 官方无关。
所有数据均来自用户本地 MAA 日志，不收集、不上传任何个人信息。
