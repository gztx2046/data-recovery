#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apk_downgrade.py  —  Android 免 root 取微信数据库（Avilla 式思路，工程化）
=========================================================================
核心思路（来自 Avilla Forensics 的免 root 技巧）：
  新版微信在 Android 12+ 上禁止 `adb backup`（allowBackup=false），且 scoped storage
  让直接 `adb pull` 私有目录失败。解决路径是“降级安装”旧版微信：
    1) 先 `adb backup` 把当前微信数据备份出来（保险，防丢）；
    2) `adb install -r -d 旧版微信.apk`：`-r` 保留数据、`-d` 允许降级；
       旧版微信的 manifest 允许 `adb backup`；
    3) 再 `adb backup -f wx.ab com.tencent.mm` 导出数据（含 EnMicroMsg.db 密文）；
    4) 用 Android Backup Extractor (abe) 把 .ab 解成 tar，取出数据库；
    5) 配合 wechat_key.py 用 IMEI+UIN 推导出密钥后解密、恢复。

【安全红线（务必遵守）】
  - 一切有数据风险的操作（backup / install -d 降级 / pull）都必须显式 confirmed=True，
    CLI 上用 --i-understand 开启；否则一律拒绝并给出提示。
  - install -d 降级在极少数 ROM 上仍可能清数据，脚本不替你决定，必须你确认。
  - 本脚本只生成/执行 adb 命令并打印结果，不修改任何本地个人文件。

【可测试性】
  所有 adb 调用都经 `runner(cmd)` 注入；测试时传入假 runner 即可校验命令构造与
  安全闸门，无需真机。

用法：
  python apk_downgrade.py check
  python apk_downgrade.py version
  python apk_downgrade.py backup   --pkg com.tencent.mm --ab out/wx_before.ab --i-understand
  python apk_downgrade.py downgrade --apk old_wechat.apk --i-understand
  python apk_downgrade.py extract  --ab out/wx.ab --out out/wx_extracted
  python apk_downgrade.py pull     --pkg com.tencent.mm --out out/dbs --i-understand
  python apk_downgrade.py workflow --apk old_wechat.apk --out work
