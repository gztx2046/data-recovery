---
name: exhumer
description: Exhumer（掘尸人）——取证级数据恢复 Agent 技能。SQLite 删除记录恢复（页 slack/freeblock/WAL/journal + 全文件深度雕刻）、微信 EnMicroMsg.db 密钥推导与解密、iOS 备份与 Android 导出目录批量恢复，单一编排入口自动路由。纯标准库，可选 cryptography 做 SQLCipher 解密。
version: 2.2
---

# Exhumer（掘尸人）· 取证数据恢复工具集 v2.2

> **名字由来**：`exhume` 是法医的词——把埋进土里的东西重新掘出来验。这套工具对删掉的数据做的事一模一样：数据库那边已经把盖子盖上了，它从底下的页未分配区、freeblock、WAL 历史页里，把记录重新掘出来。
> （原名 `data-recovery` 在 GitHub 上有 1718 个近名仓库，辨识度为零，故更名。详见 §7。）

## 0. 这是什么：一个给 AI 用的 Agent 技能

本技能的**第一使用者是 AI agent**（WorkBuddy / CodeBuddy 这类能读文件、能执行命令的助手），人手动敲命令行是第二路径。
三层分工：

| 文件 | 读者 | 作用 |
|---|---|---|
| 本文件 `SKILL.md` | **AI** | 面向机器的入口：开头 `name` / `description` 供 AI 判断**要不要加载**；正文是决策规则、场景路由、拒答边界、安全闸门。 |
| `scripts/*.py` | **AI**（或人） | AI 实际调用的引擎。独立可跑，参数从简，支持 `--json` 机器可读输出。 |
| `README.md` | 人 | 给人看的概览页（GitHub 落地页）。 |

### 加载时机（AI 决策层触发条件）

- 用户要恢复 `.db` / SQLite 文件里被删的记录，或该库看起来是空的；
- 用户给出**自己的** IMEI + UIN 和一个 `EnMicroMsg.db`，要求解锁 / 查看；
- 用户指着 iOS 备份目录或 Android 导出目录，要找回被删数据；
- 用户有一台**自己有权处理**的 Android 设备，想免 root 取出应用数据。

反向约束：用户拿不出归属 / 授权依据时**必须停手**——这是设计行为，不是缺功能。

### 给 AI 的三条硬约定

1. **破坏性操作一律加 `--i-understand`**：`apk_downgrade.py` 的 backup / downgrade / extract / pull 与设备拉取，缺此参数直接拒绝执行，AI 不得代用户默认同意。
2. **先确认交付对象再动手**：涉及"恢复哪台设备 / 哪个库 / 恢复给谁"缺项时先问，不许拿"最像的那个"顶替。
3. **结果据实汇报**：恢复 0 条就是 0 条，不得把"未命中"包装成"已完成"。

一套**可命令行直接跑**的取证恢复脚本，覆盖四类场景：

1. **SQLite 删除恢复**：普通 DELETE 后残留在页 slack / freeblock 的记录、WAL/rollback journal 里的历史页；
2. **微信 EnMicroMsg.db**：由 IMEI+UIN 推导 SQLCipher 密钥并离线校验；
3. **iOS 备份 / Android 导出目录**：递归扫描（含真实备份里 SHA1 哈希命名、无扩展名的库），逐个恢复；
4. **统一编排入口**：一个命令按输入类型自动路由，不用记多个工具。

设计目标：把社区里分散的单点强工具，**取长补短揉成一套**，且**不依赖图形界面、不依赖联网、不依赖越权**。

---

## 1. 社区工具对比与“取长补短”结果（带评分）

评分维度（每项 1-5，附一句话理由）；总分 = 五项平均（保留一位小数）：

- **可操作性**：能不能直接抄去用，还是要大量改写
- **完成度**：是否自洽、有没有缺关键环节
- **独特性**：网上是否一搜一大把，还是真有独占信息
- **时效性**：会不会很快过期
- **坑位**：有没有隐藏前提、未验证假设、作者藏私引流

