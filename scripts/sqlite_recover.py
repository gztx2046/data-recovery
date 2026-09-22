#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sqlite_recover.py  v2.1
=======================
SQLite 3 删除记录取证恢复引擎（纯标准库，无第三方依赖）。

吸收的社区强技术（见 SKILL.md 复盘）：
  - FQLite / bring2lite：叶页 freeblock 链 + 页 slack(未分配区) 雕刻，
    而非只扫 freelist 页；schema 感知（读 sqlite_master 还原表→列名）。
  - 深度雕刻（v2.1 新增）：对整个库字节及每张 WAL/Journal 帧镜像做全文字符串
    扫描，捕获游离在 slack/freeblock 之外的残留（被复用未覆盖的页、文件级未分配
    空间等）。置信度低，单独以 source='carve' 标记，与结构化恢复区分。
  - WAL（-wal）与 rollback journal（-journal）历史页恢复：提交前/回滚前
    的数据常残留在这些文件里，是普通 DELETE 之后更可靠的来源。
  - 可选 SQLCipher 解密（微信 EnMicroMsg.db 等），用 --decrypt-key 喂密钥。

用法：
  python sqlite_recover.py <db> [minlen] [maxout] \
        [--wal X] [--journal X] [--decrypt-key K] [--page-size N] [--json]

