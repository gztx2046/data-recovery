<div align="center">

# 🔍 data-recovery

**取证数据恢复工具集 · Forensic Data Recovery Toolkit**

离线 · 纯 Python · 一个入口覆盖 SQLite / 微信 / iOS / Android

*Offline · Pure Python · One entry point for SQLite / WeChat / iOS / Android*

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](#-requirements--安装)
[![License](https://img.shields.io/badge/License-MIT-3DA639.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-6e7681)](#-requirements--安装)
[![Tests](https://img.shields.io/badge/Tests-21%20passing%20%2B%203%20optional-2ea043)](#-testing--测试)

**[English](#english)** | **[简体中文](#简体中文)**

[Features](#-features) • [Quick Start](#-quick-start) • [Testing](#-testing) • [Legal](#%EF%B8%8F-legal--compliance)

</div>

---

# English

## ✨ Features

- **SQLite deleted-record recovery** — `scripts/sqlite_recover.py`
  Page slack (unallocated region) + freeblock chain + WAL / rollback-journal historical pages + whole-file / frame deep carving. Schema-aware: reads `sqlite_master` and restores columns by name.
- **WeChat database decryption** — `scripts/wechat_key.py`
  Derives the key from `MD5(IMEI+UIN)`, auto-detects the page size from block 0, brute-forces multiple candidates, and verifies offline by checking for a valid SQLite header.
- **iOS backup recovery** — `scripts/ios_backup_recover.py`
  Scans by extension *and* by SQLite magic bytes, so hash-named, extension-less backup files are covered.
- **Android forensics** — `scripts/android_triage.py`
  Directory scanning plus no-root extraction via APK downgrade, with safety gates.
- **Unified entry point** — `scripts/recover_orchestrator.py`
  Auto-routes by input type: single file / directory / device.

## 📦 Requirements & Install

- Python 3.8+
- Optional: `cryptography` — only needed for WeChat decryption

```bash
# Core features use the standard library only — no dependencies required.
# WeChat decryption etc. needs cryptography (optional):
pip install cryptography
```

## 🚀 Quick Start

```bash
# 1) Unified entry point (recommended)
python scripts/recover_orchestrator.py chat.db --minlen 4 --maxout 200
python scripts/recover_orchestrator.py ./my_backup_dir                 # recursive directory scan
python scripts/recover_orchestrator.py --device --pkg com.tencent.mm   # device (best-effort)
python scripts/recover_orchestrator.py secret.db --decrypt-key <key>   # encrypted database

# 2) Core engine (standalone)
python scripts/sqlite_recover.py chat.db 4 200 [--wal X] [--journal X] \
       [--decrypt-key K] [--page-size N] [--json] [--no-deep-carve]

# 3) WeChat key
python scripts/wechat_key.py --imei <IMEI> --uin <UIN> --verify EnMicroMsg.db
python scripts/wechat_key.py --scan-backup <extracted-backup-root>     # scan for residual hex keys

# 4) iOS backup
python scripts/ios_backup_recover.py ./backup_dir --minlen 4 --json

# 5) No-root WeChat extraction (Avilla-style downgrade; destructive steps need --i-understand)
python scripts/apk_downgrade.py workflow          # review the recommended flow first
python scripts/apk_downgrade.py backup --i-understand --ab wx_before.ab   # back up first
python scripts/apk_downgrade.py downgrade --apk old-wechat.apk --i-understand
python scripts/apk_downgrade.py pull --i-understand --abe abe.jar
```

## 🧪 Testing

```bash
python tests/run_all.py          # 21 standard cases (no cryptography needed)
python tests/run_all.py --full   # + 3 cases that require cryptography
```

## 📊 Honest Self-Assessment

This toolkit self-rates **4.2** — but that is a **subjective score, containing a conflict of interest and backed by no authoritative source**. The real positioning:

- **Strong at**: one entry point, fully offline, pure standard library, SQLite + WeChat + iOS/Android in a single package, with honestly stated boundaries.
- **Not the strongest, item by item**: SQLite carving depth is below FQLite; no-root practice is below Avilla Forensics; interface completeness is below ios-forensics-mcp.

The full five-dimension scoring and community comparison live in `SKILL.md`. **All scores are the author's subjective judgement — benchmark with real samples to correct them.**

## ⚖️ Legal & Compliance

- Intended for **personal / authorized forensics use only**. Every decryption requires your own IMEI+UIN or a device you are authorized to examine — it cannot break into someone else's data out of thin air.
- Once publicly distributed, how others use it is outside the author's control. Do not use it to access someone else's device or data; the author assumes no liability for misuse.
- The code here is an **original rewrite**. The technical approach draws on FQLite / Avilla Forensics / ForensicsTool / ios-forensics-mcp / bring2lite (see `SKILL.md` §4) — no source code was copied.

## 📁 Project Structure

```
data-recovery/
├── SKILL.md                   # WorkBuddy skill doc (scoring / comparison / sources)
├── README.md                  # this file
├── LICENSE                    # MIT
├── .gitignore
├── scripts/
│   ├── sqlite_recover.py       # core recovery engine
│   ├── wechat_key.py           # WeChat key derivation + decryption
│   ├── ios_backup_recover.py   # iOS backup scanning
│   ├── android_triage.py       # Android directory + device
│   ├── apk_downgrade.py        # no-root downgrade extraction (safety-gated)
│   └── recover_orchestrator.py # unified entry point
└── tests/
    └── run_all.py              # synthetic-data regression (21 + 3 optional)
```

## 📜 License

[MIT](LICENSE).

---

# 简体中文

## ✨ 功能

- **SQLite 删除记录恢复** — `scripts/sqlite_recover.py`
  页未分配区(slack) + freeblock 链 + WAL / rollback journal 历史页 + 全文件 / 帧镜像深度雕刻。schema 感知：读取 `sqlite_master`，按列名还原。
- **微信数据库解密** — `scripts/wechat_key.py`
  用 `MD5(IMEI+UIN)` 派生密钥，块 0 自探测页大小，多候选穷举，离线校验是否解出合法 SQLite 头。
- **iOS 备份恢复** — `scripts/ios_backup_recover.py`
  按扩展名 **和** SQLite 魔数双重扫描，兼容哈希命名、无扩展名的备份文件。
- **Android 取证** — `scripts/android_triage.py`
  目录扫描 + 免 root 经 APK 降级取数，安全闸门齐全。
- **统一入口** — `scripts/recover_orchestrator.py`
  按输入类型自动路由：单文件 / 目录 / 设备。

## 📦 环境要求与安装

- Python 3.8+
- 可选：`cryptography`（仅微信解密需要）

```bash
# 核心功能纯标准库，无需任何依赖。
# 微信解密等需要 cryptography（可选）：
pip install cryptography
```

## 🚀 快速使用

```bash
# 1) 统一入口（推荐）
python scripts/recover_orchestrator.py chat.db --minlen 4 --maxout 200
python scripts/recover_orchestrator.py ./my_backup_dir                 # 目录递归扫描
python scripts/recover_orchestrator.py --device --pkg com.tencent.mm   # 设备(best-effort)
python scripts/recover_orchestrator.py secret.db --decrypt-key <密钥>  # 加密库

# 2) 核心引擎（单独调用）
python scripts/sqlite_recover.py chat.db 4 200 [--wal X] [--journal X] \
       [--decrypt-key K] [--page-size N] [--json] [--no-deep-carve]

# 3) 微信密钥
python scripts/wechat_key.py --imei <IMEI> --uin <UIN> --verify EnMicroMsg.db
python scripts/wechat_key.py --scan-backup <解压后的备份根目录>   # 扫残留 hex key

# 4) iOS 备份
python scripts/ios_backup_recover.py ./backup_dir --minlen 4 --json

# 5) 免 root 取微信数据（Avilla 式降级法，破坏性操作需 --i-understand）
python scripts/apk_downgrade.py workflow          # 先看推荐流程
python scripts/apk_downgrade.py backup --i-understand --ab wx_before.ab   # 先备份
python scripts/apk_downgrade.py downgrade --apk 旧版微信.apk --i-understand
python scripts/apk_downgrade.py pull --i-understand --abe abe.jar
```

## 🧪 测试

```bash
python tests/run_all.py          # 标准 21 项（无需 cryptography）
python tests/run_all.py --full   # 另加 3 项需 cryptography
```

## 📊 自评与社区对比（诚实说明）

本工具**自评 4.2**，但这是**主观分、含利益冲突、无权威来源**。真实定位是：

- **占优**：单入口、离线、纯标准库、SQLite + 微信 + iOS/Android 一包打尽，边界标注诚实。
- **不占优（逐项看）**：SQLite 雕刻深度低于 FQLite；免 root 实战低于 Avilla Forensics；接口完整度低于 ios-forensics-mcp。

完整五维评分与同类对比表见 `SKILL.md`。**评分均为作者主观判断，欢迎用真实样本跑分来纠偏。**

## ⚖️ 法律与合规边界

- 本工具定位为**个人 / 授权取证自用**；所有解密均需你自己的 IMEI+UIN 或已获授权的设备，无法凭空破解他人数据。
- 公开分发后，他人如何使用不在作者控制范围内。请勿用于未授权访问他人设备 / 数据，作者不承担任何滥用后果。
- 本仓库代码为**原创重写**，技术思路吸收自 FQLite / Avilla Forensics / ForensicsTool / ios-forensics-mcp / bring2lite（详见 `SKILL.md` §4），未复制其源码。

## 📁 目录结构

```
data-recovery/
├── SKILL.md                   # WorkBuddy 技能说明（含评分 / 对比 / 技术来源）
├── README.md                  # 本文件
├── LICENSE                    # MIT
├── .gitignore
├── scripts/
│   ├── sqlite_recover.py       # 核心恢复引擎
│   ├── wechat_key.py           # 微信密钥推导 + 解密
│   ├── ios_backup_recover.py   # iOS 备份扫描
│   ├── android_triage.py       # Android 目录 + 设备
│   ├── apk_downgrade.py        # 免 root 降级取数（安全闸门）
│   └── recover_orchestrator.py # 统一入口
└── tests/
    └── run_all.py              # 合成数据回归（21 项 + 3 项可选）
```

## 📜 许可证

[MIT](LICENSE)。