| 社区工具 | 可操作 | 完成度 | 独特性 | 时效性 | 坑位 | 总分 | 一句话 |
|---|---|---|---|---|---|---|---|
| FQLite | 5 | 5 | 4 | 4 | 5 | **4.6** | SQLite 删除恢复最稳、深度领先本项目；只做 SQLite、命令行交互弱 |
| Avilla Forensics | 5 | 4 | 4 | 4 | 5 | **4.4** | 无 root 读 app 私有数据靠 APK 降级，手法独家、实战经验足，但只对老系统 |
| IPED | 4 | 5 | 3 | 4 | 5 | **4.2** | 工业级桌面 GUI，强但重、学习成本高 |
| MVT | 4 | 4 | 4 | 4 | 4 | **4.0** | 移动取证的标杆，但偏 Android/iOS 基线、不专攻删记录 |
| ForensicsTool | 4 | 4 | 3 | 4 | 5 | **4.0** | 微信 key 思路有用，但脚本散、维护差 |
| ios-forensics-mcp | 5 | 4 | 4 | 5 | 5 | **4.6** | 原生 agent 接口，思路最对路但只覆盖 iOS |
| bring2lite | 3 | 4 | 3 | 3 | 4 | **3.4** | 学术向 SQLite 雕刻，论文味重、难落地 |
| Undark | 4 | 3 | 3 | 2 | 4 | **3.2** | 老牌但停更、只做最浅层恢复 |

> 注：上表均为本工具集的**主观自评对照**，存在为抬高本项目而压低竞品的利益冲突；无权威来源，可信度有限，仅供内部参照。其中 FQLite / Avilla / ForensicsTool / bring2lite / Undark 的分值已较早期版本上调至不刻意压低的合理区间（早期版本把 FQLite 压到 4.0、Avilla 压到 3.6，实为注水分）。

**本工具集（Exhumer v2.2）评分：**

| 维度 | 分 | 理由 |
|---|---|---|
| 可操作性 | 5 | 脚本开箱即跑，纯标准库；一条编排命令覆盖全部场景 |
| 完成度 | 4 | 主干齐全；溢出页大记录未重组、内部页扫描偏移瑕疵、iOS 加密备份不覆盖（均为 P2，未做） |
| 独特性 | 4 | “单入口全包”确实罕见，但拆开看每一项都有更强的同行单品 |
| 时效性 | 4 | SQLite 格式稳定；但微信取数路径会随版本衰减，且没有持续维护节奏 |
| 坑位 | 4 | 审计出的 P0/P1 已全部闭环（tar 穿越、测试诚信、AES-128 标注、失败报成功）；密码学仅自洽验证、对比表压分隐患已在 v2.2 修正为诚实区间 |

**总分 = (5+4+4+4+4)/5 = 4.2**

**结论：可作为 FQLite 的上游/补充直接使用，但综合评分不高于 FQLite（4.6）与 ios-forensics-mcp（4.6）。** 本项目真正的占优维度是“单入口、离线、纯标准库、SQLite+微信+iOS/Android 全包”，但拆开看：SQLite 恢复深度仍低于 FQLite、免 root 实战经验低于 Avilla、接口完整度低于 ios-forensics-mcp——自评 4.2 是“整合便利性”维度的分，不是“各项都最强”的分。v2.1 把上一版的三个弱项全部补上——免 root 降级从“只给思路”变成**安全闸门齐全的 `apk_downgrade.py`**；纯 SQLite 雕刻深度从“只扫 slack/freeblock”扩展到**全文件/帧镜像深度雕刻**；微信密钥从“单一页大小”变成**块 0 页大小自探测 + 多候选穷举**。v2.2 据独立审计再修四类问题（**P0/P1 全部闭环**）：① 解压 tar 路径穿越（CVE-2007-4559）防护；② 测试把“跳过项”算通过的诚信问题，改为明确标记 SKIP 且不计入通过；③ 微信加密原错标注 AES-256，更正为 **AES-128**（MD5 16 字节摘要）；④ 备份/解压失败时不再返回假目录谎报成功。仍保留两条诚实边界：① 微信密钥来源轮换在无 root 下本质上仍受 IMEI+UIN 限制（完全突破需 root/Frida，已在 §5 标注）；② 免 root 降级与真机拉取已在 mock 层端到端验证命令构造与安全闸门，但真机实战未跑（需真实设备+旧版 APK 才能闭环）。