"""
import os
import sys
import shutil
import subprocess
import argparse

WX_PKG = "com.tencent.mm"
DEFAULT_SDK_REL = "platform-tools/adb.exe"


def _real_runner(cmd, timeout=90):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.returncode, r.stdout, r.stderr)
    except Exception as e:
        return (-1, "", str(e))


def find_adb():
    """定位 adb：优先 PATH，其次常见 Android SDK 路径与环境变量。"""
    on_path = shutil.which("adb")
    if on_path:
        return on_path
    candidates = []
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(env)
        if v:
            candidates.append(os.path.join(v, DEFAULT_SDK_REL))
    user = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
    if user:
        candidates.append(os.path.join(user, "AppData", "Local", "Android", "Sdk", DEFAULT_SDK_REL))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def device_present(adb_exe, runner=_real_runner):
    rc, out, err = runner([adb_exe, "devices"])
    if rc != 0:
        return False, (out + err).strip()
    # 出现 "<serial>\tdevice" 视为已授权连接
    for line in out.splitlines()[1:]:
        if line.strip().endswith("device"):
            return True, out.strip()
    return False, out.strip() or (err.strip() or "无已授权设备")


def get_wechat_version(adb_exe, runner=_real_runner):
    rc, out, err = runner([adb_exe, "shell", "dumpsys", "package", WX_PKG])
    if rc != 0:
        return None, (out + err).strip()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("versionName="):
            return line.split("=", 1)[1].strip(), out
    return None, out


def build_backup_cmd(adb_exe, pkg, ab_path, no_apk=True):
    opts = ["-noapk"] if no_apk else ["-apk"]
    return [adb_exe, "backup", "-f", ab_path] + opts + [pkg]


def backup_app(adb_exe, pkg, ab_path, confirmed, runner=_real_runner):
    """adb backup 导出 app 数据（保险手段）。confirmed 否则拒绝。"""
    if not confirmed:
        return (1, "", "安全闸门：backup 需要 --i-understand 显式确认（请在设备上点“备份我的数据”）。")
    os.makedirs(os.path.dirname(os.path.abspath(ab_path)), exist_ok=True)
    cmd = build_backup_cmd(adb_exe, pkg, ab_path)
    return runner(cmd)


def build_downgrade_cmd(adb_exe, apk_path):
    # -r 保留数据；-d 允许版本降级（覆盖安装旧版）
    return [adb_exe, "install", "-r", "-d", apk_path]


def install_downgrade(adb_exe, apk_path, confirmed, runner=_real_runner):
    """降级安装旧版微信（保留数据）。confirmed 否则拒绝。"""
    if not confirmed:
        return (1, "", "安全闸门：降级安装有数据风险，需要 --i-understand 显式确认。")
    if not os.path.exists(apk_path):
        return (2, "", "APK 不存在: %s" % apk_path)
    cmd = build_downgrade_cmd(adb_exe, apk_path)
    return runner(cmd)


def _safe_extract_tar(tf, out_dir):
    """安全解压 tar：逐个成员校验路径，拦截 CVE-2007-4559 路径穿越。
    任何成员若以绝对路径开头、含 '..' 段、或落点越出 out_dir，一律拒绝并整体中止
    （不部分解压被篡改的归档）。硬链接/符号链接的目标同样校验。"""
    out_dir_abs = os.path.abspath(out_dir)
    os.makedirs(out_dir_abs, exist_ok=True)
    for m in tf.getmembers():
        name = m.name
        if name.startswith("/") or name.startswith("\\") or ".." in name.replace("\\", "/").split("/"):
            raise ValueError("拒绝越界成员: %r" % name)
        target = os.path.normpath(os.path.join(out_dir_abs, name))
        if target != out_dir_abs and not target.startswith(out_dir_abs + os.sep):
            raise ValueError("拒绝越界成员: %r -> %r" % (name, target))
        if m.issym() or m.islnk():
            link = m.linkname.replace("\\", "/")
            if link.startswith("/") or link.startswith("\\") or ".." in link.split("/"):
                raise ValueError("拒绝越界链接: %r -> %r" % (name, m.linkname))
            link_target = os.path.normpath(os.path.join(out_dir_abs, m.linkname))
            if link_target != out_dir_abs and not link_target.startswith(out_dir_abs + os.sep):
                raise ValueError("拒绝越界链接: %r -> %r" % (name, m.linkname))
    for m in tf.getmembers():
        if not (m.isdir() or m.issym() or m.islnk()):
            parent = os.path.dirname(os.path.normpath(os.path.join(out_dir_abs, m.name)))
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
        tf.extract(m, out_dir_abs)
    return True


def extract_ab(ab_path, out_dir, java_exe=None, abe_jar=None, runner=_real_runner):
    """用 Android Backup Extractor 解 .ab。java/abe 缺失时返回指引。"""
    if not os.path.exists(ab_path):
        return (2, "", "备份文件不存在: %s" % ab_path)
    os.makedirs(out_dir, exist_ok=True)
    java_exe = java_exe or shutil.which("java")
    if not java_exe or not abe_jar or not os.path.exists(abe_jar):
        return (3, "", "未找到 java 或 abe.jar（Android Backup Extractor）。请安装后重试，"
                        "或手动：java -jar abe.jar unpack %s <输出tar>" % ab_path)
    tar_path = os.path.join(out_dir, "backup.tar")
    cmd = [java_exe, "-jar", abe_jar, "unpack", ab_path, tar_path]
    rc, out, err = runner(cmd)
    if rc != 0:
        return (rc, out, err)
    # 安全解压 tar（防路径穿越 CVE-2007-4559，详见 _safe_extract_tar）
    try:
        import tarfile
        with tarfile.open(tar_path) as tf:
            _safe_extract_tar(tf, out_dir)
    except Exception as e:
        return (4, out, "tar 解包失败: %s（但 backup.tar 已生成于 %s）" % (e, tar_path))
    return (0, "已解压到 %s" % out_dir, "")


def pull_root(adb_exe, pkg, remote_db, local_dir, runner=_real_runner):
    """root / run-as 情形下直接 adb pull 私有数据库。best-effort。"""
    os.makedirs(local_dir, exist_ok=True)
    local = os.path.join(local_dir, os.path.basename(remote_db))
    return runner([adb_exe, "pull", remote_db, local])


def pull_via_backup(adb_exe, pkg, workdir, confirmed, abe_jar=None, java_exe=None, runner=_real_runner):
    """编排：backup → extract。返回 (extracted_dir, (rc,out,err))。"""
    if not confirmed:
        return None, (1, "", "安全闸门：pull 需要 --i-understand 显式确认。")
    os.makedirs(workdir, exist_ok=True)
    ab_path = os.path.join(workdir, "wx.ab")
    rc, out, err = backup_app(adb_exe, pkg, ab_path, True, runner)
    if rc != 0:
        return None, (rc, out, err)
    out_dir = os.path.join(workdir, "extracted")
    rc, out2, err2 = extract_ab(ab_path, out_dir, java_exe, abe_jar, runner)
    if rc != 0:
        # 解压/备份失败：返回 None，避免上层误判“已拿到数据”
        return None, (rc, out + "\n" + out2, err2)
    return out_dir, (rc, out + "\n" + out2, err2)


def main_argv(argv):
    p = argparse.ArgumentParser(description="Android 免 root 取微信数据库（降级法）")
    sub = p.add_subparsers(dest="cmd")
    for name in ("check", "version", "backup", "downgrade", "extract", "pull", "workflow"):
        sp = sub.add_parser(name)
        sp.add_argument("--pkg", default=WX_PKG)
        sp.add_argument("--adb", default=None)
        sp.add_argument("--ab", default=None)
        sp.add_argument("--apk", default=None)
        sp.add_argument("--out", default=None)
        sp.add_argument("--abe", default=None, help="abe.jar 路径（extract 用）")
        sp.add_argument("--i-understand", action="store_true", help="开启有数据风险的操作")
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return
    adb_exe = a.adb or find_adb()
    if a.cmd in ("version", "backup", "downgrade", "pull", "workflow") and not adb_exe:
        print("未找到 adb。请安装 Android 平台工具并加入 PATH，或 --adb 指定路径。")
        return

    if a.cmd == "check":
        adb_exe = adb_exe or "(未找到)"
        ok, info = device_present(adb_exe) if os.path.exists(adb_exe) else (False, "adb 未找到")
        print("adb: %s" % adb_exe)
        print("设备: %s" % ("已连接" if ok else "未连接/未授权"))
        if info:
            print(info)
        return

    if a.cmd == "version":
        ver, _ = get_wechat_version(adb_exe)
        print("微信版本: %s" % (ver or "未知（需设备连接与授权）"))
        return

    if a.cmd == "backup":
        rc, out, err = backup_app(adb_exe, a.pkg, a.ab or "wx_before.ab", a.i_understand)
        print(out); print(err, file=sys.stderr)
        return

    if a.cmd == "downgrade":
        rc, out, err = install_downgrade(adb_exe, a.apk, a.i_understand)
        print(out); print(err, file=sys.stderr)
        return

    if a.cmd == "extract":
        rc, out, err = extract_ab(a.ab or "wx.ab", a.out or "wx_extracted", None, a.abe)
        print(out); print(err, file=sys.stderr)
        return

    if a.cmd == "pull":
        d, (rc, out, err) = pull_via_backup(adb_exe, a.pkg, a.out or "work", a.i_understand, a.abe)
        print(out); print(err, file=sys.stderr)
        if d:
            print(">>> 数据库解压目录: %s （再用 wechat_key.py 推导密钥后交给 sqlite_recover.py）" % d)
        return

    if a.cmd == "workflow":
        print(">>> 免 root 取微信数据库 推荐流程：")
        print("  1. python apk_downgrade.py check            # 确认 adb 与设备")
        print("  2. python apk_downgrade.py backup --i-understand   # 先备一份当前数据")
        print("  3. python apk_downgrade.py downgrade --apk 旧版微信.apk --i-understand  # 降级保留数据")
        print("  4. python apk_downgrade.py pull --i-understand --abe abe.jar   # backup+解压")
        print("  5. python wechat_key.py --pull 或手动 --imei/--uin 推导密钥")
        print("  6. python sqlite_recover.py <解压出的 EnMicroMsg.db> --decrypt-key <密钥>")
        return


if __name__ == "__main__":
    main_argv(sys.argv[1:])
