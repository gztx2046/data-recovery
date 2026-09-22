#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat_key.py  —  微信 EnMicroMsg.db SQLCipher 密钥推导 / 多配置离线校验
=====================================================================
吸收 ForensicsTool 的思路：密钥不是密码，而是设备相关派生值。

【微信 EnMicroMsg.db 的实际密码学】
  微信（WCDB/SQLCipher 分支）使用“legacy/raw”模式：
    key = MD5(IMEI + UIN) 的原始 16 字节摘要，直接作为 AES-128 密钥（16 字节 = AES-128）；
    AES-128-CBC，IV = 页号(4B 大端) + 0*12，无 HMAC、无 KDF。
    （cryptography 的 AES 按密钥长度自动选 128/192/256；若日后拿到 32 字节密钥即为 AES-256。）
  这是绝大多数仍可被取证的微信版本的真相，本脚本的主路径即此。

【关于“7.x+ 密钥轮换”的诚实说明】
  微信 7.x 之后并未改密码学算法，真正的瓶颈是“密钥来源”：
    - Android 10+ 限制了 IMEI 读取，微信在新设备上可能不再以 IMEI 派生；
    - 新微信把 db key 存进设备绑定的安全区，纯 IMEI+UIN 取不到。
  因此本脚本在“无 root/备份”前提下，能做的加固是：
    1) 把候选派生做全（IMEI+UIN / IMEI / UIN / 顺序交换）；
    2) 对多个页大小(512~65536)逐一尝试，避免非默认页大小漏解；
    3) 备份提取后 best-effort 扫描可能残留的 32 位 hex key（见 --scan-backup）。
  真正的“完全突破”需要 root / Frida / Magisk 模块读取设备绑定 key —— 超出本脚本范围，
  已在 SKILL.md §5 边界明确标注，不夸大。

【为什么不做通用 SQLCipher 的 PBKDF2 passphrase 路径】
  通用 SQLCipher（带 KDF/HMAC）与微信的 legacy 模式在“第 1 页是否保留明文 salt、
  magic 偏移、IV 派生”上完全不同；微信是 raw 密钥、整页按页号 IV 加密。强行套 KDF
  路径极易写出“看起来能跑但解不对”的错误实现，反而误导取证，故本脚本只覆盖
  微信真实使用的 legacy 模式，并做页大小穷举。

用法：
  python wechat_key.py --imei <IMEI> --uin <UIN> [--verify <EnMicroMsg.db>]
  python wechat_key.py --imei <IMEI> --uin <UIN> --export-env
  python wechat_key.py --pull                 # best-effort adb 抓 IMEI/UIN
  python wechat_key.py --scan-backup <解压后的备份根目录>   # 扫描可能残留的 hex key