**上一版缺失项（已全部闭环）**：① 自动 APK 降级脚本 → 落地为 `apk_downgrade.py`（备份优先、降级保留数据、解压、安全闸门）；② 微信 7.x+ 密钥轮换 → 以“多页大小 + 多候选”加固，并诚实标注无 root 下的来源上限；③ 真机 Android 拉取 → `android_triage.pull_device` 接通 `apk_downgrade` 备份路径，未确认操作一律拒绝。
**仍存的存疑/待实跑项**：① Avilla 免 root 降级在 Android 12+ 实际成功率需真机验证；② 通用 SQLCipher（带 KDF/HMAC）未实现——刻意不做，避免写出“能跑但解不对”的错误加密实现，详见 `wechat_key.py` 注释；③ iOS 加密备份（密钥包 `Manifest.plist`）未覆盖。

---

## 2. 文件结构

```
exhumer/
├── SKILL.md
├── scripts/
│   ├── sqlite_recover.py       核心引擎：删除记录恢复 + WAL/journal + 深度雕刻 + 可选解密
│   ├── wechat_key.py           微信 EnMicroMsg.db 密钥推导（多候选+多页大小）+ 离线校验
│   ├── apk_downgrade.py        Android 免 root 取微信数据（Avilla 式降级法，安全闸门齐全）
│   ├── ios_backup_recover.py   iOS 备份/目录 批量恢复（扩展名 + 魔数扫描）
│   ├── android_triage.py       Android 导出目录恢复 + adb 设备检查 + 设备拉取
│   └── recover_orchestrator.py 统一入口：单文件/目录/设备 自动路由
└── tests/
    └── run_all.py             合成数据回归（标准 21 项全过 + 3 项因缺 cryptography 标记 SKIP；--full 共 26 项全过）
```

> 注意：本工具集**不触碰任何在线服务、不越权、不连接设备做非法操作**。所有恢复都在你本机已能读到的文件上做。

---

## 3. 各脚本用法

### 3.1 统一入口（首选）
```bash
# 单个 SQLite 文件
python scripts/recover_orchestrator.py chat.db --minlen 4 --maxout 200
# 目录（iOS 备份 / Android 导出）——自动递归扫描
python scripts/recover_orchestrator.py ./my_backup_dir
# 设备（best-effort，无 root 受限）
python scripts/recover_orchestrator.py --device --pkg com.tencent.mm
# 加密库：先解出密钥，再用 --decrypt-key 喂入
python scripts/recover_orchestrator.py secret.db --decrypt-key <16进制或原始密钥>
```

### 3.2 单独调用核心引擎
```bash
python scripts/sqlite_recover.py chat.db 4 200 [--wal X] [--journal X] [--decrypt-key K] [--page-size N] [--json] [--no-deep-carve]
```
- `--wal X`：指定 WAL 文件（不指定则自动找 `<db>-wal`）
- `--decrypt-key K`：SQLCipher 密钥（16 进制字符串或原始字节的 hex），需要 `cryptography`
- 深度雕刻默认开启：对整个库字节 + 每张 WAL/Journal 帧镜像做全文字符串扫描，捕获游离在 slack/freeblock 之外的残留（置信度低，单独以 `来源:carve` 标记）。`--no-deep-carve` 可关。

### 3.3 微信密钥
```bash
python scripts/wechat_key.py --imei <IMEI> --uin <UIN> --verify EnMicroMsg.db
python scripts/wechat_key.py --pull            # 从已连接设备 best-effort 抓 IMEI/UIN
python scripts/wechat_key.py --imei <IMEI> --uin <UIN> --export-env
python scripts/wechat_key.py --scan-backup <解压后的备份根目录>   # 扫描可能残留的 hex key
```
- `verify` 现在做**块 0 页大小自探测 + 多候选穷举**：先解密第 1 块（页号 IV 使其与页大小无关）确认 magic 并读出真实页大小，再全量解密，避免 4096 假阳性。
- 仍限 legacy 模式（密钥=MD5 原始摘要、无 HMAC）。通用 SQLCipher（带 KDF/HMAC）故意不做（见 §5 边界）。

### 3.4 批量目录
```bash
python scripts/ios_backup_recover.py ./backup_dir --minlen 4 --json
```

