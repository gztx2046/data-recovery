#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all.py  —  data-recovery 套件自测（合成数据，无需真实设备/库）
==============================================================
覆盖：
  T1 普通 DELETE → 页 slack 恢复
  T2 WAL 历史页恢复
  T3 误报检查（活记录不应作为“被删”输出）
  T4 freeblock 链恢复（中部删除）
  T5 微信 key 推导 + 离线校验
  T6 iOS 备份目录恢复（扩展名 + 魔数/哈希命名）
  T7 统一编排器 单文件/目录 双分支
  T8 端到端：加密库 → 推导 key → 解密 → 恢复被删
  T9 深度雕刻：游离残留（全文件扫描，超出页边界）
  T10 APK 降级免 root：命令构造 + 安全闸门
  T11 微信密钥 多页大小穷举（非默认页大小）
  T12 设备拉取：命令构造 + 安全闸门 + 包发现

用法：
  python tests/run_all.py          # 标准库部分（T1-T4, T6-T7）
  python tests/run_all.py --full   # 含需 cryptography 的 T5/T8（请先 pip install cryptography）
"""
import sqlite3, os, sys, tempfile, struct, hashlib, io, contextlib, argparse, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import sqlite_recover as R
import ios_backup_recover as I
import android_triage as A
import recover_orchestrator as O
import wechat_key as W
import apk_downgrade as AD

TMP = tempfile.gettempdir()
PASS = []   # 真实通过/失败
SKIP = []   # 因缺少依赖/环境而跳过的项（不计入通过数）


def check(name, cond, detail=""):
    PASS.append(cond)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))


def skip(name, detail=""):
    SKIP.append(name)
    print("  [SKIP] %s %s" % (name, detail))


# ---------- T1/T2/T3 ----------
def test_slack_wal_fp():
    print("== T1/T2/T3: slack / WAL / 无 false-positive ==")
    main_db = os.path.join(TMP, "ra_main.db")
    wal_db = os.path.join(TMP, "ra_wal.db")
    for p in (main_db, wal_db):
        if os.path.exists(p): os.remove(p)
    con = sqlite3.connect(main_db); cur = con.cursor()
    cur.execute("CREATE TABLE chat(id INTEGER PRIMARY KEY, name TEXT, msg TEXT)")
    for i in range(1, 20):
        cur.execute("INSERT INTO chat(name,msg) VALUES(?,?)", ("用户%d"%i,"正常消息%d"%i))
    cur.execute("INSERT INTO chat(name,msg) VALUES(?,?)", ("机密人","秘密被删的对话内容ABC"))
    con.commit(); cur.execute("DELETE FROM chat WHERE name=?", ("机密人",)); con.commit(); con.close()
    res = R.recover_file(main_db, 4, 200, as_json=True)
    f1 = any(any(isinstance(v,str) and "秘密被删" in v for v in r['values']) for r in res['recovered'])
    check("T1 slack 恢复", f1)
    # 误报
    fp = sum(1 for r in res['recovered']
             if any(isinstance(v,str) and v.startswith("正常消息") for v in r['values']))
    check("T3 无误报", fp == 0, "误报=%d"%fp)

    con = sqlite3.connect(wal_db); cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("CREATE TABLE note(id INTEGER PRIMARY KEY, t TEXT)")
    for i in range(30): cur.execute("INSERT INTO note(t) VALUES(?)", ("正常笔记%d"%i,))
    cur.execute("INSERT INTO note(t) VALUES(?)", ("WAL里的临时秘密XYZ",))
    con.commit(); cur.execute("DELETE FROM note WHERE t=?", ("WAL里的临时秘密XYZ",)); con.commit(); con.close()
    res2 = R.recover_file(wal_db, 4, 200, as_json=True)
    f2 = any(any(isinstance(v,str) and "WAL里" in v for v in r['values']) for r in res2['recovered'])
    check("T2 WAL 恢复", f2)


# ---------- T4 ----------
def test_freeblock():
    print("== T4: freeblock 链（中部删除）==")
    p = os.path.join(TMP, "ra_fb.db")
    if os.path.exists(p): os.remove(p)
    con = sqlite3.connect(p); cur = con.cursor()
    cur.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(1, 31):
        cur.execute("INSERT INTO t(v) VALUES(?)", ("内容填充行%d用来撑满页面避免复用"%i,))
    con.commit(); cur.execute("DELETE FROM t WHERE id=15"); con.commit(); con.close()
    res = R.recover_file(p, 4, 200, as_json=True)
    f = any(any(isinstance(v,str) and "内容填充行15" in v for v in r['values']) for r in res['recovered'])
    check("T4 freeblock 恢复", f)


# ---------- T5 ----------
def test_wechat(full):
    print("== T5: 微信 key 推导 + 离线校验 ==")
    if not full:
        skip("T5 微信 key 推导+校验（需 cryptography，--full 启用）"); return
    import wechat_key as W
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    IMEI, UIN = "868659010000001", "123456789"
    p = os.path.join(TMP, "ra_wx.db")
    if os.path.exists(p): os.remove(p)
    con = sqlite3.connect(p); cur = con.cursor()
    cur.execute("CREATE TABLE msg(id INTEGER PRIMARY KEY, t TEXT)")
    for i in range(20): cur.execute("INSERT INTO msg(t) VALUES(?)", ("微信记录%d"%i,))
    con.commit(); con.close()
    with open(p,'rb') as f: plain=f.read()
    if len(plain)%4096: plain += b'\x00'*(4096-len(plain)%4096)
    key = hashlib.md5((IMEI+UIN).encode()).digest()
    out=bytearray(); n=len(plain)//4096
    for i in range(n):
        pg=plain[i*4096:(i+1)*4096]; iv=struct.pack('>II',i+1,0)+b'\x00'*8
        e=Cipher(algorithms.AES(key),modes.CBC(iv),backend=default_backend()).encryptor()
        out+=e.update(pg)+e.finalize()
    with open(p,'wb') as f: f.write(bytes(out))
    hit = W.verify(p, IMEI, UIN)
    check("T5 key 命中", hit is not None and hit[0]=="md5(imei+uin)")
    hit2 = W.verify(p, "wrong", UIN)
    check("T5 错误拒识", hit2 is None)


# ---------- T6 ----------
def test_ios():
    print("== T6: iOS 备份目录（扩展名 + 魔数/哈希命名）==")
    root = os.path.join(TMP, "ra_ios")
    if os.path.exists(root): shutil.rmtree(root)
    os.makedirs(root)
    def mk(path, secret):
        if os.path.exists(path): os.remove(path)
        c=sqlite3.connect(path); cu=c.cursor()
        cu.execute("CREATE TABLE sms(id INTEGER PRIMARY KEY, body TEXT)")
        for i in range(15): cu.execute("INSERT INTO sms(body) VALUES(?)", ("短信%d"%i,))
        cu.execute("INSERT INTO sms(body) VALUES(?)", (secret,))
        c.commit(); cu.execute("DELETE FROM sms WHERE body=?", (secret,)); c.commit(); c.close()
    mk(os.path.join(root,"sms.db"), "iOS已删AAA")
    mk(os.path.join(root,"a"*40), "iOS已删BBB")
    dbs, results, skipped = I.recover_backup(root, 4, 200)
    txt=[]
    for _,recs in results:
        for r in recs:
            for v in r['values']:
                if isinstance(v,str): txt.append(v)
    check("T6 扩展名扫描", any("AAA" in t for t in txt))
    check("T6 魔数扫描(哈希名)", any("BBB" in t for t in txt))


# ---------- T7 ----------
def test_orchestrator():
    print("== T7: 统一编排器 单文件/目录 ==")
    sdb = os.path.join(TMP, "ra_orb.db")
    if os.path.exists(sdb): os.remove(sdb)
    c=sqlite3.connect(sdb); cu=c.cursor()
    cu.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(10): cu.execute("INSERT INTO t(v) VALUES(?)", ("单文件行%d"%i,))
    cu.execute("INSERT INTO t(v) VALUES(?)", ("编排器被删ZZZ",))
    c.commit(); cu.execute("DELETE FROM t WHERE v=?", ("编排器被删ZZZ",)); c.commit(); c.close()
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf):
        O.main_argv([sdb,"--minlen","4"])
    ok1 = "ZZZ" in buf.getvalue()
    check("T7 单文件分支", ok1)

    rdir=os.path.join(TMP,"ra_orb_dir")
    if os.path.exists(rdir): shutil.rmtree(rdir)
    os.makedirs(rdir)
    for nm,sec in [("x.db","目录AAA"),("y"*40,"目录BBB")]:
        pp=os.path.join(rdir,nm)
        cc=sqlite3.connect(pp); ccu=cc.cursor()
        ccu.execute("CREATE TABLE m(id INTEGER PRIMARY KEY, b TEXT)")
        for i in range(8): ccu.execute("INSERT INTO m(b) VALUES(?)", ("q%d"%i,))
        ccu.execute("INSERT INTO m(b) VALUES(?)", (sec,))
        cc.commit(); ccu.execute("DELETE FROM m WHERE b=?", (sec,)); cc.commit(); cc.close()
    buf2=io.StringIO()
    with contextlib.redirect_stdout(buf2):
        O.main_argv([rdir,"--minlen","4"])
    ok2 = "AAA" in buf2.getvalue() and "BBB" in buf2.getvalue()
    check("T7 目录分支", ok2)


# ---------- T8 ----------
def test_integration(full):
    print("== T8: 端到端 加密库→key→解密→恢复 ==")
    if not full:
        skip("T8 端到端加密链路（需 cryptography，--full 启用）"); return
    import wechat_key as W
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    IMEI, UIN = "868659010000001", "123456789"; PS=4096
    plain=os.path.join(TMP,"ra_int_plain.db"); enc=os.path.join(TMP,"ra_int_enc.db")
    if os.path.exists(plain): os.remove(plain)
    c=sqlite3.connect(plain); cu=c.cursor()
    cu.execute("CREATE TABLE chat(id INTEGER PRIMARY KEY, who TEXT, msg TEXT)")
    for i in range(12): cu.execute("INSERT INTO chat(who,msg) VALUES(?,?)", ("A%d"%i,"消息%d"%i))
    cu.execute("INSERT INTO chat(who,msg) VALUES(?,?)", ("老板","已删机密:项目代号黑桃Q"))
    c.commit(); cu.execute("DELETE FROM chat WHERE who=?", ("老板",)); c.commit(); c.close()
    with open(plain,'rb') as f: data=f.read()
    if len(data)%PS: data+=b'\x00'*(PS-len(data)%PS)
    key=hashlib.md5((IMEI+UIN).encode()).digest()
    out=bytearray(); n=len(data)//PS
    for i in range(n):
        pg=data[i*PS:(i+1)*PS]; iv=struct.pack('>II',i+1,0)+b'\x00'*8
        e=Cipher(algorithms.AES(key),modes.CBC(iv),backend=default_backend()).encryptor()
        out+=e.update(pg)+e.finalize()
    with open(enc,'wb') as f: f.write(bytes(out))
    hit=W.verify(enc, IMEI, UIN)
    check("T8 key 命中", hit is not None)
    if hit:
        with open(enc,'rb') as f: edb=f.read()
        pt=R.decrypt_sqlcipher(edb, hit[1], PS)
        tmp2=os.path.join(TMP,"ra_int_dec.db")
        with open(tmp2,'wb') as f: f.write(pt)
        res=R.recover_file(tmp2,4,200,as_json=True)
        fnd=any(any(isinstance(v,str) and "黑桃Q" in v for v in r['values']) for r in res['recovered'])
        check("T8 解密后恢复", fnd)


# ---------- T9 ----------
def test_deep_carve():
    print("== T9: 深度雕刻（游离残留，全文件扫描）==")
    p = os.path.join(TMP, "ra_deep.db")
    if os.path.exists(p): os.remove(p)
    con = sqlite3.connect(p); cur = con.cursor()
    cur.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(10): cur.execute("INSERT INTO t(v) VALUES(?)", ("行%d" % i,))
    cur.execute("INSERT INTO t(v) VALUES(?)", ("深度雕刻标记DEEPCARVE",))
    con.commit(); cur.execute("DELETE FROM t WHERE v=?", ("深度雕刻标记DEEPCARVE",)); con.commit(); con.close()
    # 模拟“游离残留”：在文件末尾追加含秘密的脏数据（超出最后一页，结构化恢复够不到）
    with open(p, 'ab') as f:
        f.write(b"\x00\x00GARBAGE\x00\x00" + "残留游离秘密FREEFLOATXYZ".encode('utf-8') + b"\x00\x00JUNK")
    res = R.recover_file(p, 4, 200, as_json=True)
    vals = []
    for r in res['recovered']:
        for v in r['values']:
            if isinstance(v, str):
                vals.append(v)
    f1 = any("深度雕刻标记" in v for v in vals)        # 结构化(slack)也应找到
    f2 = any("FREEFLOATXYZ" in v for v in vals)        # 只有深度雕刻能找到
    check("T9 结构化仍命中", f1)
    check("T9 深度雕刻命中游离残留", f2)


# ---------- T10 ----------
def test_apk_downgrade():
    print("== T10: APK 降级免 root（命令构造 + 安全闸门）==")
    cmds = []
    def fake_runner(cmd, timeout=90):
        cmds.append(cmd)
        s = " ".join(cmd)
        if "devices" in s:
            return (0, "List of devices attached\nABC123\tdevice\n", "")
        if "dumpsys" in s:
            return (0, "    versionName=8.0.46\n", "")
        return (0, "", "")
    ok, _ = AD.device_present("adb", fake_runner)
    check("T10 设备检测解析", ok is True)
    ver, _ = AD.get_wechat_version("adb", fake_runner)
    check("T10 版本解析", ver == "8.0.46")
    apk = os.path.join(TMP, "old.apk")
    open(apk, "wb").close()   # 真实存在，绕过“apk 不存在”的安全拦截
    rc, out, err = AD.install_downgrade("adb", apk, False, fake_runner)
    check("T10 降级安全闸门(未确认拒绝)", rc == 1 and "安全闸门" in (out + err))
    rc, out, err = AD.install_downgrade("adb", apk, True, fake_runner)
    cmd = cmds[-1]
    check("T10 降级命令构造", cmd[0] == "adb" and "install" in cmd and "-r" in cmd and "-d" in cmd and cmd[-1] == apk)
    bc = AD.build_backup_cmd("adb", "com.tencent.mm", "x.ab")
    check("T10 backup 命令构造", bc[:2] == ["adb", "backup"] and "-noapk" in bc and "com.tencent.mm" in bc)


# ---------- T11 ----------
def test_wechat_rotation(full):
    print("== T11: 微信密钥 多页大小穷举（非默认页大小/轮换）==")
    if not full:
        skip("T11 多页大小穷举（需 cryptography，--full 启用）"); return
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    IMEI, UIN = "868659010000001", "123456789"; PS = 1024
    plain = os.path.join(TMP, "ra_rot_plain.db"); enc = os.path.join(TMP, "ra_rot_enc.db")
    if os.path.exists(plain): os.remove(plain)
    c = sqlite3.connect(plain); cu = c.cursor()
    cu.execute("PRAGMA page_size=1024")   # 明文页大小=1024，与加密块大小一致（贴近真实 SQLCipher）
    cu.execute("CREATE TABLE chat(id INTEGER PRIMARY KEY, who TEXT, msg TEXT)")
    for i in range(10): cu.execute("INSERT INTO chat(who,msg) VALUES(?,?)", ("A%d" % i, "m%d" % i))
    cu.execute("INSERT INTO chat(who,msg) VALUES(?,?)", ("老板", "已删机密:代号梅花J"))
    c.commit(); cu.execute("DELETE FROM chat WHERE who=?", ("老板",)); c.commit(); c.close()
    with open(plain, 'rb') as f: data = f.read()
    if len(data) % PS: data += b'\x00' * (PS - len(data) % PS)
    key = hashlib.md5((IMEI + UIN).encode()).digest()
    out = bytearray(); n = len(data) // PS
    for i in range(n):
        pg = data[i*PS:(i+1)*PS]; iv = struct.pack('>II', i+1, 0) + b'\x00'*8
        e = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).encryptor()
        out += e.update(pg) + e.finalize()
    with open(enc, 'wb') as f: f.write(bytes(out))
    hit = W.verify(enc, IMEI, UIN)
    check("T11 非默认页大小(1024)命中", hit is not None and hit[2] == 1024)


# ---------- T12 ----------
def test_android_pull():
    print("== T12: 设备拉取（命令构造 + 安全闸门）==")
    cmds = []
    def fake_runner(cmd, timeout=90):
        cmds.append(cmd)
        return (0, "", "")
    d, info = A.pull_device("adb", "com.tencent.mm", "work", False, None, fake_runner)
    check("T12 拉取安全闸门(未确认拒绝)", d is None and "安全闸门" in info)
    d, info = A.pull_device("adb", "com.tencent.mm", "work", True, None, fake_runner)
    # 已确认：越过安全闸门（info 不含拒绝提示）；测试环境无 java/abe，extract 会如实返回 None
    # —— 这里同时验证了“失败不再谎报成功”（d is None 而非假目录）
    check("T12 确认后越过安全闸门且如实返回", d is None and "安全闸门" not in info)
    def fake_runner2(cmd, timeout=90):
        if "list packages" in " ".join(cmd):
            return (0, "package:com.tencent.mm\npackage:com.android.x\n", "")
        return (0, "", "")
    pkgs = A.discover_packages("adb", fake_runner2)
    check("T12 包发现过滤", "com.tencent.mm" in pkgs and len(pkgs) == 1)
    check("T12 触发 backup 命令", any("backup" in " ".join(c) for c in cmds))


# ---------- T13 ----------
def test_tar_safe():
    print("== T13: tar 解压路径穿越防护（CVE-2007-4559）==")
    import tarfile, io
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tf:
        d = b"ok"
        ti = tarfile.TarInfo(name="good/ok.txt"); ti.size = len(d)
        tf.addfile(ti, io.BytesIO(d))
        # 越界成员：../ 跳出 out_dir
        ti2 = tarfile.TarInfo(name="../escape.txt"); ti2.size = len(d)
        tf.addfile(ti2, io.BytesIO(d))
    raw.seek(0)
    out_dir = os.path.join(TMP, "ra_tar_safe")
    if os.path.exists(out_dir): shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    with tarfile.open(fileobj=raw, mode="r") as tf:
        try:
            AD._safe_extract_tar(tf, out_dir)
            raised = False
        except ValueError:
            raised = True
    check("T13 拒绝越界成员", raised)
    # 确认没有任何文件被写到 out_dir 之外（越界落盘点）
    check("T13 无越界落盘", not os.path.exists(os.path.join(TMP, "escape.txt")))


if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--full",action="store_true"); a=ap.parse_args()
    test_slack_wal_fp(); test_freeblock(); test_wechat(a.full)
    test_ios(); test_orchestrator(); test_integration(a.full)
    test_deep_carve(); test_apk_downgrade(); test_wechat_rotation(a.full); test_android_pull()
    test_tar_safe()
    print("\n===== 汇总: %d/%d 通过，%d 跳过 =====" % (sum(PASS), len(PASS), len(SKIP)))
    if SKIP:
        print("（跳过项不计入通过/失败；用 --full 并安装 cryptography 可补齐 T5/T8/T11）")
    sys.exit(0 if all(PASS) else 1)
