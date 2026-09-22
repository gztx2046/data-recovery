#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recover_orchestrator.py  —  统一取证入口（本项目相对单功能 GUI 工具的差异化卖点）
===================================================================================
一个入口，按输入类型/设备自动路由：
  - 单个 SQLite 文件        → sqlite_recover.recover_file（删除/残留 + WAL/journal + 可选解密）
  - 目录（iOS 备份/Android 导出）→ ios_backup_recover / android_triage（递归扫描 + 逐个恢复）
  - 设备（--device/--pkg）   → best-effort adb（无 root 受限；见 SKILL.md 的 APK 降级免 root 法）

用法：
  python recover_orchestrator.py <文件或目录> [--minlen 4] [--maxout 200] \
        [--wal X] [--journal X] [--decrypt-key K] [--page-size N] [--json]
  python recover_orchestrator.py --device [--pkg com.tencent.mm]

输出：分来源汇总的被删/残留记录。--json 供上层/流水线消费。
"""
import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import sqlite_recover as R
import ios_backup_recover as I
import android_triage as A


def recover_single(db, minlen=4, maxout=200, wal=None, journal=None, decrypt_key=None,
                   page_size=None, as_json=False):
    return R.recover_file(db, minlen, maxout, wal, journal, decrypt_key, page_size, as_json)


def recover_directory(directory, minlen=4, maxout=200, as_json=False):
    return I.main_argv([directory, "--minlen", str(minlen), "--maxout", str(maxout)] +
                       (["--json"] if as_json else []))


def recover_device(pkg=None, as_json=False):
    if pkg:
        return A.main_argv(["--pkg", pkg])
    return A.main_argv([])


def main_argv(argv):
    p = argparse.ArgumentParser(description="统一取证恢复入口")
    p.add_argument("target", nargs="?", default=None, help="SQLite 文件或目录")
    p.add_argument("--device", action="store_true", help="走设备(adb)分支")
    p.add_argument("--pkg", default=None, help="指定 Android 包名")
    p.add_argument("--minlen", type=int, default=4)
    p.add_argument("--maxout", type=int, default=200)
    p.add_argument("--wal", default=None)
    p.add_argument("--journal", default=None)
    p.add_argument("--decrypt-key", default=None)
    p.add_argument("--page-size", type=int, default=None)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    if a.device or a.pkg:
        return recover_device(a.pkg, a.json)

    if not a.target:
        p.print_help()
        return

    if os.path.isfile(a.target):
        recover_single(a.target, a.minlen, a.maxout, a.wal, a.journal, a.decrypt_key,
                      a.page_size, a.json)
    elif os.path.isdir(a.target):
        recover_directory(a.target, a.minlen, a.maxout, a.json)
    else:
        print("ERROR: 路径不存在: %s" % a.target, file=sys.stderr)


if __name__ == "__main__":
    main_argv(sys.argv[1:])