### 3.5 免 root 取微信数据（Avilla 式降级法）
```bash
python scripts/apk_downgrade.py check                 # 确认 adb 与设备
python scripts/apk_downgrade.py version               # 读微信版本
python scripts/apk_downgrade.py backup --i-understand --ab wx_before.ab   # 先备一份当前数据
python scripts/apk_downgrade.py downgrade --apk 旧版微信.apk --i-understand  # 降级保留数据
python scripts/apk_downgrade.py pull --i-understand --abe abe.jar           # backup+解压
python scripts/apk_downgrade.py workflow              # 打印推荐流程
```
- **安全红线**：`backup` / `downgrade` / `pull` 等任何有数据风险的操作都必须显式 `--i-understand` 才执行，否则一律拒绝并打印提示；`downgrade` 用的是 `adb install -r -d`（保留数据、允许降级）。
- 解压 `.ab` 需要 Android Backup Extractor（`abe.jar`）+ Java；缺失时只给指引不擅自执行。

---

## 4. 吸收的强技术（取长补短落点）

### A. 无 root 读 app 私有数据：APK 降级（吸收 Avilla Forensics，v2.1 已自动化）
Android 从 4.x 起 `adb backup` 默认被 app 的 `android:allowBackup` 限制。Avilla 的独家手法：
1. 找到目标 app 的**旧版本 APK**（当时 `allowBackup=true`、且没强制加密备份）；
2. `adb install -r -d wechat_old.apk` 降级安装（`-r` 保留数据、`-d` 允许降级）；
3. `adb backup -f wx.ab -noapk com.tencent.mm` 拉取私有数据；
4. `abe` 或 `adb backup` 解包得到 `databases/*.db`，再用本工具恢复。

**v2.1 已落成 `apk_downgrade.py`**：`check`/`version`/`backup`/`downgrade`/`extract`/`pull`/`workflow` 子命令，命令构造与 §4.A 步骤一一对应；`backup`+`downgrade`+`pull` 等任何有数据风险的操作都**强制 `--i-understand` 才执行**，否则拒绝（已在 `tests/run_all.py` 的 T10 用假 runner 验证命令构造与安全闸门）。`extract` 解 `.ab` 依赖 `abe.jar`+Java，缺失时只给指引不擅自跑。
> 坑（仍存）：Android 12+ 上降级可能被签名/版本策略拦，且降级有清数据风险——脚本强制“先备份再降级”。这是“免 root”的唯一现实路径，**命令层已全验证，真机实战成功率待真机实测**。

### B. 微信 EnMicroMsg.db 密钥（吸收 ForensicsTool，v2.1 加固）
- 旧版微信：`key = MD5(IMEI + UIN)` 的原始 16 字节摘要，SQLCipher 以 **legacy/raw** 模式工作（**AES-128-CBC**，16 字节 = AES-128；IV=页号，无 HMAC、无 KDF）。
- 本工具 `wechat_key.py` 直接生成候选（`md5(imei+uin)` / `md5(imei)` / `md5(uin)` / `md5(uin+imei)` 顺序交换）并**离线解密校验**。
- **v2.1 关键修正——消除“页大小误判”**：微信页号 IV 使第 1 块解密与页大小无关，所以旧版“按固定 4096 试”会解出 magic 假阳性但后续全乱。`verify` 改为：**先解密块 0 确认 magic 并读出明文头里的真实页大小，再据此全量解密**。同时仍对多个候选密钥穷举，并在备份解压后 `--scan-backup` best-effort 扫描可能残留的 32 位 hex key。
- 新版微信（7.x+）的“密钥轮换”本质是**密钥来源**变化（Android 10+ 限制 IMEI、key 存进设备绑定安全区），纯 IMEI+UIN 在无 root 下仍可能取不到——这是所有社区工具共同的硬上限，**完全突破需 root/Frida/Magisk**，超出本工具范围，已在 §5 明确标注，不夸大。