"""
import sys
import os
import re
import struct
import hashlib
import argparse
import subprocess

DEFAULT_IMEI = "1234567890ABCDEF"
MAGIC = b"SQLite format 3\x00"
VALID_PAGE_SIZES = (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)


def candidates(imei, uin):
    """返回 [(label, key_bytes), ...]。key_bytes 为可直接喂 legacy SQLCipher 的 16 字节密钥。"""
    imei = imei or DEFAULT_IMEI
    uin = "" if uin is None else str(uin)
    pairs = [
        ("md5(imei+uin)", (imei + uin).encode("utf-8", "ignore")),
        ("md5(imei)", imei.encode("utf-8", "ignore")),
        ("md5(uin)", uin.encode("utf-8", "ignore")),
        # 顺序交换：个别机型/版本的拼接顺序不同
        ("md5(uin+imei)", (uin + imei).encode("utf-8", "ignore")),
    ]
    out = []
    for label, data in pairs:
        if not data:
            continue
        out.append((label, hashlib.md5(data).digest()))  # 16 字节原始摘要
    return out


# ---------------------------------------------------------------------------
# 解密原语（legacy = 微信/WCDB 使用的页号 IV、无 HMAC、整页加密）
# ---------------------------------------------------------------------------

def _aes_cbc_decrypt(page, key, iv):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
    except Exception:
        return None
    try:
        d = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).decryptor()
        return d.update(page) + d.finalize()
    except Exception:
        return None


def decrypt_sqlcipher(db_bytes, key_hex, page_size):
    """解密 legacy SQLCipher 单页流。key_hex 可为 16 进制字符串或原始字节密钥。
    返回解密后的完整数据库字节（用于后续恢复）。需要 cryptography 库。"""
    if isinstance(key_hex, (bytes, bytearray)):
        key = bytes(key_hex)
    else:
        key = bytes.fromhex(key_hex)
    out = bytearray()
    n = len(db_bytes) // page_size
    for i in range(n):
        page = db_bytes[i * page_size:(i + 1) * page_size]
        iv = struct.pack(">II", i + 1, 0) + b"\x00" * 8
        pt = _aes_cbc_decrypt(page, key, iv)
        if pt is None:
            return None
        out += pt
    return bytes(out)


def _decrypt_block0(db_bytes, key):
    """解密第 1 块（前 1024 字节）。微信/SQLCipher 的页号 IV 使得“第 1 块”的 IV 恒为
    页号 1，与真实页大小无关——因此块 0 总能正确解出，可用于校验 magic 并读出页大小。"""
    if len(db_bytes) < 1024:
        return None
    iv = struct.pack(">II", 1, 0) + b"\x00" * 8
    return _aes_cbc_decrypt(db_bytes[0:1024], key, iv)


def verify(db_path, imei, uin, page_sizes=(4096, 1024, 2048, 8192, 16384, 512)):
    """离线校验密钥。返回 (label, key, page_size) 或 None。

    做法（避免页大小误判）：先对每块候选密钥解密“块 0”——由于页号 IV，块 0 与页大小
    无关，必能解出明文首页；据此确认 magic 并读取明文头里的真实页大小，再用该页大小做全量
    解密。这样即使库用了非默认页大小也不会被 4096 的“块 0 假阳性”带偏。
    """
    if not os.path.exists(db_path):
        print("ERROR: 数据库文件不存在: %s" % db_path, file=sys.stderr)
        return None
    with open(db_path, "rb") as f:
        db = f.read()
    hit = None
    for label, key in candidates(imei, uin):
        pt0 = _decrypt_block0(db, key)
        if pt0 is not None and pt0[:16] == MAGIC:
            ps = struct.unpack(">H", pt0[16:18])[0]
            if ps not in VALID_PAGE_SIZES:
                ps = 4096
            full = decrypt_sqlcipher(db, key, ps)
            if full is not None and full[:16] == MAGIC:
                hit = (label, key, ps)
                print("[命中] 算法 %s | 页大小 %d | 解密得到合法 SQLite 头，密钥正确。" % (label, ps))
                break
        if hit:
            break
        # 兜底：直接按候选页大小试（仅用于块 0 路径未能覆盖的极端情形）
        if hit is None:
            for ps in page_sizes:
                if len(db) < ps:
                    continue
                full = decrypt_sqlcipher(db, key, ps)
                if full is not None and full[:16] == MAGIC:
                    hit = (label, key, ps)
                    print("[命中] 算法 %s | 页大小 %d（兜底）| 密钥正确。" % (label, ps))
                    break
        if hit:
            break
    if not hit:
        print("[未命中] 给定 IMEI/UIN 未能解出。可能：①新版微信轮换密钥（无 root 难突破）；"
              "②IMEI/UIN 错误；③该库用了非默认页大小以外的加密方式。")
    return hit


# ---------------------------------------------------------------------------
# 备份提取后 best-effort 扫描可能残留的 hex key
# ---------------------------------------------------------------------------

def find_hex_keys_in_backup(backup_root, maxfind=20):
    """在已解压的 adb backup 目录里扫描 32 位 hex 字符串（SQLCipher passphrase 候选）。
    best-effort：微信会把真实 key 加密存放，未必能直接拿到；此处尽量捞回明文残留。"""
    found = []
    if not os.path.isdir(backup_root):
        return found
    hexre = re.compile(r"\b([0-9a-fA-F]{32})\b")
    for dirpath, _d, files in os.walk(backup_root):
        for fn in files:
            if len(found) >= maxfind:
                return found
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > 2_000_000:
                    continue
                with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read()
            except OSError:
                continue
            for m in hexre.finditer(txt):
                h = m.group(1).lower()
                if h not in found:
                    found.append(h)
        if len(found) >= maxfind:
            break
    return found


# ---------------------------------------------------------------------------
# adb 辅助
# ---------------------------------------------------------------------------

def adb(args):
    try:
        return subprocess.run(["adb"] + args, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:
        print("adb 调用失败: %s" % e, file=sys.stderr)
        return ""


def pull():
    """best-effort 从已连接设备抓取 IMEI 与 UIN。需要设备授权/权限。"""
    print(">>> 尝试 adb 抓取（需要设备已连接、USB 调试开启；UIN 读取常需 root）")
    imei = (adb(["shell", "getprop", "persist.radio.imei"]) or
            adb(["shell", "getprop", "gsm.serial"]) or
            adb(["shell", "service", "call", "iphonesubinfo", "1"]))
    uin = ""
    pref = adb(["shell", "cat", "/data/data/com.tencent.mm/shared_prefs/com.tencent.mm_preferences.xml"])
    m = re.search(r'name="_uin"[^>]*value="(\d+)"', pref)
    if m:
        uin = m.group(1)
    print("IMEI: %s" % imei)
    print("UIN : %s" % uin)
    if imei or uin:
        print("可继续执行：python wechat_key.py --imei %s --uin %s [--verify EnMicroMsg.db]" % (imei, uin))
    else:
        print("未能抓取。请确认设备连接与权限；或手动提供 --imei/--uin。")
    return imei, uin


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main_argv(argv):
    p = argparse.ArgumentParser(description="微信 EnMicroMsg.db 密钥推导")
    p.add_argument("--imei", default=DEFAULT_IMEI)
    p.add_argument("--uin", default=None)
    p.add_argument("--verify", default=None, help="用候选密钥离线解密该 db 校验")
    p.add_argument("--pull", action="store_true", help="从已连接设备 adb 抓取 IMEI/UIN")
    p.add_argument("--export-env", action="store_true", help="仅打印候选 hex 密钥")
    p.add_argument("--scan-backup", default=None, help="扫描已解压备份目录中的 hex key 候选")
    a = p.parse_args(argv)
    if a.pull:
        pull()
        return
    if a.scan_backup:
        keys = find_hex_keys_in_backup(a.scan_backup)
        print(">>> 在 %s 中发现 %d 个 32 位 hex 候选：" % (a.scan_backup, len(keys)))
        for k in keys:
            print("  %s" % k)
        if not keys:
            print("  （未发现明文 hex key；微信通常加密存放，需 root/备份级提取。）")
        return
    cands = candidates(a.imei, a.uin)
    if a.export_env:
        for label, key in cands:
            print("%-18s %s" % (label, key.hex()))
        return
    print("IMEI=%s  UIN=%s" % (a.imei, a.uin))
    for label, key in cands:
        print("  候选 %-18s -> %s" % (label, key.hex()))
    if a.verify:
        verify(a.verify, a.imei, a.uin)


if __name__ == "__main__":
    main_argv(sys.argv[1:])
