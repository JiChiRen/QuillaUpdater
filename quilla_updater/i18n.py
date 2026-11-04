# -*- coding: utf-8 -*-
# Copyright (c) 2026, JiChiRen Info. Tech.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# ``AS IS`` AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# This file is part of QuillaUpdater.

"""
Bilingual strings for the whole tool (GUI chrome, status, dialogs, and the
operator-facing log / error lines emitted by session.py).

Design:
  * Two flat dictionaries, "zh" and "en", keyed by the same identifiers.
  * t(key, **kw) returns the string for the active language, falls back to "en",
    then to the key itself, so a missing key never crashes the UI.
  * Strings that contain a value use {name} placeholders and are filled with
    str.format; if a format fails we return the raw template rather than raise,
    so a typo in a placeholder degrades gracefully.
  * The active language is a module global set by set_language(); both the GUI
    and the worker thread read it at log time, so a language switch mid-run only
    affects log lines emitted afterwards (the history is left as-is).

The Chinese strings are written in a neutral, technical register - no slang, no
exclamation-driven urgency - because this is a production instrument, not a chat.
"""

import locale

_LANG = "zh"

# ------------------------------------------------------------------ detection
def detect_system_language():
    """Return "zh" when the host looks Chinese, else "en"."""
    try:
        loc = locale.getdefaultlocale()[0] or ""
        if loc.lower().startswith("zh"):
            return "zh"
    except Exception:
        pass
    try:
        import ctypes
        # 0x804 = zh-CN, 0x404 = zh-TW / zh-HK
        if ctypes.windll.kernel32.GetUserDefaultUILanguage() in (0x804, 0x404):
            return "zh"
    except Exception:
        pass
    return "en"


def set_language(lang):
    global _LANG
    if lang in ("auto", None, ""):
        _LANG = detect_system_language()
    elif lang in ("en", "english"):
        _LANG = "en"
    else:
        _LANG = "zh"


def get_language():
    return _LANG


# --------------------------------------------------------------------- lookup
def t(key, **kw):
    """Return the string for the active language.

    The table is flat: the Chinese form is stored under `key` and the English
    form under `key + "_en"`. Resolution falls back to the other language, then
    to the key itself, so a missing translation degrades to readable text rather
    than crashing. `str.format` is used for any {placeholder}; a bad format is
    swallowed and the raw template returned.
    """
    if _LANG == "en":
        s = _STRINGS.get(key + "_en", _STRINGS.get(key))
    else:
        s = _STRINGS.get(key, _STRINGS.get(key + "_en"))
    if s is None:
        s = key
    if kw:
        try:
            return s.format(**kw)
        except Exception:
            return s
    return s