### C. SQLite 删除恢复引擎（吸收 FQLite / bring2lite）
两个关键修正（这两点正是“普通 DELETE 后查不到”的根因）：
1. **页 slack（未分配区）才是主战场**：普通 DELETE 后，被删 cell 的数据大多残留在“cell 指针数组末端 → cell 内容区起点”之间的 slack，而非 freelist。早期只扫 freelist 必然 0 命中。
2. **freeblock 头部会破坏记录头**：中部删除形成的 freeblock，其 4 字节头会覆盖 cell 前几个字节（含记录头），导致结构化解析失败——因此加了 **bring2lite 式文本片段雕刻兜底**：记录头坏了但文本字节还在，直接抓可打印 run。
3. **WAL / rollback journal 历史页**：提交前/回滚前的数据常在这些文件里，是 DELETE 之后更可靠的来源；本引擎解析 WAL 帧（magic 0x377f0682/83）和 journal 帧，对每帧裸页镜像跑删除恢复。
4. **schema 感知**：先读 `sqlite_master` 还原 表→rootpage→列名，恢复结果按列名结构化输出，并用“活记录签名”去重避免误报。
5. **深度雕刻（v2.1 新增，对齐 FQLite 纯 carving 深度）**：在 slack/freeblock 之外，对整个库字节以及每张 WAL/Journal 帧镜像做**全文字符串扫描**，捕获游离在结构化区域之外的残留——被复用但未完全覆盖的页、checkpoint 后残留、文件级未分配空间等。置信度低，单独以 `来源:carve` 标记并与结构化恢复区分呈现；并过滤“是某条活记录文本子串”的碎片以降低误报。`tests/run_all.py` 的 T9 通过在文件尾追加含秘密的脏数据验证了该路径（结构化恢复够不到、只有深度雕刻能命中）。

### D. iOS 备份恢复（吸收 ios-forensics-mcp 的“原生、自动”思路）
- 真实 iOS 备份文件名是 **SHA1 哈希（无扩展名）**，不能只按 `.db` 找——必须按 `SQLite format 3` 魔数扫描。命中后再跑删除恢复。
- 加密备份（含密钥包 `Manifest.plist`）暂不覆盖，仅处理未加密或已解包的库。

### E. 外部引擎（MVT / IPED 作参考，不重造）
MVT 是移动取证基线标杆、IPED 是工业级桌面 GUI。本工具不替代它们，只补上“删记录雕刻”这一它们不专攻的短板；需要完整取证流水线时，本工具输出可作为它们的上游输入。

---

## 5. 边界表（能 / 不能）