输出：被删/残留记录（按表分组），默认表格；--json 给编排器消费。
"""
import sys
import os
import struct
import hashlib
import argparse
import json

# ----------------------------------------------------------------------------
# 基础解析：varint / serial type / record
# ----------------------------------------------------------------------------

def read_varint(data, off):
    """读 SQLite 可变长整数（1-9 字节）。返回 (value, new_off)；越界返回 (None, off)。"""
    if off < 0 or off >= len(data):
        return (None, off)
    result = 0
    for i in range(9):
        if off >= len(data):
            return (None, off)
        b = data[off]
        off += 1
        if i == 8:
            result = (result << 8) | b
            return (result, off)
        result = (result << 7) | (b & 0x7F)
        if not (b & 0x80):
            return (result, off)
    return (result, off)


def decode_serial(stype, data, off):
    """按 serial type 解码一个值。返回 (value, consumed_bytes)；无法解码返回 (None, 0)。"""
    if stype == 0:
        return (None, 0)
    if stype == 1:
        if off + 1 > len(data): return (None, 0)
        return (int.from_bytes(data[off:off+1], 'big', signed=True), 1)
    if stype == 2:
        if off + 2 > len(data): return (None, 0)
        return (int.from_bytes(data[off:off+2], 'big', signed=True), 2)
    if stype == 3:
        if off + 3 > len(data): return (None, 0)
        return (int.from_bytes(data[off:off+3], 'big', signed=True), 3)
    if stype == 4:
        if off + 4 > len(data): return (None, 0)
        return (int.from_bytes(data[off:off+4], 'big', signed=True), 4)
    if stype == 5:
        if off + 6 > len(data): return (None, 0)
        return (int.from_bytes(data[off:off+6], 'big', signed=True), 6)
    if stype == 6:
        if off + 8 > len(data): return (None, 0)
        return (int.from_bytes(data[off:off+8], 'big', signed=True), 8)
    if stype == 7:
        if off + 8 > len(data): return (None, 0)
        return (struct.unpack('>d', data[off:off+8])[0], 8)
    if stype == 8:
        return (0, 0)
    if stype == 9:
        return (1, 0)
    if stype >= 12:
        if stype % 2 == 0:
            n = (stype - 12) // 2
            if off + n > len(data): return (None, 0)
            return (data[off:off+n], n)          # BLOB → bytes
        else:
            n = (stype - 13) // 2
            if off + n > len(data): return (None, 0)
            raw = data[off:off+n]
            # 文本：优先 utf-8，失败回退 utf-16le（iOS/微信常见）
            try:
                return (raw.decode('utf-8'), n)
            except UnicodeDecodeError:
                return (raw.decode('utf-16-le', errors='replace'), n)
    # 10/11 保留类型，视为无效
    return (None, 0)


def parse_record(payload):
    """解析一条 record（cell 的 payload）。返回 values 列表；失败返回 None。"""
    if not payload:
        return None
    hdr_len, p = read_varint(payload, 0)
    if hdr_len is None or hdr_len < 1 or p > hdr_len:
        return None
    end = hdr_len
    stypes = []
    while p < end and p < len(payload):
        st, p = read_varint(payload, p)
        if st is None:
            return None
        stypes.append(st)
    # 校验每个值的字节长度可满足
    q = end
    for st in stypes:
        _, c = decode_serial(st, payload, q)
        if c == 0 and st not in (0, 8, 9):
            return None
        q += c
    if q > len(payload):
        return None
    if not stypes:
        return None
    values = []
    pos = end
    for st in stypes:
        v, c = decode_serial(st, payload, pos)
        values.append(v)
        pos += c
    return values


def columns_from_create(sql):
    """从 CREATE TABLE 语句中解析列名（schema 感知）。"""
    if not sql:
        return []
    # 找第一个 '(' 与匹配的 ')'
    i = sql.find('(')
    if i < 0:
        return []
    depth = 0
    j = i
    while j < len(sql):
        if sql[j] == '(':
            depth += 1
        elif sql[j] == ')':
            depth -= 1
            if depth == 0:
                break
        j += 1
    body = sql[i+1:j]
    cols = []
    buf = ''
    d = 0
    for ch in body:
        if ch == '(':
            d += 1; buf += ch
        elif ch == ')':
            d -= 1; buf += ch
        elif ch == ',' and d == 0:
            name = _col_name(buf)
            if name:
                cols.append(name)
            buf = ''
        else:
            buf += ch
    name = _col_name(buf)
    if name:
        cols.append(name)
    return cols


def _col_name(seg):
    seg = seg.strip()
    if not seg:
        return None
    up = seg.upper()
    # 跳过表级约束
    for kw in ('PRIMARY KEY', 'UNIQUE', 'CHECK', 'FOREIGN KEY', 'CONSTRAINT', 'KEY'):
        if up.startswith(kw):
            return None
    # 列名可能是 "name TYPE" 或带引号 "name" TYPE
    if seg.startswith('"') or seg.startswith('`') or seg.startswith("'"):
        q = seg[0]
        k = seg.find(q, 1)
        if k > 0:
            return seg[1:k]
    # 取第一个空白/括号前的 token
    for idx, ch in enumerate(seg):
        if ch in (' ', '\t', '\n', '('):
            return seg[:idx].strip('"`\'')
    return seg.strip('"`\'')


# ----------------------------------------------------------------------------
# 页 / b-tree 解析
# ----------------------------------------------------------------------------

def get_page_size(db):
    if len(db) < 100:
        return None
    ps = struct.unpack('>I', db[16:20])[0]
    if ps == 1:
        return 65536
    if ps in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
        return ps
    # 常见默认
    return 4096


def page_base(page_num, page_size):
    """页在文件中的起始偏移。页号从 1 开始。"""
    return (page_num - 1) * page_size


def btree_header_offset(page_num, source):
    """b-tree 头偏移：主库页 1 前面有 100 字节 DB 头；WAL/Journal 页镜像是裸页（无 DB 头）。"""
    if source == 'main' and page_num == 1:
        return 100
    return 0


def read_cell(page_bytes, cell_off, page_start, page_size):
    """读一个叶表 cell：返回 (rowid, payload_bytes)；失败返回 (None, None)。"""
    P, p = read_varint(page_bytes, cell_off)
    if P is None:
        return (None, None)
    R, p = read_varint(page_bytes, p)
    if R is None:
        return (None, None)
    payload = page_bytes[p:p + P]
    return (R, payload)


def walk_leaf_cells(page_bytes, header_off, page_size, cb):
    """遍历一个叶表页（0x0d）的所有 cell，调用 cb(rowid, payload, cell_off, cell_end)。"""
    ptype = page_bytes[header_off]
    if ptype != 0x0D:
        return
    ncells = struct.unpack('>H', page_bytes[header_off+3:header_off+5])[0]
    # cell 指针数组紧跟在页头之后
    ptr_start = header_off + 8
    max_end = 0
    for i in range(ncells):
        cp = struct.unpack('>H', page_bytes[ptr_start + i*2: ptr_start + i*2 + 2])[0]
        abs_off = cp  # cell 指针是“页内偏移”，绝对 = page_start + cp（调用方已处理）
        R, payload = read_cell(page_bytes, abs_off, 0, page_size)
        if payload is None:
            continue
        cell_end = abs_off + len(payload) + 0  # 近似（忽略溢出链）
        if cell_end > max_end:
            max_end = cell_end
        cb(R, payload, abs_off, cell_end)
    return max_end


def recover_leaf_deleted(page_bytes, header_off, cols, source, live_sigs, minlen, maxout, out, live_text=None):
    """在叶页的 freeblock 链 + 未分配区 雕刻被删/残留记录。"""
    if live_text is None:
        live_text = set()
    ptype = page_bytes[header_off]
    if ptype not in (0x0D, 0x05):
        return
    ncells = struct.unpack('>H', page_bytes[header_off+3:header_off+5])[0]
    ptr_start = header_off + 8
    first_fb = struct.unpack('>H', page_bytes[header_off+1:header_off+3])[0]
    ptr_array_end = ptr_start + ncells * 2
    # cell 内容区起点（页头字节 5-6；0 表示页尾 65536）
    ccs = struct.unpack('>H', page_bytes[header_off+5:header_off+7])[0]
    if ccs == 0:
        ccs = len(page_bytes)

    # 1) freeblock 链（删除发生在 cell 内容区中部时形成）
    fb = first_fb
    while fb != 0:
        if fb + 4 > len(page_bytes):
            break
        nxt = struct.unpack('>H', page_bytes[fb:fb+2])[0]
        size = struct.unpack('>H', page_bytes[fb+2:fb+4])[0]
        if size < 4:
            break
        region = page_bytes[fb+4: fb+size]
        _try_carve(region, cols, source, live_sigs, minlen, maxout, out, slide=True)
        # freeblock 头会覆盖 cell 前 4 字节（含记录头），结构化解析可能失败，
        # 但文本字节大多仍在 → 抓可打印片段兜底
        for frag in _extract_fragments(region, minlen):
            _emit_fragment(frag, 'freeblock-text', live_text, maxout, out)
        fb = nxt

    # 2) 未分配区（cell 指针数组末端 → cell 内容区起点）。
    #    叶页：指针数组在页头之后向上生长，cell 从页尾向下生长，
    #    两者之间是真正的 slack —— 删除“内容区起点处”的 cell 后数据就残在这里。
    unalloc_region = page_bytes[ptr_array_end:ccs]
    _try_carve(unalloc_region, cols, source, live_sigs, minlen, maxout, out, slide=True)
    for frag in _extract_fragments(unalloc_region, minlen):
        _emit_fragment(frag, 'slack-text', live_text, maxout, out)


def _text_ok(v, minlen):
    if not isinstance(v, str):
        return False
    if len(v) < minlen:
        return False
    # 至少含一个可打印字符（中英文/数字/常见标点）
    printable = sum(1 for c in v if c.isprintable() and not c.isspace())
    return printable >= minlen


def _try_carve(region, cols, source, live_sigs, minlen, maxout, out, slide=False):
    if not region or len(region) < 4:
        return
    offsets = range(0, len(region)) if slide else (0,)
    for off in offsets:
        sub = region[off:]
        if len(sub) < 4:
            continue
        # 尝试 1：直接当 record 解析
        vals = parse_record(sub)
        if vals and _accept(vals, cols, source, live_sigs, minlen):
            _emit(vals, cols, source, live_sigs, maxout, out)
        # 尝试 2：当 cell（payload_len, rowid, payload）
        P, p = read_varint(sub, 0)
        if P is not None and P > 0 and P <= len(sub) - p:
            payload = sub[p:p+P]
            vals2 = parse_record(payload)
            if vals2 and _accept(vals2, cols, source, live_sigs, minlen):
                _emit(vals2, cols, source, live_sigs, maxout, out)


def _accept(vals, cols, source, live_sigs, minlen):
    # 必须至少含一个像样的文本列
    has_text = any(_text_ok(v, minlen) for v in vals)
    if not has_text:
        return False
    # 若有 schema 列数，要求列数匹配（容差 ±0，避免错配）
    if cols:
        if len(vals) != len(cols):
            return False
    else:
        if not (1 <= len(vals) <= 64):
            return False
    sig = (len(vals), tuple(_norm(v) for v in vals))
    if sig in live_sigs:
        return False
    return True


def _norm(v):
    if isinstance(v, (bytes, bytearray)):
        return ('B', hashlib.md5(v).hexdigest())
    return v


def _emit(vals, cols, source, live_sigs, maxout, out):
    sig = (len(vals), tuple(_norm(v) for v in vals))
    if sig in live_sigs:
        return
    if len(out) >= maxout:
        return
    out.append({'cols': cols, 'values': vals, 'source': source})


def _extract_fragments(data, minlen):
    """从字节区提取连续可打印片段（bring2lite 式雕刻兜底）。
    当记录头被 freeblock 头破坏时，结构化解析失败，但文本字节仍在，
    直接抓可打印 run 即可拿到被删内容。"""
    frags = []
    buf = bytearray()
    def flush():
        if len(buf) >= minlen:
            s = bytes(buf).decode('utf-8', errors='replace')
            # 去掉首尾 ASCII 标点/符号（被 freeblock/脏字节带进来的残留），
            # 保留 CJK 与字母数字，避免 '=文本' 这类噪声碎片
            s = s.strip('=+-*/\\|<>{}[]().,;:!?@#$%^&~`"\' \t\n\r')
            if s and sum(1 for c in s if c.isprintable()) >= len(s) * 0.8:
                frags.append(s)
        buf.clear()
    for b in data:
        if (32 <= b <= 126) or b in (9, 10) or (0x80 <= b <= 0xBF) or (0xC2 <= b <= 0xF4):
            buf.append(b)
        else:
            flush()
    flush()
    return frags


def _emit_fragment(text, source, live_text, maxout, out):
    if not text or text in live_text:
        return
    # 若该片段是某个“活记录”文本的子串，多半只是活数据的碎片，跳过以降低误报
    if live_text and any(text in lv for lv in live_text):
        return
    for r in out:
        # 若已是某条已恢复记录（结构化或片段）的子串，视为重复，跳过
        if text in ''.join(str(x) for x in r['values']):
            return
    if len(out) >= maxout:
        return
    out.append({'cols': None, 'values': [text], 'source': source, '_frag': True})


# ----------------------------------------------------------------------------
# schema / b-tree 遍历（恢复“活”记录签名，并定位表叶页）
# ----------------------------------------------------------------------------

def collect_live_and_leaves(db, page_size, live_sigs, leaf_pages, live_text=None):
    """读 sqlite_master，收集每张表的列名→rootpage，并把所有叶页号记入 leaf_pages。"""
    if live_text is None:
        live_text = set()
    tables = {}  # name -> (rootpage, cols)
    # sqlite_master 自身在主库页 1（rootpage=1），先解析页 1 拿到 schema 记录
    page1 = db[0:page_size]
    records = []
    def cb(rowid, payload, off, end):
        v = parse_record(payload)
        if v:
            records.append(v)
    walk_leaf_cells(page1, btree_header_offset(1, 'main'), page_size, cb)
    for rec in records:
        # sqlite_master 列：type,name,tbl_name,rootpage,sql
        if len(rec) < 5:
            continue
        typ, name, tbl_name, rootpage, sql = rec[0], rec[1], rec[2], rec[3], rec[4]
        if typ == 'table' and isinstance(name, str):
            cols = columns_from_create(sql) if isinstance(sql, str) else []
            try:
                rootpage = int(rootpage)
            except Exception:
                rootpage = 0
            tables[name] = (rootpage, cols)
    # 遍历每张表的 b-tree，收集叶页号 + 活记录签名
    visited = set()
    for name, (root, cols) in tables.items():
        if not root:
            continue
        _walk(db, root, page_size, visited, leaf_pages, live_sigs, cols, live_text)
    return tables


def _walk(db, page_num, page_size, visited, leaf_pages, live_sigs, cols, live_text):
    if page_num in visited or page_num < 1:
        return
    visited.add(page_num)
    base = page_base(page_num, page_size)
    if base + page_size > len(db):
        return
    page = db[base:base + page_size]
    hoff = btree_header_offset(page_num, 'main')
    ptype = page[hoff]
    if ptype == 0x0D:  # 叶表
        leaf_pages.add(page_num)
        def cb(rowid, payload, off, end):
            v = parse_record(payload)
            if v:
                sig = (len(v), tuple(_norm(x) for x in v))
                live_sigs.add(sig)
                for x in v:
                    if isinstance(x, str):
                        live_text.add(x)
        walk_leaf_cells(page, hoff, page_size, cb)
    elif ptype == 0x05:  # 内部表
        ncells = struct.unpack('>H', page[hoff+3:hoff+5])[0]
        ptr_start = hoff + 12  # 内部页头 12 字节
        right = struct.unpack('>I', page[hoff+8:hoff+12])[0]
        for i in range(ncells):
            cp = struct.unpack('>H', page[ptr_start + i*2: ptr_start + i*2 + 2])[0]
            # 内部 cell：[4 字节左子页][varint key]
            child = struct.unpack('>I', page[cp:cp+4])[0]
            _walk(db, child, page_size, visited, leaf_pages, live_sigs, cols)
        _walk(db, right, page_size, visited, leaf_pages, live_sigs, cols)


# ----------------------------------------------------------------------------
# WAL / Journal 解析（历史页恢复）
# ----------------------------------------------------------------------------

def parse_wal(path, page_size):
    """解析 WAL 文件，返回 [(page_num, page_image_bytes), ...]。"""
    if not os.path.exists(path):
        return []
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) < 32:
        return []
    magic = struct.unpack('>I', data[0:4])[0]
    if magic == 0x377F0682:
        endian = '>'
    elif magic == 0x377F0683:
        endian = '<'
    else:
        return []
    ps = struct.unpack(endian + 'I', data[4:8])[0]
    if ps not in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
        ps = page_size
    frames = []
    off = 32
    n = 24 + ps
    while off + n <= len(data):
        page_num = struct.unpack(endian + 'I', data[off:off+4])[0]
        img = data[off+24: off+24+ps]
        frames.append((page_num, img))
        off += n
    return frames


def parse_journal(path, page_size):
    """解析 rollback journal（-journal），返回 [(page_num, page_image_bytes), ...]。
    注意：journal 页镜像也是裸页（页 1 无 100 字节 DB 头）。best-effort。"""
    if not os.path.exists(path):
        return []
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) < 28:
        return []
    magic = struct.unpack('>Q', data[0:8])[0]
    if magic not in (0xD11D2003, 0xD11D2002):
        return []
    endian = '>' if magic == 0xD11D2003 else '<'
    ps = struct.unpack(endian + 'I', data[8:12])[0]
    if ps not in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
        ps = page_size
    frames = []
    off = 28  # journal 头 28 字节
    rec = 4 + ps + 4  # page_num + image + checksum
    while off + rec <= len(data):
        page_num = struct.unpack(endian + 'I', data[off:off+4])[0]
        img = data[off+4: off+4+ps]
        frames.append((page_num, img))
        off += rec
    return frames


def recover_frames(frames, page_size, tables, live_sigs, minlen, maxout, out, live_text=None):
    """对 WAL/Journal 的每帧页镜像跑删除恢复（裸页，header 偏移=0）。"""
    if live_text is None:
        live_text = set()
    visited = set()
    for page_num, img in frames:
        if len(img) < page_size:
            continue
        ptype = img[0]
        if ptype not in (0x0D, 0x05):
            continue
        # 用第一张表的列数做宽松匹配（历史页可能属于任意表）
        for tname, (root, cols) in tables.items():
            recover_leaf_deleted(img, 0, cols, 'wal/journal', live_sigs, minlen, maxout, out, live_text)
            # 也尝试无 schema 约束（抓任意残留文本）
            recover_leaf_deleted(img, 0, None, 'wal/journal', live_sigs, minlen, maxout, out, live_text)


# ----------------------------------------------------------------------------
# SQLCipher 解密（可选）
# ----------------------------------------------------------------------------

def decrypt_sqlcipher(db_bytes, key_hex, page_size):
    """解密 legacy SQLCipher 单页流（微信/WCDB 等使用）。
    密钥按长度自动选算法：16 字节 → AES-128，24 → AES-192，32 → AES-256
    （微信真实使用 16 字节 = AES-128）。IV = 页号(4B 大端) + 0*12，无 HMAC、无 KDF。
    key_hex 可为 16 进制字符串或原始字节。需要 cryptography 库。"""
    if isinstance(key_hex, (bytes, bytearray)):
        key = bytes(key_hex)
    else:
        key = bytes.fromhex(key_hex)
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
    except Exception as e:
        raise RuntimeError("解密需要 cryptography 库：pip install cryptography（%s）" % e)
    out = bytearray()
    n = len(db_bytes) // page_size
    for i in range(n):
        page = db_bytes[i*page_size:(i+1)*page_size]
        iv = struct.pack('>II', i+1, 0) + b'\x00'*8  # SQLCipher IV = 页码(4) + 0*12
        dec = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        d = dec.decryptor()
        out += d.update(page) + d.finalize()
    return bytes(out)


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def recover_file(db_path, minlen=4, maxout=200, wal_path=None, journal_path=None,
                 decrypt_key=None, page_size=None, as_json=False, deep_carve=True):
    if not os.path.exists(db_path):
        print("ERROR: 文件不存在: %s" % db_path, file=sys.stderr)
        return None
    with open(db_path, 'rb') as f:
        db = f.read()

    if page_size is None:
        page_size = get_page_size(db)
    if page_size is None:
        page_size = 4096

    # 可选解密
    if decrypt_key:
        db = decrypt_sqlcipher(db, decrypt_key, page_size)

    live_sigs = set()
    live_text = set()
    leaf_pages = set()
    tables = collect_live_and_leaves(db, page_size, live_sigs, leaf_pages, live_text)

    out = []
    # 主库：对每张表的叶页跑删除恢复
    for tname, (root, cols) in tables.items():
        for pn in leaf_pages:
            base = page_base(pn, page_size)
            if base + page_size > len(db):
                continue
            page = db[base:base + page_size]
            recover_leaf_deleted(page, btree_header_offset(pn, 'main'), cols, 'db',
                                 live_sigs, minlen, maxout, out, live_text)
            # 无 schema 约束兜底（抓跨表残留）
            recover_leaf_deleted(page, btree_header_offset(pn, 'main'), None, 'db',
                                 live_sigs, minlen, maxout, out, live_text)

    # 深度雕刻区域收集（主库 + WAL/Journal 帧镜像）
    carve_regions = [('db', db)]

    # WAL
    if wal_path is None:
        cand = db_path + '-wal'
        if os.path.exists(cand):
            wal_path = cand
    if wal_path:
        frames = parse_wal(wal_path, page_size)
        recover_frames(frames, page_size, tables, live_sigs, minlen, maxout, out, live_text)
        for pn, img in frames:
            carve_regions.append(('wal:%d' % pn, img))

    # Journal
    if journal_path is None:
        cand = db_path + '-journal'
        if os.path.exists(cand):
            journal_path = cand
    if journal_path:
        frames = parse_journal(journal_path, page_size)
        recover_frames(frames, page_size, tables, live_sigs, minlen, maxout, out, live_text)
        for pn, img in frames:
            carve_regions.append(('journal:%d' % pn, img))

    # 深度雕刻（FQLite 式纯 carving 深度）：对整个库字节及 WAL/Journal 帧镜像
    # 全文扫描可打印片段，捕获游离在 slack/freeblock 之外的残留文本
    # （例如被复用但未完全覆盖的页、checkpoint 后残留、文件级未分配空间等）。
    # 这些片段置信度低（source='carve'），与结构化恢复区分呈现。
    if deep_carve:
        cmin = max(minlen, 6)
        for rname, region in carve_regions:
            if len(region) < cmin:
                continue
            for frag in _extract_fragments(region, cmin):
                _emit_fragment(frag, 'carve', live_text, maxout, out)

    # 去重（跨来源）
    seen = set()
    final = []
    for r in out:
        sig = (len(r['values']), tuple(_norm(v) for v in r['values']))
        if sig in seen:
            continue
        seen.add(sig)
        final.append(r)

    if as_json:
        return {'tables': {k: {'rootpage': v[0], 'cols': v[1]} for k, v in tables.items()},
                'recovered': final}
    # 文本输出
    print("数据库: %s" % db_path)
    print("页大小: %d  表数量: %d  活记录签名: %d  叶页: %d" %
          (page_size, len(tables), len(live_sigs), len(leaf_pages)))
    print("=" * 60)
    if not final:
        print("未发现被删/残留记录。")
        return None
    for r in final:
        cols = r['cols'] or []
        print("[来源:%s]" % r['source'])
        for i, v in enumerate(r['values']):
            label = cols[i] if i < len(cols) else ("col%d" % i)
            if isinstance(v, (bytes, bytearray)):
                v = "<BLOB %d字节>" % len(v)
            print("  %-20s : %s" % (label, v))
        print("-" * 60)
    n_carved = sum(1 for r in final if r.get('_frag'))
    print("共恢复 %d 条（其中结构化 %d 条，深度雕刻 %d 条）。" %
          (len(final), len(final) - n_carved, n_carved))
    return final


def main_argv(argv):
    p = argparse.ArgumentParser(description="SQLite 删除记录取证恢复")
    p.add_argument("db")
    p.add_argument("minlen", nargs="?", type=int, default=4)
    p.add_argument("maxout", nargs="?", type=int, default=200)
    p.add_argument("--wal", default=None)
    p.add_argument("--journal", default=None)
    p.add_argument("--decrypt-key", default=None)
    p.add_argument("--page-size", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-deep-carve", action="store_true", help="关闭全文件/帧镜像深度雕刻")
    a = p.parse_args(argv)
    res = recover_file(a.db, a.minlen, a.maxout, a.wal, a.journal,
                       a.decrypt_key, a.page_size, a.json, not a.no_deep_carve)
    if a.json and res:
        print(json.dumps(res, ensure_ascii=False))


if __name__ == '__main__':
    main_argv(sys.argv[1:])