# ------------------------------------------------------------------- strings
_STRINGS = {    # ===================== GUI chrome (static) =====================
    "gui.title": "Quilla Updater - QBOOT 串口升级",
    "gui.title_en": "Quilla Updater - QBOOT serial upgrade",

    "gui.serial": " 串口 ",
    "gui.port": "端口",
    "gui.refresh": "刷新",
    "gui.baud": "波特率",

    "gui.firmware": " 固件 ",
    "gui.qapp_bin": "QAPP .bin",
    "gui.browse": "浏览...",

    "gui.signing": " 签名（可选） ",
    "gui.send_sign": "发送 SIGN 帧",
    "gui.private_key": "私钥",

    "gui.actions": " 操作 ",
    "gui.start": "开始升级",
    "gui.cancel": "取消",
    "gui.probe": "探测板卡",
    "gui.clear_log": "清空日志",

    "gui.log": " 日志 ",

    "gui.fw_upgrade": "  固件升级  ",
    "gui.key_tool": "  密钥工具  ",

    "gui.lang": "语言",
    # Language-picker entries. These are autonyms on purpose: a user who
    # cannot read the current UI language must still be able to find their own.
    "gui.lang_pick_auto": "Auto",
    "gui.lang_pick_zh": "中文",
    "gui.lang_pick_english": "English",

    # key tool page
    "gui.gen_keys": " 生成新密钥对 ",
    "gui.output_dir": "输出目录",
    "gui.select": "选择...",
    "gui.gen_keys_btn": "生成密钥对",
    "gui.gen_keys_hint": "写入 private.hex（32 字节种子）和 public.hex。",

    "gui.derive_title": " 由私钥导出公钥 ",
    "gui.priv_file": "私钥文件",
    "gui.derive_btn": "导出公钥",
    "gui.derive_hint": "用于校验设备内已烧录的公钥与本地私钥是否构成匹配密钥对。密钥对不匹配是 SIGN 阶段被拒绝的主要原因。",

    "gui.result": " 结果 ",
    "gui.copy_pub": "复制公钥",
    "gui.copy_macro": "复制编译宏",
    "gui.clear": "清空",

    "gui.key_warn": (
        "私钥应仅保留在签名机。切勿提交到仓库、写入固件或发送给他人。\n"
        "私钥一旦泄露，任何人都能签出设备可接受的镜像，安全启动即失效。"
    ),

    # ===================== GUI messages / dialogs =====================
    "gui.ready_1": "已就绪。请选择串口与固件后点击“开始升级”。",
    "gui.ready_2": "支持在应用程序运行时直接升级；工具会自动切换至升级模式。",

    "gui.no_ports": "未检测到串口。连接 USB 转串口线后点击“刷新”。",

    "gui.dlg_no_port_title": "缺少串口",
    "gui.dlg_no_port": "请先选择一个串口。",
    "gui.dlg_no_fw_title": "缺少固件",
    "gui.dlg_no_fw": "请先选择一个 .bin 固件。",
    "gui.dlg_no_key_title": "未选择私钥",
    "gui.dlg_no_key": (
        "已勾选 SIGN 但私钥为空。\n\n"
        "若设备已烧录公钥，本次升级将在 SIGN 阶段被拒绝。\n"
        "是否继续？"
    ),
    "gui.dlg_invalid_fw_title": "固件无效",
    "gui.dlg_invalid_key_title": "私钥无效",
    "gui.dlg_success_title": "升级成功",
    "gui.dlg_success": "烧录完成：\n\n{stamp}",
    "gui.dlg_cancelled": "已取消。板卡仍保留 QIAP 标志，重新运行即可继续升级。",

    "gui.port_err_busy": "串口被占用",
    "gui.port_err_not_ready": "串口无法配置（可能被调试会话占用）",
    "gui.port_err_not_found": "串口不存在",
    "gui.port_err_other": "串口无法打开",
    "gui.dlg_fail_title": "升级失败",
    "gui.probe_done": (
        "探测完成。part 含 'qboot' -> QBOOT shell；含 'app1' -> APP 在运行；"
        "空且无回显 -> 升级空闲态。"
    ),

    "gui.dlg_no_dir_title": "缺少目录",
    "gui.dlg_no_dir": "请先指定一个输出目录。",
    "gui.dlg_key_exists_title": "私钥已存在",
    "gui.dlg_key_exists": (
        "{path} 已存在。\n\n"
        "覆盖后原私钥将不可恢复。若 QBOOT 内已烧录其对应公钥，该设备将无法再升级"
        "（除非重新烧写 QBOOT）。\n\n"
        "确认覆盖吗？"
    ),
    "gui.dlg_gen_fail_title": "生成失败",
    "gui.dlg_no_clip_title": "无内容",
    "gui.dlg_no_clip": "请先生成或导出一个公钥。",

    # dynamic labels / status
    "gui.status_ready": "就绪",
    "gui.status_connecting": "连接中 ...",
    "gui.status_success": "升级成功",
    "gui.status_cancelled": "已取消",
    "gui.status_port_err": "串口打不开",
    "gui.status_failed": "失败",
    "gui.status_probe_done": "探测完成",

    "gui.fw_none": "未选择固件",
    "gui.fw_info_secver_none": (
        "{name}   {size} KiB   SHA-256 {sha}...   无 .quilla_secver 段（已烧录公钥的 QBOOT 将拒绝该镜像）"
    ),
    "gui.fw_info_secver": (
        "{name}   {size} KiB   SHA-256 {sha}...   安全版本 {ver} (0x{ver:X})"
    ),
    "gui.fw_warn_no_secver": "该固件不含安全版本段，已烧录公钥的设备将以 VER(0x09) 拒绝。",
    "gui.key_info": "公钥 {pk}...  （须与 QBOOT 内已烧录的公钥一致）",
    "gui.key_loaded": "私钥：{name}",
    "gui.done_msg": "升级完成：{result}",
    "gui.detail_speed": "{speed} KiB/s",
    "gui.detail_done": "{total:.1f} 秒（写入 {write:.1f} 秒）  {speed:.1f} KiB/s",
    "gui.detail_eta": "剩余 {eta:.0f} 秒",
    "gui.detail_progress": "{done} / {total} B",
    "gui.writing_pct": "写入中 {pct:.0f}%",
    "gui.sign_detail": "设备侧 Ed25519 验签（耗时数秒至数十秒）",
    "gui.verify_detail": "后置确认：检查随完成码到达的启动横幅（非致命）",

    # phase text
    "phase.detect": "检测板卡状态 ...",
    "phase.enter": "发送 ENTER ...",
    "phase.write": "写入固件",
    "phase.end": "提交长度与 CRC ...",
    "phase.sign": "设备验签中（请勿断电）",
    "phase.verify": "后置确认：短时窥视启动横幅（非致命）...",
    "phase.done": "完成",

    # key tool result lines
    "kt.generated": "已生成密钥对\n",
    "kt.seed_line": "  {path}   32 字节种子，须保密\n",
    "kt.pub_line": "  {path}   烧录至 QBOOT 使用\n\n",
    "kt.pub_hex": "public key (hex):\n",
    "kt.macro_head": "QBOOT 编译宏：\n",
    "kt.derived": "公钥导出成功\n\n",
    "kt.copied": "已复制到剪贴板：{what}\n",

    # ===================== session.py operator-facing lines =====================
    "sess.opened": "已打开 {port} @ {baud} 8N1",
    "sess.reading_banner": "读取设备输出（最长 4 秒）...",
    "sess.already_upgrade": "板卡已处于升级模式（存在 QIAP 标志），将直接发送 ENTER。",
    "sess.not_qboot_try_enter": "未检测到 QBOOT shell；先尝试直接发送 ENTER（兼容升级空闲态）。",
    "sess.app_shell_reset": "检测到 APP shell（part 返回 app1）；通过 swqboot 复位进入 QBOOT。",
    "sess.direct_enter_failed": "直接 ENTER 失败：{err}",
    "sess.swqboot_attempt": "发送 'swqboot'（第 {n} 次）以复位进入 QBOOT ...",
    "sess.port_dropped_wait": "复位后端口 {port} 掉线，等待其重新枚举（最多 {timeout:.0f} 秒）...",
    "sess.post_reset_output": "复位后输出: {data!r}",
    "sess.post_swqboot_part": "swqboot 后 part -> {data!r}",
    "sess.in_qboot_shell": "板卡处于 QBOOT shell。",
    "sess.still_app": "swqboot 后仍处于 APP shell（第 {n} 次），判定复位未生效。",
    "sess.no_echo_assume": "swqboot 后无回显，假定板卡已处于升级空闲态。",
    "sess.board_qboot": "板卡处于 QBOOT shell。",
    "sess.swqboot_fail": (
        "swqboot 未能将板卡切到 QBOOT shell：两次后 part 仍回 'app1'。\n"
        "  1. 在串口终端手动输入 swqboot，确认板卡是否复位\n"
        "  2. 或按下板卡复位键或重新上电，然后重新执行升级\n"
        "（QBOOT 启动后 part 应返回 qboot，而非 app1）"
    ),
    "sess.entered_upgrade": "已切换至升级模式（qiap 第 {n} 次）",
    "sess.enter_accepted": "ENTER 已接受；QIAP 标志已置位，此后掉电可恢复升级。",
    "sess.partition_ok": "分区（来自设备）: APP_START=0x{start:08X} APP_END=0x{end:08X}（{size} B）",
    "sess.partition_fail": "pinfo 未返回分区表（可能为旧版固件）；主机不强制上限，由设备 ADDR NAK(0x01) 决定。",
    "sess.qiap_attempt": "qiap 第 {n} 次未能进入升级模式",
    "sess.port_gone_qiap": "串口 {port} 已离线，无法发送 qiap。请重新连接后重试。",
    "sess.qiap_write_fail": "发送 qiap 时串口断开（{port}）",
    "sess.cannot_enter": (
        "无法进入升级模式。请将板卡置于 QBOOT shell（手动发送 'qiap'，或复位板卡），"
        "或先在 APP 内执行 'swqboot'。\nbanner={banner!r}\npart={part!r}"
    ),

    "sess.signing_key": "签名私钥: {path}   （公钥 {pk}...）",
    "sess.no_key": "未提供签名私钥：将不发送 SIGN 帧。已烧录公钥的设备会拒绝本次升级。",
    "sess.image_secver": "镜像安全版本 = {ver} (0x{ver:X})",
    "sess.image_no_secver": "镜像无 .quilla_secver 段 - KEY 版 QBOOT 将以 VER(0x09) 拒绝。",
    "sess.image_too_big": "镜像 {size} B，超出可编程上限 {max} B（APP 区）。",
    "sess.err_key_needed": (
        "设备已烧录公钥，END 仅确认接收、未提交：本次升级必须提供 --key 签名私钥。"
        "设备当前停留在升级状态（标志 QIAP），补齐私钥后可直接重跑。"),

    "sess.err_enter_status": "ENTER 返回状态={status}",
    "sess.ack_timeout": "等待 ACK 0x{cmd:02X} 超时（第 {attempt}/{retries} 次）",
    "sess.nak_retransmit": "NAK(0x{cmd:02X}) reason=0x{reason:02X} {txt} - 重传中",
    "sess.nak_hard": "NAK(0x{cmd:02X}) reason=0x{reason:02X} {txt}",
    "sess.unexpected_resp": "收到非预期响应 0x{cmd:02X}（期望 ACK 0x{ack:02X}）",

    "sess.enter_sent": "ENTER (app_start=0x{start:08X})",
    "sess.enter_payload": "ENTER 载荷: app_start=0x{start:08X}",  # legacy alias
    "sess.enter_status": "ENTER 返回状态={status}",
    "sess.data_addr_mismatch": (
        "DATA 块 {i} 回显地址错误（期望 0x{exp:08X}，收到 0x{got:08X}）；"
        "会话已失步，请复位板卡后重新运行（建议降低波特率）。"
    ),
    "sess.end_sent": "END (total_len={length} total_crc=0x{crc:04X})",
    "sess.end_status": "END 返回状态={status}",
    "sess.end_accepted": "END 已接受（若设备持有公钥，提交仍待定）。",
    "sess.end_committed": "设备已报告提交完成（重启前的完成公告），SIGN 环节不再适用。",
    "sess.sign_skipped_committed": "提交已于 END 完成，跳过 SIGN 帧。",
    "sess.sign_skipped_gone": "端口在提交复位时掉线，不发送 SIGN 帧；将以复位证据判定完成（弱证据）。",

    "sess.sign_sent": "已发送 SIGN 帧（64 字节签名）；设备侧验签期间串口无输出，请勿断电或复位。",
    "sess.sign_no_ack_reset": "复位前未收到 SIGN ACK 或提交公告；依据设备复位判定完成（弱证据，建议复核板卡）。",
    "sess.sign_no_ack_alive": "在 {timeout:.0f} 秒内未收到 SIGN ACK、提交公告或启动戳；无法确认提交。",
    "sess.sign_accepted": "SIGN 已通过设备验签。",
    "sess.sign_nak": "SIGN 被拒绝: NAK(0x{cmd:02X}) reason=0x{reason:02X} {txt}",
    "sess.sign_unexpected": "SIGN: 收到非预期响应 0x{cmd:02X}",

    "sess.wait_stamp_tick": "等待启动戳 ... {elapsed:.0f} 秒 / {timeout:.0f} 秒",
    "sess.stamp_found": "新 APP 已运行: {stamp}",
    "sess.expect_stamp": "待校验启动戳（取自镜像）: {stamp}",
    "sess.no_expect_stamp": (
        "镜像中未找到 '[QAPP] ...' 字面量；将接受任意启动戳，"
        "无法据此区分新旧固件。"
    ),
    "sess.stamp_mismatch": "启动戳与镜像不符（收到 '{stamp}'，期望 '{expected}'）；继续等待。",
    "sess.port_dropped_stamp": "设备复位时端口掉线；待其重新枚举后再查找启动戳。",
    "sess.ack_complete": (
        "烧录完成（重启前确认，依据 {ack}）：flag=APP1 与 manifest 已提交，"
        "设备正在重启进入 APP；无需等待启动戳。"
    ),
    "sess.completion_weak": (
        "完成结论仅依据设备复位（端口掉线），未收到完成码；拔线与复位表现相同，"
        "请复核板卡运行状态。"
    ),
    "sess.completion_no_stamp": "{ack}（无需等待新 APP 启动横幅）",
    "sess.err_no_commit_ack": (
        "未收到提交后的完成 ACK、提交公告或启动戳，也没有观察到设备复位，无法确认烧录完成。"
        "请检查 QIAP 的 END / SIGN 阶段是否返回 NAK，或设备是否仍停在 QBOOT。"
    ),

    "sess.upgrade_finished": (
        "升级完成：写入 {size} 字节用时 {write_elapsed:.1f} 秒（{speed:.1f} KiB/s），"
        "总耗时 {elapsed:.1f} 秒（含探测与签名）。"
    ),
    "sess.phase_detect": "探测与进入升级模式完成，耗时 {elapsed:.1f} 秒。",
    "sess.phase_write": (
        "数据传输完成：{size} 字节 / {elapsed:.1f} 秒（{speed:.1f} KiB/s）。"
    ),
    "sess.reopen_wait": "端口 {port} 在复位期间掉线，等待其重新枚举（最多 {timeout:.0f} 秒）...",
    "sess.reopen_back": "端口 {port} 在 {elapsed:.1f} 秒后恢复",
    "sess.reopen_fail": "端口 {port} 在 {timeout:.0f} 秒内未恢复",
    "sess.port_not_configurable": "端口 {port} 暂不可配置（{kind}），{delay:.2f} 秒后重试",
    "sess.write_failed": "写入失败: {err}",
    "sess.write_broke": "串口在写入中途断开（{port}）。板卡可能已复位或连线松动。\n请重新连接，待 QBOOT 启动后重新执行升级。",
    "sess.cancel_requested": "已请求取消，等待当前帧结束（最多一帧超时）。",

    "sess.err_data_mismatch": "DATA 块 {i} 回显地址不匹配（期望 0x{exp:08X}，收到 0x{got:08X}）；升级会话已失步，请复位板卡后重新运行。",
    "sess.err_end_status": "END 返回状态={status}",
    "sess.err_sign_status": "SIGN 返回状态={status}",
    "sess.err_port_gone_qiap": "串口 {port} 已离线，无法发送 qiap。请重新连接后重试。",
    "sess.err_swqboot_fail": (
        "swqboot 未能将板卡切到 QBOOT shell：两次之后 part 仍回 'app1'。\n"
        "  1. 在串口终端手动输入 swqboot，确认板卡是否复位\n"
        "  2. 或按下板卡复位键或重新上电，然后重新执行升级\n"
        "（QBOOT 启动后 part 应返回 qboot，而非 app1）"
    ),
    "sess.err_sign_rejected": "SIGN 被拒绝: NAK(0x{cmd:02X}) reason=0x{reason:02X} {txt}",
    "sess.err_stamp_timeout": (
        "在 {timeout:.0f} 秒内未收到 '[QAPP] ...' 启动戳。该检查不是完成判据："
        "完成由 QBOOT 的提交 ACK 判定。若需复核，请重新探测板卡。"
    ),
    "sess.err_cannot_enter": (
        "无法进入升级模式。请将板卡置于 QBOOT shell（手动发送 'qiap'，或复位板卡），"
        "或先在 APP 内执行 'swqboot'。\nbanner={banner!r}\npart={part!r}"
    ),
    "sess.err_image_above_ceiling": "镜像 {size} B，超出可编程上限 {max} B（APP 区）。",

    # ===================== port open error (describe_open_error) =====================
    "sess.port.busy": (
        "无法打开 {port}：串口正被其他程序占用。\n\n"
        "按顺序处理：\n"
        "  1. 关闭串口助手、PuTTY 或仍在运行的旧版升级脚本\n"
        "  2. 若已开启 Keil，执行 Debug -> Stop 后重试\n"
        "  3. 若仍失败，注销或重启系统一次（句柄可能被残留进程占用）\n\n"
        "原始错误: {detail}"
    ),
    "sess.port.not_ready": (
        "无法打开 {port}：系统能识别端口，但配置时失败。\n"
        "（Windows ERROR_GEN_FAILURE / 31）\n\n"
        "WCH-Link、J-Link 等调试探针的串口与调试口共用\n"
        "一路 USB。Keil 一旦进入调试会话，COM 口在设备\n"
        "列表中依然存在、状态也显示正常，但串口参数会被拒绝。\n\n"
        "建议按以下顺序处理：\n"
        "  1. 在 Keil 中执行 Debug -> Stop，或直接退出 Keil，然后重新执行升级\n"
        "  2. 拔下 WCH-Link，等待 3 秒后重新插入（更换 USB 端口可提高成功率）\n"
        "  3. 在设备管理器确认 {port} 无黄色感叹号，必要时禁用再启用该设备\n\n"
        "注意：设备管理器中“状态正常”并不代表串口可用。\n\n"
        "原始错误: {detail}"
    ),
    "sess.port.not_found": (
        "无法打开 {port}：该端口不存在。\n\n"
        "  1. 板卡或 USB 转串口线可能已拔出，请重新连接\n"
        "  2. 端口号可能已变更，点击“刷新”重新枚举后再选择\n\n"
        "原始错误: {detail}"
    ),
    "sess.port.other": "无法打开 {port}: {detail}",

    # ===================== CLI phrases =====================
    "cli.desc": "Quilla QBOOT 串口升级（UART）。",
    "cli.port_help": "串口，例如 COM7 或 /dev/ttyUSB0",
    "cli.bin_help": "QAPP 固件 .bin",
    "cli.key_help": "Ed25519 私钥（private.hex，32 字节种子）；省略则跳过 SIGN 帧",
    "cli.quiet_help": "仅输出警告与错误",
    "cli.probe_help": "仅打印板卡状态，不烧录",
    "cli.list_ports_help": "列出串口并退出",
    "cli.self_test_help": "离线自检（无需串口）",
    "cli.need_both": "PORT 与 BINFILE 均为必填（或使用 --self-test / --list-ports）。",
    "cli.probe_needs_port": "--probe 需要指定端口。",
    "cli.cancelled": "已取消：板卡保留 QIAP 标志，重新运行可继续。",
    "cli.interrupted": "已被用户中断（Ctrl+C）。",
    "cli.success": "成功: {result}",
    "cli.fw_summary": "固件: {summary}",
    "cli.warn_no_secver": "无 .quilla_secver 段 - KEY 版将拒绝该镜像。",
    "cli.warn_no_key": "未指定 --key：不发送 SIGN 帧，已烧录公钥的设备将拒绝本次升级。",
    "cli.reading_banner": "读取设备输出（最长 4 秒）...",
    "cli.how_to_read": "结果解读：",
    "cli.hint_qboot": "  part 含 'qboot'  -> QBOOT shell，'qiap' 可直接升级",
    "cli.hint_app1": "  part 含 'app1'   -> APP 运行中，工具会先执行 swqboot",
    "cli.hint_idle": "  part 为空且无回显 -> 升级空闲态（等待 ENTER）或无连接",
    "cli.hint_pinfo": "  pinfo 显示 [PART]    -> 设备报告的 APP 区边界",
    "cli.baud_help": "波特率（默认 115200）",
    "cli.audit_help": "检查翻译表是否有缺漏",
    "cli.lang_help": "输出语言（默认沿用界面设置）",

    # ===================== EN strings =====================    "gui.title_en": "Quilla Updater - QBOOT serial upgrade",

    # Language-picker entries stay autonyms in both languages.
    "gui.lang_pick_auto_en": "Auto",
    "gui.lang_pick_zh_en": "中文",
    "gui.lang_pick_english_en": "English",

    "gui.serial_en": " Serial port ",
    "gui.port_en": "Port",
    "gui.refresh_en": "Refresh",
    "gui.baud_en": "Baud rate",

    "gui.firmware_en": " Firmware ",
    "gui.qapp_bin_en": "QAPP .bin",
    "gui.browse_en": "Browse...",

    "gui.signing_en": " Signing (optional) ",
    "gui.send_sign_en": "Send SIGN frame",
    "gui.private_key_en": "Private key",

    "gui.actions_en": " Actions ",
    "gui.start_en": "Start upgrade",
    "gui.cancel_en": "Cancel",
    "gui.probe_en": "Probe board",
    "gui.clear_log_en": "Clear log",

    "gui.log_en": " Log ",

    "gui.fw_upgrade_en": "  Firmware upgrade  ",
    "gui.key_tool_en": "  Key tool  ",

    "gui.lang_en": "Language",

    "gui.gen_keys_en": " Generate key pair ",
    "gui.output_dir_en": "Output directory",
    "gui.select_en": "Select...",
    "gui.gen_keys_btn_en": "Generate keys",
    "gui.gen_keys_hint_en": "Writes private.hex (32-byte seed) and public.hex.",

    "gui.derive_title_en": " Derive public key from private ",
    "gui.priv_file_en": "Private key file",
    "gui.derive_btn_en": "Derive public key",
    "gui.derive_hint_en": "Verifies that the public key provisioned in the device and the local private key form a matching pair. A mismatched pair is the primary cause of a rejection at the SIGN stage.",

    "gui.result_en": " Result ",
    "gui.copy_pub_en": "Copy public key",
    "gui.copy_macro_en": "Copy build macro",
    "gui.clear_en": "Clear",

    "gui.key_warn_en": (
        "Keep the private key on the signing station only. Do not commit it to a "
        "repository, bake it into firmware, or send it to anyone.\n"
        "A leaked private key lets anyone sign an image the device will accept, "
        "which defeats secure boot entirely."
    ),

    "gui.ready_1_en": "Ready. Select a port and firmware, then click \"Start upgrade\".",
    "gui.ready_2_en": "Upgrading while the application is running is supported; the tool switches to upgrade mode automatically.",

    "gui.no_ports_en": "No serial port detected. Connect a USB-to-serial cable, then click \"Refresh\".",

    "gui.dlg_no_port_title_en": "No port selected",
    "gui.dlg_no_port_en": "Select a serial port first.",
    "gui.dlg_no_fw_title_en": "No firmware",
    "gui.dlg_no_fw_en": "Select a .bin firmware first.",
    "gui.dlg_no_key_title_en": "No private key",
    "gui.dlg_no_key_en": (
        "SIGN is enabled but no private key is selected.\n\n"
        "If the device has a public key flashed, this upgrade will be rejected at "
        "the SIGN stage.\n"
        "Continue anyway?"
    ),
    "gui.dlg_invalid_fw_title_en": "Invalid firmware",
    "gui.dlg_invalid_key_title_en": "Invalid private key",
    "gui.dlg_success_title_en": "Upgrade succeeded",
    "gui.dlg_success_en": "Flashing complete:\n\n{stamp}",
    "gui.dlg_cancelled_en": "Cancelled. The board keeps the QIAP flag; re-run to continue the upgrade.",

    "gui.port_err_busy_en": "Port busy",
    "gui.port_err_not_ready_en": "Port not configurable (possibly held by a debug session)",
    "gui.port_err_not_found_en": "Port does not exist",
    "gui.port_err_other_en": "Cannot open port",
    "gui.dlg_fail_title_en": "Upgrade failed",
    "gui.probe_done_en": (
        "Probe done. part containing 'qboot' -> QBOOT shell; 'app1' -> APP running; "
        "empty with no echo -> upgrade-idle."
    ),

    "gui.dlg_no_dir_title_en": "No directory",
    "gui.dlg_no_dir_en": "Pick an output directory first.",
    "gui.dlg_key_exists_title_en": "Private key exists",
    "gui.dlg_key_exists_en": (
        "{path} already exists.\n\n"
        "Overwriting makes the original private key unrecoverable. If QBOOT was "
        "built with its matching public key, that device can no longer be upgraded "
        "unless QBOOT is re-flashed.\n\n"
        "Overwrite it?"
    ),
    "gui.dlg_gen_fail_title_en": "Generation failed",
    "gui.dlg_no_clip_title_en": "Nothing to copy",
    "gui.dlg_no_clip_en": "Generate or derive a public key first.",

    "gui.status_ready_en": "Ready",
    "gui.status_connecting_en": "Connecting ...",
    "gui.status_success_en": "Succeeded",
    "gui.status_cancelled_en": "Cancelled",
    "gui.status_port_err_en": "Cannot open port",
    "gui.status_failed_en": "Failed",
    "gui.status_probe_done_en": "Probe done",

    "gui.fw_none_en": "No firmware selected",
    "gui.fw_info_secver_none_en": (
        "{name}   {size} KiB   SHA-256 {sha}...   no .quilla_secver section (rejected by a QBOOT with a public key)"
    ),
    "gui.fw_info_secver_en": (
        "{name}   {size} KiB   SHA-256 {sha}...   security version {ver} (0x{ver:X})"
    ),
    "gui.fw_warn_no_secver_en": "The firmware has no security-version section; a device with a public key flashed will reject it with VER(0x09).",
    "gui.key_info_en": "Public key {pk}...  (must match the key provisioned in QBOOT)",
    "gui.key_loaded_en": "private key: {name}",
    "gui.done_msg_en": "Upgrade complete: {result}",
    "gui.detail_speed_en": "{speed} KiB/s",
    "gui.detail_done_en": "{total:.1f} s (write {write:.1f} s)  {speed:.1f} KiB/s",
    "gui.detail_eta_en": "ETA {eta:.0f} s",
    "gui.detail_progress_en": "{done} / {total} B",
    "gui.writing_pct_en": "Writing {pct:.0f}%",
    "gui.sign_detail_en": "Device-side Ed25519 verify (seconds to tens of seconds)",
    "gui.verify_detail_en": "Post-confirmation: inspecting a boot stamp that arrived with the completion code (non-fatal)",

    "phase.detect_en": "Detecting board state ...",
    "phase.enter_en": "Sending ENTER ...",
    "phase.write_en": "Writing firmware",
    "phase.end_en": "Committing length & CRC ...",
    "phase.sign_en": "Device verifying (do not power off)",
    "phase.verify_en": "Post-confirmation: brief peek for a boot stamp (non-fatal) ...",
    "phase.done_en": "Done",

    "kt.generated_en": "Key pair generated\n",
    "kt.seed_line_en": "  {path}   32-byte seed, KEEP SECRET\n",
    "kt.pub_line_en": "  {path}   flash into QBOOT\n\n",
    "kt.pub_hex_en": "public key (hex):\n",
    "kt.macro_head_en": "QBOOT build macro:\n",
    "kt.derived_en": "Public key derived\n\n",
    "kt.copied_en": "Copied to clipboard: {what}\n",

    "sess.opened_en": "Opened {port} @ {baud} 8N1",
    "sess.reading_banner_en": "Reading device output (up to 4 s) ...",
    "sess.already_upgrade_en": "Board already in upgrade mode (QIAP flag present); sending ENTER directly.",
    "sess.not_qboot_try_enter_en": "No QBOOT shell detected; trying a direct ENTER first (covers the upgrade-idle state).",
    "sess.app_shell_reset_en": "APP shell detected (part answered app1); resetting into QBOOT via swqboot.",
    "sess.direct_enter_failed_en": "Direct ENTER failed: {err}",
    "sess.swqboot_attempt_en": "Sending 'swqboot' (attempt {n}) to reset into QBOOT ...",
    "sess.port_dropped_wait_en": "Port {port} dropped on reset, waiting for it to re-enumerate (up to {timeout:.0f} s) ...",
    "sess.post_reset_output_en": "post-reset output: {data!r}",
    "sess.post_swqboot_part_en": "post-swqboot part -> {data!r}",
    "sess.in_qboot_shell_en": "Board is in the QBOOT shell.",
    "sess.still_app_en": "Still in the APP shell after swqboot (attempt {n}); the reset did not take effect.",
    "sess.no_echo_assume_en": "No echo after swqboot; assuming the board is already in the upgrade-idle state.",
    "sess.board_qboot_en": "Board is in the QBOOT shell.",
    "sess.swqboot_fail_en": (
        "swqboot did not move the board to the QBOOT shell: after two attempts "
        "part still replies 'app1'.\n"
        "  1. Enter swqboot manually in a serial terminal and confirm the board resets\n"
        "  2. Or press the board reset button or power-cycle, then start the upgrade again\n"
        "(once QBOOT has booted, part should return qboot, not app1)"
    ),
    "sess.entered_upgrade_en": "Switched to upgrade mode (qiap attempt {n})",
    "sess.enter_accepted_en": "ENTER accepted; QIAP flag set, so a power loss from this point is recoverable.",
    "sess.partition_ok_en": "Partition (from device): APP_START=0x{start:08X} APP_END=0x{end:08X} ({size} B)",
    "sess.partition_fail_en": "pinfo returned no partition layout (possibly older firmware); the host does not enforce a ceiling, ADDR NAK(0x01) does.",
    "sess.qiap_attempt_en": "qiap attempt {n} did not enter upgrade mode",
    "sess.port_gone_qiap_en": "Port {port} is offline; cannot send qiap. Reconnect and retry.",
    "sess.qiap_write_fail_en": "Port dropped while sending qiap ({port})",
    "sess.cannot_enter_en": (
        "Could not enter upgrade mode. Put the board in the QBOOT shell (send "
        "'qiap' manually, or reset the board), or run 'swqboot' from the APP first."
        "\nbanner={banner!r}\npart={part!r}"
    ),

    "sess.signing_key_en": "Signing key: {path}  (public key {pk}...)",
    "sess.no_key_en": "No signing key: no SIGN frame will be sent. A device with a public key flashed will reject this upgrade.",
    "sess.image_secver_en": "Image security version = {ver} (0x{ver:X})",
    "sess.image_no_secver_en": "Image has no .quilla_secver region - a KEY build will reject it with VER(0x09).",
    "sess.image_too_big_en": "Image is {size} B, above the programmable ceiling of {max} B (APP region).",
    "sess.err_key_needed_en": (
        "The device holds a public key, so END acknowledged without committing: "
        "this upgrade needs a signing key (--key). The device is parked in the "
        "upgrade state (flag QIAP); rerun with the key, no reset required."),

    "sess.err_enter_status_en": "ENTER returned status={status}",
    "sess.ack_timeout_en": "Timed out waiting for ACK 0x{cmd:02X} (attempt {attempt}/{retries})",
    "sess.nak_retransmit_en": "NAK(0x{cmd:02X}) reason=0x{reason:02X} {txt} - retransmitting",
    "sess.nak_hard_en": "NAK(0x{cmd:02X}) reason=0x{reason:02X} {txt}",
    "sess.unexpected_resp_en": "Unexpected response 0x{cmd:02X} (expected ACK 0x{ack:02X})",

    "sess.enter_sent_en": "ENTER (app_start=0x{start:08X})",
    "sess.enter_status_en": "ENTER returned status={status}",
    "sess.data_addr_mismatch_en": (
        "DATA chunk {i} echoed the wrong address (expected 0x{exp:08X}, got 0x{got:08X}); "
        "the session has lost sync, reset the board and re-run (a lower baud rate is more reliable)."
    ),
    "sess.end_sent_en": "END (total_len={length} total_crc=0x{crc:04X})",
    "sess.end_status_en": "END returned status={status}",
    "sess.end_accepted_en": "END accepted (commit still pending if the device holds a public key).",
    "sess.end_committed_en": "The device reported a completed commit (pre-reset announcement); the SIGN step no longer applies.",
    "sess.sign_skipped_committed_en": "Commit already happened at END - SIGN frame skipped.",
    "sess.sign_skipped_gone_en": "Port dropped during the commit reset, so no SIGN frame is sent; the verdict will rest on reset evidence (weak).",

    "sess.sign_sent_en": "Sent SIGN frame (64 B signature); the link stays silent during device-side verification - do not power off or reset.",
    "sess.sign_no_ack_reset_en": "No SIGN ACK or commit announcement before the reset; the verdict rests on the reset (weak evidence - re-check the board).",
    "sess.sign_no_ack_alive_en": "No SIGN ACK, commit announcement or boot stamp within {timeout:.0f} s; the commit cannot be confirmed.",
    "sess.sign_accepted_en": "SIGN verified by the device.",
    "sess.sign_nak_en": "SIGN rejected: NAK(0x{cmd:02X}) reason=0x{reason:02X} {txt}",
    "sess.sign_unexpected_en": "SIGN: unexpected response 0x{cmd:02X}",

    "sess.wait_stamp_tick_en": "Waiting for the boot stamp ... {elapsed:.0f} s / {timeout:.0f} s",
    "sess.stamp_found_en": "New APP is running: {stamp}",
    "sess.expect_stamp_en": "Expected boot stamp (from the image): {stamp}",
    "sess.no_expect_stamp_en": (
        "No '[QAPP] ...' literal in the image; any boot stamp will be accepted, "
        "so old and new firmware cannot be told apart."
    ),
    "sess.stamp_mismatch_en": "Boot stamp does not match the image (got '{stamp}', expected '{expected}'); still waiting.",
    "sess.port_dropped_stamp_en": "Port dropped when the device reset; waiting for it to re-enumerate before looking for the boot stamp.",
    "sess.ack_complete_en": (
        "Flashing complete (confirmed before the reset, evidence: {ack}): "
        "flag=APP1 and the manifest are committed; the device is rebooting "
        "into the APP. No boot-stamp wait is required."
    ),
    "sess.completion_weak_en": (
        "The verdict rests only on a device reset (port lost): no completion "
        "code was received, and a cable pull looks the same. Re-check that "
        "the new APP is running."
    ),
    "sess.completion_no_stamp_en": "{ack} (no wait for the new APP boot stamp)",
    "sess.err_no_commit_ack_en": (
        "No post-commit completion ACK, commit announcement or boot stamp, and "
        "no device reset observed, so the flash cannot be confirmed. Check for "
        "a NAK in the QIAP END / SIGN phase, or whether the board is still in "
        "QBOOT."
    ),

    "sess.upgrade_finished_en": (
        "Upgrade finished: {size} bytes written in {write_elapsed:.1f} s "
        "({speed:.1f} KiB/s); {elapsed:.1f} s total including detection and signing."
    ),
    "sess.phase_detect_en": "Detection and upgrade-mode entry took {elapsed:.1f} s.",
    "sess.phase_write_en": (
        "Data transfer done: {size} bytes in {elapsed:.1f} s ({speed:.1f} KiB/s)."
    ),
    "sess.reopen_wait_en": "Port {port} went away during the reset, waiting for it to re-enumerate (up to {timeout:.0f} s) ...",
    "sess.reopen_back_en": "Port {port} back after {elapsed:.1f} s",
    "sess.reopen_fail_en": "Port {port} did not come back within {timeout:.0f} s",
    "sess.port_not_configurable_en": "Port {port} not configurable yet ({kind}), retrying in {delay:.2f} s",
    "sess.write_failed_en": "Write failed: {err}",
    "sess.write_broke_en": "Serial port broke mid-write ({port}). The board may have reset or the cable may be loose.\nReconnect, wait for QBOOT to boot, then start the upgrade again.",
    "sess.cancel_requested_en": "Cancel requested; waiting for the current frame to finish (at most one frame timeout).",

    "sess.err_data_mismatch_en": "DATA chunk {i} echoed a mismatched address (expected 0x{exp:08X}, got 0x{got:08X}); the upgrade session has lost sync, reset the board and re-run.",
    "sess.err_end_status_en": "END returned status={status}",
    "sess.err_sign_status_en": "SIGN returned status={status}",
    "sess.err_port_gone_qiap_en": "Port {port} is offline; cannot send qiap. Reconnect and retry.",
    "sess.err_swqboot_fail_en": (
        "swqboot did not move the board to the QBOOT shell: after two attempts "
        "part still replies 'app1'.\n"
        "  1. Enter swqboot manually in a serial terminal and confirm the board resets\n"
        "  2. Or press the board reset button or power-cycle, then start the upgrade again\n"
        "(once QBOOT has booted, part should return qboot, not app1)"
    ),
    "sess.err_sign_rejected_en": "SIGN rejected: NAK(0x{cmd:02X}) reason=0x{reason:02X} {txt}",
    "sess.err_stamp_timeout_en": (
        "No '[QAPP] ...' boot stamp within {timeout:.0f} s. This check is not "
        "the completion criterion: QBOOT's commit ACK decides that. Re-probe "
        "the board if you want to confirm which image is running."
    ),
    "sess.err_cannot_enter_en": (
        "Could not enter upgrade mode. Put the board in the QBOOT shell (send "
        "'qiap' manually, or reset the board), or run 'swqboot' from the APP first."
        "\nbanner={banner!r}\npart={part!r}"
    ),
    "sess.err_image_above_ceiling_en": "Image is {size} B, above the programmable ceiling of {max} B (APP region).",

    "sess.port.busy_en": (
        "Cannot open {port}: the port is held by another program.\n\n"
        "  1. Close the serial assistant, PuTTY, or a stale upgrade script\n"
        "  2. If Keil is open, run Debug -> Stop, then retry\n"
        "  3. If it still fails, sign out or reboot (a leftover process may hold the handle)\n\n"
        "Original error: {detail}"
    ),
    "sess.port.not_ready_en": (
        "Cannot open {port}: the system sees the port but fails to configure it.\n"
        "(Windows ERROR_GEN_FAILURE / 31)\n\n"
        "On a composite probe (WCH-Link, J-Link) the serial port and the debug "
        "port share one USB link. Once Keil enters a debug session, the COM port "
        "is still listed and shows \"working\", but SetCommState is refused.\n\n"
        "  1. In Keil, run Debug -> Stop or quit Keil, then start the upgrade again\n"
        "  2. Unplug the WCH-Link, wait 3 s, plug it back in (a different USB port improves the odds)\n"
        "  3. In Device Manager confirm {port} has no yellow exclamation; disable/re-enable it if needed\n\n"
        "Note: \"working\" in Device Manager does NOT mean the port is usable.\n\n"
        "Original error: {detail}"
    ),
    "sess.port.not_found_en": (
        "Cannot open {port}: this port does not exist.\n\n"
        "  1. The board or USB-to-serial cable may be disconnected; reconnect it\n"
        "  2. The port number may have changed; click \"Refresh\" and re-select\n\n"
        "Original error: {detail}"
    ),
    "sess.port.other_en": "Cannot open {port}: {detail}",

    # ---------------------------------------------------- CLI (English)
    "cli.desc_en": "Quilla QBOOT serial upgrade (UART).",
    "cli.port_help_en": "Serial port, e.g. COM7 or /dev/ttyUSB0",
    "cli.bin_help_en": "QAPP firmware .bin",
    "cli.key_help_en": (
        "Ed25519 private key (private.hex, 32-byte seed); omit to skip the SIGN frame"
    ),
    "cli.quiet_help_en": "Print warnings and errors only",
    "cli.probe_help_en": "Print the board state without flashing",
    "cli.list_ports_help_en": "List serial ports and exit",
    "cli.self_test_help_en": "Offline self-test (no serial port required)",
    "cli.need_both_en": (
        "Both PORT and BINFILE are required (or use --self-test / --list-ports)."
    ),
    "cli.probe_needs_port_en": "--probe requires a port.",
    "cli.cancelled_en": (
        "Cancelled: the board keeps the QIAP flag, re-run to continue the upgrade."
    ),
    "cli.interrupted_en": "Interrupted by the user (Ctrl+C).",
    "cli.success_en": "Success: {result}",
    "cli.fw_summary_en": "Firmware: {summary}",
    "cli.warn_no_secver_en": (
        "No .quilla_secver section - a KEY build will reject this image."
    ),
    "cli.warn_no_key_en": (
        "No --key given: the SIGN frame is not sent, so a device with a public key "
        "flashed will reject this upgrade."
    ),
    "cli.reading_banner_en": "Reading device output (up to 4 s) ...",
    "cli.how_to_read_en": "How to read the result:",
    "cli.hint_qboot_en": (
        "  part contains 'qboot' -> QBOOT shell, 'qiap' can upgrade directly"
    ),
    "cli.hint_app1_en": (
        "  part contains 'app1'  -> the APP is running, the tool runs swqboot first"
    ),
    "cli.hint_idle_en": (
        "  part empty and no echo -> upgrade-idle (waiting for ENTER) or not connected"
    ),
    "cli.hint_pinfo_en": "  pinfo shows [PART]    -> APP region bounds as reported by the device",
    "cli.baud_help_en": "baud rate (default 115200)",
    "cli.audit_help_en": "check the translation table for gaps",
    "cli.lang_help_en": "output language (default: the persisted UI setting)",

    "sess.enter_payload_en": "ENTER payload: app_start=0x{start:08X}",
}