| 场景 | 能否恢复 | 说明 |
|---|---|---|
| SQLite 普通 DELETE（无 VACUUM） | ✅ | slack + freeblock 雕刻 |
| SQLite + WAL / journal 历史 | ✅ | 解析帧并恢复 |
| 已 VACUUM / 覆盖写入 | ❌ | 空间被复用，数据物理消失 |
| 微信旧版 EnMicroMsg.db | ✅ | IMEI+UIN 推导密钥 |
| 微信 7.x+（密钥轮换） | ❌ | 需 Frida/Magisk 取系统密钥 |
| iOS 未加密备份 | ✅ | 魔数扫描 + 恢复 |
| iOS 加密备份 | ❌ | 需密钥包，未覆盖 |
| Android 本地已导出目录 | ✅ | 扫描 databases/*.db |
| Android 真机无 root 拉取 | ⚠️ | 已自动化（apk_downgrade），安全闸门齐全，真机实战未跑 |

---

## 6. 实战流程建议

1. 拿到文件/目录 → 先跑 `recover_orchestrator.py`（自动路由）。
2. 微信库解不出 → `wechat_key.py --pull` 抓 IMEI/UIN，或手动提供，再 `--verify`。
3. 解密后仍有删记录 → 引擎自动顺带挖 slack/WAL。
4. Android 真机 → 用 `apk_downgrade.py workflow` 走降级备份流程（§4.A），导出目录后再喂本工具；任何有风险步骤都需自己补 `--i-understand`。
5. 跑 `tests/run_all.py` 做回归（标准 21 项全过 + T5/T8/T11 因缺 cryptography 标记 SKIP 不计入通过；`--full` 共 26 项全过，需先 `pip install cryptography`）。

---

## 7. 复盘日志

- **更名（v2.2 同版）**：原名 `data-recovery` 在 GitHub 上有 **1718** 个近名仓库（实测），辨识度为零。撞名实测后排除神话系（osiris 2616 / charon 1457 / revenant 736 更撞）与已被同类占用的词（`exhume` 被 forensicxlab 占、`resurgam` 被 duriantaco 占），选定 **Exhumer**（撞名 27，同名的 `axolotl-logic/Exhumer` 已废弃）。同步改动：技能目录名 `exhumer/`、`SKILL.md` frontmatter `name: exhumer`、README 标题与全篇、GitHub 仓库名与 git remote。GitHub 改名后旧链接 301 跳转；已被 fork 的会断。
- **v2.0 重建**：原 `.qclaw` 工程树在本环境丢失，按“取长补短”规格从零重建并补了端到端测试。
  - 关键修正：未分配区方向（之前把 slack 区间算反，导致普通 DELETE 0 命中）；freeblock 头破坏记录头的问题用文本片段雕刻兜底；SQLCipher 解密同时支持 hex 字符串与原始字节。
  - 验证：合成数据 12/12 通过（slack / WAL / 无 false-positive / freeblock / 微信 key 命中与拒识 / iOS 扩展名与魔数 / 编排器双分支 / 端到端加密库链路）。
- **v1.x**（早期）：仅 freelist + 整文件文本匹配，漏掉绝大多数普通 DELETE 残留——已被 v2 引擎取代。
- **v2.1 优化**：按用户要求补齐 v2.0 自评暴露的三个弱项/缺失。
  - C 引擎：新增**深度雕刻**（全文件 + WAL/Journal 帧镜像字符串扫描），对齐 FQLite 纯 carving 深度；碎片过滤“活记录子串”降误报。T9 验证（文件尾游离残留只有雕刻能命中）。
  - B 微信密钥：修掉 `subprocess` 缺失 import；候选扩到 4 种拼接；**`verify` 改为块 0 页大小自探测 + 多候选穷举**，消除 4096 假阳性（页号 IV 使块 0 与页大小无关）。新增 `--scan-backup` 扫残留 hex key。T11 验证（非默认页大小 1024 正确命中）。
  - A 免 root 降级：新脚本 `apk_downgrade.py`（check/version/backup/downgrade/extract/pull/workflow），**所有有风险操作强制 `--i-understand`**，解压依赖 abe.jar+Java 缺失时只指引。T10 验证命令构造与安全闸门。
  - Android 拉取：新 `android_triage.pull_device` 接通 `apk_downgrade` 备份路径 + `discover_packages` 关注包过滤，未确认拒绝。T12 验证。
  - 验证：标准 21/21 通过 + 3 项 SKIP（T5/T8/T11 需 cryptography，不计入通过/失败）；`--full` 26/26 通过。新增 T13 实测拦截 tar 路径穿越。
  - 诚实边界：微信密钥“来源轮换”在无 root 下仍受 IMEI+UIN 上限（完全突破需 root/Frida，超出范围）；免 root 降级/真机拉取命令层已验证但真机实战未跑；通用 SQLCipher(KDF/HMAC) 故意不实现，避免错误加密实现误导。
- **v2.2 审计驱动的 P0/P1 闭环**：独立审计（取证正确性 / 工程质量与安全 / 竞品）后，按用户要求修掉四类问题。
  - 安全（P0）：`apk_downgrade.extract_ab` 原 `tarfile.extractall` 未防路径穿越（CVE-2007-4559）。新增 `_safe_extract_tar`，逐个成员校验绝对路径 / `..` 段 / 落点越界，硬链接与符号链接目标一并校验，越界即整体拒绝。T13 新增真实拦截测试（构造含 `../escape.txt` 的恶意 tar，验证被拒且无越界落盘）。
  - 测试诚信（P0）：`tests/run_all.py` 原把“缺 cryptography 时 T5/T8/T11”用 `check(...,True)` 记通过，凑出“24/24 全过”假象。改为 `skip()` 明确标记 SKIP，不计入通过数也不算失败；汇总行如实显示“21/21 通过，3 跳过 / 26/26 通过”。
  - AES 标注（P1）：微信加密原错标 AES-256；MD5 摘要为 16 字节，实为 **AES-128**。已在 `wechat_key.py` 与 `sqlite_recover.py` 的注释/文档统一更正（cryptography 按密钥长度自动选 128/192/256，若日后拿到 32 字节密钥即 AES-256）。
  - 失败报成功（P1）：`apk_downgrade.pull_via_backup` 在 `extract_ab` 失败时仍返回目录路径，上层会误判“已拿到数据”。改为失败返回 `None`，`android_triage.pull_device` 不再打印假目录；T12 断言同步改为“确认后越过安全闸门且如实返回 None”。
  - 自评/对比表（诚实化）：自评从 4.7（注水分）下调到诚实的 4.2；对比表“压低对手分数”隐患已在 v2.2 修正为不刻意压低的诚实区间（FQLite 上调至 4.6、Avilla 4.4、IPED 4.2、ForensicsTool 4.0、bring2lite 3.4、Undark 3.2），并在表后加注说明利益冲突。“密码学仅自洽验证未对照真实微信”一项仍如实标注，不掩盖。
