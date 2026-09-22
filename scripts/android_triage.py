#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
android_triage.py  —  Android 设备 / 已导出数据目录 的 SQLite 删除恢复
========================================================================
两条用法：
  1) 已通过 adb/root/备份 把某个 app 的 databases 目录导出到本地 → 直接扫描恢复；
  2) 接上设备，用 --pkg 触发 best-effort 的 adb 拉取（无 root 时受限于权限，
     自动走 apk_downgrade 的“备份+解压”免 root 路径；需 --i-understand 开启）。

注意：本脚本不做任何违法/越权操作；仅对已能读到的本地文件做恢复。
"""
import os
import sys
import argparse
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import sqlite_recover as R

# apk_downgrade 为可选依赖：存在则启用免 root 备份拉取
try:
    import apk_downgrade as AD
except Exception:
    AD = None

SQLITE_MAGIC = b"SQLite format 3\x00"

# 取证常关心的包名（用于 discover_packages 过滤）
INTEREST_PKGS = (
    "com.tencent.mm",            # 微信
    "com.tencent.mobileqq",      # QQ
    "com.tencent.wework",        # 企业微信
    "com.sina.weibo",            # 微博
    "com.alibaba.android.rimet", # 钉钉
)


def is_sqlite_file(path):
    try:
        with open(path, "rb") as f:
            return f.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def find_dbs(root):
    out = []
    if os.path.isfile(root):
        out.append(root)
        return out
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            low = fn.lower()
            if low.endswith((".db", ".sqlite", ".sqlitedb")):
                out.append(p)
            elif os.path.getsize(p) >= 16 and is_sqlite_file(p):
                out.append(p)
    return out


def recover_android(root, minlen=4, maxout=200):
    dbs = find_dbs(root)
    results = []
    for p in dbs:
        try:
            res = R.recover_file(p, minlen, maxout, as_json=True)
        except Exception as e:
            print("  [跳过] %s 异常: %s" % (p, e), file=sys.stderr)
            continue
        recs = (res.get("recovered") if res else None) or []
        if recs:
            results.append((p, recs))
    return dbs, results


def _real_runner(cmd, timeout=90):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.returncode, r.stdout, r.stderr)
    except Exception as e:
        return (-1, "", str(e))


def adb_check(adb_exe="adb", runner=_real_runner):
    rc, out, err = runner([adb_exe, "devices"])
    return out.strip() or err.strip() or ("adb 不可用: %s" % err)


def discover_packages(adb_exe="adb", runner=_real_runner):
    """列出设备上已安装、且属于取证关注列表的包名。"""
    rc, out, err = runner([adb_exe, "shell", "pm", "list", "packages"])
    if rc != 0:
        return []
    found = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        pkg = line.split(":", 1)[1].strip()
        if pkg in INTEREST_PKGS:
            found.append(pkg)
    return found


def pull_device(adb_exe, pkg, dest_dir, confirmed, abe_jar=None, runner=_real_runner):
    """从已连接设备拉取某 app 的数据库。优先走 apk_downgrade 的免 root 备份路径；
    若 apk_downgrade 不可用则给出指引。返回 (extracted_dir_or_None, info_text)。"""
    if AD is None:
        return None, ("apk_downgrade 模块缺失，无法自动拉取。请手动 `adb backup` + "
                      "Android Backup Extractor 解压后，把 databases 目录指向本地路径。")
    d, (rc, out, err) = AD.pull_via_backup(adb_exe, pkg, dest_dir, confirmed, abe_jar, None, runner)
    info = (out + "\n" + err).strip()
    return d, info


def main_argv(argv):
    p = argparse.ArgumentParser(description="Android SQLite 删除恢复")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--pkg", default=None, help="指定包名，best-effort adb 拉取")
    p.add_argument("--adb", default="adb")
    p.add_argument("--abe", default=None, help="abe.jar 路径（设备备份解压）")
    p.add_argument("--minlen", type=int, default=4)
    p.add_argument("--maxout", type=int, default=200)
    p.add_argument("--i-understand", action="store_true", help="开启有数据风险的设备操作")
    a = p.parse_args(argv)
    if a.root:
        dbs, results = recover_android(a.root, a.minlen, a.maxout)
        print("扫描到 SQLite 库: %d 个" % len(dbs))
        for p, recs in results:
            print("=" * 70)
            print("文件: %s （命中 %d 条）" % (p, len(recs)))
            for r in recs:
                cols = r.get("cols") or []
                for i, v in enumerate(r["values"]):
                    label = cols[i] if i < len(cols) else ("col%d" % i)
                    print("  %-20s : %s" % (label, v if not isinstance(v, (bytes, bytearray)) else "<BLOB>"))
        return
    print(">>> adb 设备列表：")
    print(adb_check(a.adb))
    pkgs = discover_packages(a.adb)
    if pkgs:
        print(">>> 关注列表内已安装: %s" % ", ".join(pkgs))
    if a.pkg:
        print(">>> 对 %s 拉取（%s）：" % (a.pkg, "已确认" if a.i_understand else "未确认→将被安全闸门拒绝"))
        d, info = pull_device(a.adb, a.pkg, "work", a.i_understand, a.abe)
        print(info)
        if d:
            print(">>> 解压目录: %s —— 再跑 `python android_triage.py %s` 做本地恢复" % (d, d))


if __name__ == "__main__":
    main_argv(sys.argv[1:])
