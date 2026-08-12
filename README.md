# iiSU-CN-Scraper

中文 ROM 刮削工具 — macOS / Windows / Android 通用。

## 解决的问题

国内 ROM 文件名通常包含汉化组标签、版本号、语言标记等杂乱信息，导致刮削器无法匹配。本工具：

```
乱码文件名 → LLM 语义清洗 → Bangumi (中文) / TGDB (英文) → gamelist.xml + 封面
```

**绝不修改原始 ROM 文件。**

---

## macOS 快速开始（推荐）

```bash
# 1. 确保已安装 Python 3.10+（macOS 自带或从 python.org 安装）

# 2. 一键启动（自动检测/安装依赖）
./run_mac.sh

# 或手动方式：
python3 -m pip install -r requirements.txt
python3 main.py
```

首次使用：设置页填入 LLM API Key（推荐 DeepSeek），点击扫描 → 选择 ROM 目录 → 开始刮削。

**配置文件位置**（macOS）：
```
~/Library/Application Support/iiSU-CN-Scraper/config.json
```

---

## Windows 桌面端

```bash
pip install -r requirements.txt
python main.py
```

**配置文件位置**：`%APPDATA%/iiSU-CN-Scraper/config.json`

---

## Android 掌机

1. 下载 [最新 APK](../../releases/latest)
2. 安装后授予「所有文件访问」权限
3. 填入 API 密钥即可使用

---

## 打包成原生 .app（macOS）

```bash
# 需先安装 Flutter SDK: https://docs.flutter.dev/get-started/install/macos
flet build macos
# 产物: build/macos/iiSU CN Scraper.app
```

打包后可直接双击运行，或拖入「应用程序」文件夹。

---

## 数据源

| 数据源 | 用途 | 免费额度 |
|--------|------|----------|
| **Bangumi** | 中文游戏信息（首选） | 免费 |
| **TheGamesDB** | 英文备用补充 | 免费 |
| **LLM** | ROM 文件名语义清洗 | 按量付费（推荐 DeepSeek，极便宜） |

---

## 使用流程

```
打开 App
  → 自动扫描 ROM 目录（桌面端可手动浏览文件夹）
  → 填入 LLM API Key
  → 勾选要刮削的 ROM
  → 点击「开始刮削」
  → gamelist.xml + 封面自动生成在原 ROM 目录
```

---

## 输出结构

```
ROMs/GBA/
├── gamelist.xml              ← 自动生成/更新
└── downloaded_media/
    └── covers/               ← 封面 (.png)
```

---

## iiSU 兼容性

生成的 `gamelist.xml` 遵循 **ES-DE / EmulationStation** 标准，iiSU 可直接识别。

---

## 项目结构

```
iiSU-CN-Scraper-master/
├── main.py                  ← GUI 主入口（Flet 框架，macOS/Win/Android 通用）
├── run_mac.sh               ← macOS 一键启动脚本
├── config.json              ← CLI 配置示例（GUI 版用内置设置页配置）
├── requirements.txt         ← 运行依赖
├── pyproject.toml           ← Flet 打包配置（macOS .app / Android apk）
└── modules/
    ├── llm_normalizer.py    ← LLM 语义清洗（乱码文件名 → 标准游戏名）
    ├── bangumi_fetcher.py   ← Bangumi (bgm.tv) 中文游戏数据源
    ├── tgdb_fetcher.py      ← TheGamesDB 英文备用数据源
    ├── llm_client.py        ← 轻量级 OpenAI 兼容客户端（可选）
    └── xml_builder.py       ← ES-DE 标准 gamelist.xml 生成
```
