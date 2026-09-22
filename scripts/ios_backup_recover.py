#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ios_backup_recover.py  —  iOS 备份 / 已解包目录 的 SQLite 删除恢复
================================================================
吸收 ios-forensics-mcp 的思路：iOS 备份里大量 app 数据就是 SQLite。
关键是：真实备份文件名是 SHA1 哈希（无扩展名），不能只靠扩展名找，
必须按“SQLite format 3”魔数扫描；命中后再跑删除恢复。

用法：
  python ios_backup_recover.py <备份目录或单db> [--minlen 4] [--maxout 200] [--json]

流程：
  1) 递归扫描目录，凡文件头为 "SQLite format 3\\0" 或扩展名 .db/.sqlite/.sqlitedb 者纳入；
  2) 逐个调用 sqlite_recover.recover_file 跑删除/残留恢复；
  3) 对 SQLCipher 加密（无魔数）的库给出提示（需密钥，超出本脚本范围）。
"""
import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import sqlite_recover as R

SQLITE_MAGIC = b"SQLite format 3\x00"


def is_sqlite_file(path):
    try:
        with open(path, "rb") as f:
            return f.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def find_dbs(root):
    """返回 [db_path, ...]。扩展名命中 + 魔数命中（兼容真实 hash 命名备份）。"""
    out = []
    if os.path.isfile(root):
        out.append(root)
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            low = fn.lower()
            if low.endswith((".db", ".sqlite", ".sqlitedb", ".db-wal", ".db-journal")):
                if low.endswith((".db-wal", ".db-journal")):
                    continue  # 这些由主库自动关联，不单列
                out.append(p)
            else:
                try:
                    if os.path.getsize(p) >= 16 and is_sqlite_file(p):
                        out.append(p)
                except OSError:
                    pass
    return out


def recover_backup(root, minlen=4, maxout=200):
    dbs = find_dbs(root)
    results = []
    skipped_enc = 0
    for p in dbs:
        # 跳过明显加密（无魔数且非扩展名命中）的文件，避免误当明文解析
        if not (p.lower().endswith((".db", ".sqlite", ".sqlitedb"))) and not is_sqlite_file(p):
            # 扩展名命中但无魔数 → 可能是 SQLCipher 加密
            if p.lower().endswith((".db", ".sqlite", ".sqlitedb")):
                skipped_enc += 1
            continue
        try:
            res = R.recover_file(p, minlen, maxout, as_json=True)
        except Exception as e:
            print("  [跳过] %s 解析异常: %s" % (p, e), file=sys.stderr)
            continue
        recs = (res.get("recovered") if res else None) or []
        if recs:
            results.append((p, recs))
    return dbs, results, skipped_enc


def main_argv(argv):
    p = argparse.ArgumentParser(description="iOS 备份 SQLite 删除恢复")
    p.add_argument("root")
    p.add_argument("--minlen", type=int, default=4)
    p.add_argument("--maxout", type=int, default=200)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    dbs, results, skipped_enc = recover_backup(a.root, a.minlen, a.maxout)
    if a.json:
        import json
        print(json.dumps({"scanned": len(dbs), "skipped_encrypted": skipped_enc,
                           "files_with_recovery": [
                               {"db": x[0], "recovered": x[1]} for x in results]},
                          ensure_ascii=False))
        return
    print("扫描到 SQLite 库: %d 个（跳过疑似加密: %d 个）" % (len(dbs), skipped_enc))
    if not results:
        print("未在任何库中恢复出被删/残留记录。")
        return
    for p, recs in results:
        print("=" * 70)
        print("文件: %s  （命中 %d 条）" % (p, len(recs)))
        for r in recs:
            cols = r.get("cols") or []
            print("  [来源:%s]" % r["source"])
            for i, v in enumerate(r["values"]):
                label = cols[i] if i < len(cols) else ("col%d" % i)
                if isinstance(v, (bytes, bytearray)):
                    v = "<BLOB %d字节>" % len(v)
                print("    %-20s : %s" % (label, v))


if __name__ == "__main__":
    main_argv(sys.argv[1:])
