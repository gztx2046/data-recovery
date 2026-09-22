<div align="center">

# 🔍 Exhumer

**掘尸人 · 取证数据恢复工具集**

*Forensic Data Recovery Toolkit*

**把删掉的数据，从数据库的坟里挖回来。**

*Digging deleted data back out of the grave.*

**一个给 AI 用的 Agent 技能** · 离线 · 纯 Python · 一个入口覆盖 SQLite / 微信 / iOS / Android

*An AI agent skill · Offline · Pure Python · One entry point for SQLite / WeChat / iOS / Android*

[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-SKILL.md-8957E5)](#-this-is-an-ai-agent-skill)
[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](#-requirements--install)
[![License](https://img.shields.io/badge/License-MIT-3DA639.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-6e7681)](#-requirements--install)
[![Tests](https://img.shields.io/badge/Tests-21%20passing%20%2B%203%20optional-2ea043)](#-testing)

**[English](#english)** | **[简体中文](#简体中文)**

[Agent Skill](#-this-is-an-ai-agent-skill) • [Features](#-features) • [Quick Start](#-quick-start) • [Testing](#-testing) • [Legal](#%EF%B8%8F-legal--compliance)

</div>

---

# English

## Why "Exhumer"?

To **exhume** is to dig something buried back out of the ground — the examiner's word for retrieving a body that has already been put away. This toolkit does exactly that to deleted data: the database has already closed the lid, and we dig the records back out of the page slack, freeblocks and WAL history underneath.

## 🤖 This is an AI agent skill

This repository is not just a CLI toolkit — it is packaged as an **agent skill**: a capability bundle that an AI assistant loads and invokes on the user's behalf. Its **primary consumer is the agent**; running the scripts by hand is the secondary path.

Three layers, three audiences:

| File | Audience | Role |
|---|---|---|
| `SKILL.md` | the AI agent | Machine-facing entry. The YAML frontmatter (`name`, `description`) is what the agent reads to decide **whether to load** the skill; the body carries decision rules, scenario routing, refusal boundaries and safety gates. |
| `scripts/*.py` | the AI agent (or you) | The executable engine. Each script runs standalone, takes plain CLI arguments, and can emit machine-readable `--json`. |
| `README.md` | humans | This overview page. |

**Installing it into an agent.** Copy the whole folder into the agent's skills directory so the folder name matches the `name:` field in the `SKILL.md` frontmatter (`exhumer`). There is no build step and no required dependency (only optional `cryptography`, for WeChat decryption). Agents in the WorkBuddy / CodeBuddy family discover skills from a `skills/` root; any agent that can read a file and run a shell command can use this repo as-is.

**What makes it agent-friendly**

- **One entry, auto-routed** — `recover_orchestrator.py` decides single file / directory / device from the input, so the agent never has to pick the right tool first.
- **Machine-readable output** — the recovery scripts support `--json`, so results are parsed rather than screen-scraped.
- **Hard safety gates** — destructive steps (device backup, APK downgrade, archive extraction) refuse to run without an explicit `--i-understand`. This exists specifically so an agent cannot take a risky action on its own initiative.
- **Refusal boundaries written into `SKILL.md`** — the skill tells the agent when **not** to proceed (no third-party devices, no data it is not authorized to examine). These boundaries are instructions the model executes, not decorative prose.

**When an agent should load this skill** — the trigger conditions for the agent's decision layer:

- the user wants deleted rows/records recovered from a `.db` / SQLite file, or the database looks empty;
- the user supplies their own IMEI + UIN together with an `EnMicroMsg.db` and asks to unlock or inspect it;
- the user points at an iOS backup folder or an Android export directory and wants deleted data back;
- the user has an Android device they are authorized to examine and wants app data pulled without root.

Conversely, when the user cannot show ownership or authorization, the skill makes the agent **stop** — that is designed behaviour, not a missing feature.

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
exhumer/
├── SKILL.md                   # agent-facing entry: frontmatter + decision rules + scoring
├── README.md                  # this file (for humans)
├── LICENSE                    # MIT
├── .gitignore
├── scripts/                   # the engine an agent invokes
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

## 为什么叫 Exhumer？

**exhume** 是法医的词——把已经埋进土里的东西重新掘出来验。这套工具对删掉的数据做的事一模一样：数据库那边已经把盖子盖上了，它从底下的页未分配区、freeblock、WAL 历史页里，把记录重新掘出来。

## 🤖 这是一个给 AI 用的 Agent 技能

这个仓库不只是"给人敲命令行的工具"，它同时是一个 **Agent 技能包**——一份交给 AI 助手加载、由 AI 代你调用的能力包。它的**第一使用者是 AI**，人手动跑脚本是第二路径。

三层结构，三种读者：

| 文件 | 读者 | 作用 |
|---|---|---|
| `SKILL.md` | AI | 面向机器的入口。开头的 `name` / `description` 是 AI 用来判断**要不要加载**这个技能的元信息；正文写的是决策规则、场景路由、拒答边界和安全闸门。 |
| `scripts/*.py` | AI（或你） | 可执行的引擎。每个脚本都能独立跑，参数简单，支持 `--json` 输出机器可读结果。 |
| `README.md` | 人 | 就是本页，给人看的概览。 |

**怎么装进一个 AI**：把整个文件夹放进该 AI 的技能目录，文件夹名与 `SKILL.md` 开头的 `name`（`exhumer`）保持一致即可。没有构建步骤、没有必需依赖（只有微信解密需要可选的 `cryptography`）。WorkBuddy / CodeBuddy 这类 AI 从 `skills/` 目录发现技能；任何能读文件、能执行命令的 AI 都能直接用本仓库，不用改代码。

**为什么它对 AI 友好**

- **一个入口自动分流**——输入是文件、目录还是设备，由 `recover_orchestrator.py` 自己判断，AI 不需要先猜该用哪个脚本。
- **输出机器可读**——恢复脚本都支持 `--json`，AI 直接解析结果，不用去"读屏幕"。
- **硬安全闸门**——设备备份、降级安装、解压这些有风险的步骤，没有显式加上 `--i-understand` 一律拒绝执行。这条是专门用来**不让 AI 自作主张**的。
- **拒答边界写进了 `SKILL.md`**——技能明确告诉 AI 什么时候**不该动手**（非本人设备、无授权的数据）。这些边界是写给模型执行的指令，不是给人看的装饰文字。

**AI 应该在什么时候加载它**（触发条件）：

- 用户要恢复某个 `.db` 文件里被删的记录，或者这个库看起来是空的；
- 用户提供自己的 IMEI + UIN 和一个 `EnMicroMsg.db`，要求解锁 / 查看；
- 用户指着一个 iOS 备份目录或 Android 导出目录，想把删掉的数据找回来；
- 用户有一台自己有权处理的 Android 设备，想免 root 取出应用数据。

反过来，当用户拿不出归属 / 授权依据时，这个技能会让 AI 停手——这是**设计好的行为**，不是缺功能。

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
exhumer/
├── SKILL.md                   # 面向 AI 的入口：元信息 + 决策规则 + 评分
├── README.md                  # 本文件（给人看）
├── LICENSE                    # MIT
├── .gitignore
├── scripts/                   # AI 实际调用的引擎
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