# ------------------------------------------------------------------ self-check
def audit():
    """Return a list of problems in the string table.

    Two failure modes matter and neither is caught by Python:

    1. A Chinese key has no ``_en`` counterpart (or vice versa) - the UI then
       silently shows the other language.
    2. A Chinese key itself ends in ``_en`` (e.g. ``gui.lang_pick_en``). The
       flat table has no namespace, so that key and the English form of
       ``gui.lang_pick`` collide. This happened once already; the audit exists
       so it cannot happen again silently.

    Run ``python -m quilla_updater.cli --audit-i18n`` to check.
    """
    problems = []
    zh = {k for k in _STRINGS if not k.endswith("_en")}
    en = {k[:-3] for k in _STRINGS if k.endswith("_en")}

    for key in sorted(zh):
        if key + "_en" not in _STRINGS:
            problems.append("missing EN translation: %s" % key)
    for key in sorted(en):
        if key not in _STRINGS:
            problems.append("missing ZH translation: %s" % key)

    # Collision: key ends in "_en" AND some other key needs that exact slot.
    for key in sorted(zh):
        if key.endswith("_en"):
            owner = key[:-3]
            if owner in zh:
                problems.append(
                    "key collision: %r is both a ZH key and the EN form of %r"
                    % (key, owner))
    return problems


def _audit_or_warn():
    problems = audit()
    if problems:
        import sys
        for p in problems:
            sys.stderr.write("i18n: %s\n" % p)


_audit_or_warn()
