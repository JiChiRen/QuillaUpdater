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
Tkinter front end for the QBOOT serial upgrade.

Design notes for whoever picks this up next:

  * The UI never touches the serial port. All protocol work happens in
    session.Session, driven by a worker thread; the thread reports back through
    a queue that the Tk main loop drains with after(). Tk is not thread-safe,
    so no callback may touch a widget directly.
  * Progress has three shapes and the bar switches between them: indeterminate
    while detecting / erasing (no byte count exists), determinate during the
    write, and indeterminate again during SIGN - where the device spends ~21 s
    verifying and the only honest thing to show is "device is verifying".
  * Cancel is cooperative. The session polls it between frames and inside every
    read loop, so the worst case is one in-flight frame. The board is never left
    unrecoverable: once ENTER succeeds the QIAP flag is set, so a cancelled run
    just needs a re-run.
  * All user-facing text goes through i18n.t(); flipping the language re-applies
    every registered widget instead of restarting the app.
"""

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from . import ports as ports_mod
from . import ed25519
from . import config
from . import i18n
from .image import FirmwareImage, ImageError
from .session import (Session, UpgradeError, UpgradeCancelled, PortOpenError,
                      Progress, parse_app_reset_command)

BAUD_RATES = ("115200", "230400", "460800", "921600")
LOG_COLORS = {
    "info": "#333333",
    "ok": "#1D6E3A",
    "warn": "#9A5B00",
    "err": "#A32D2D",
    "debug": "#777777",
}

#: Language display names always read in their own tongue (UI convention), so
#: the mapping is (code, i18n key) and the label is resolved at render time.
LANG_CHOICES = (("auto", "gui.lang_pick_auto"),
                ("zh", "gui.lang_pick_zh"),
                ("en", "gui.lang_pick_english"))


def _phase_text(phase):
    return i18n.t("phase." + phase)


class UpgradePage(ttk.Frame):
    """The main page: pick a port, pick a .bin, upgrade."""

    def __init__(self, master, app):
        ttk.Frame.__init__(self, master, padding=12)
        self.master = master
        self.app = app

        self._ports = []
        self._queue = queue.Queue()
        self._worker = None
        self._cancel_evt = threading.Event()
        self._image = None
        self._fw_meta = None          # (name, size, secver, sha) for re-render
        self._key_pk = None           # public key bytes for re-render
        self._started_at = 0.0
        self._last_done = 0
        self._last_bytes = 0
        self._last_time = 0.0

        self.var_port = tk.StringVar()
        self.var_baud = tk.StringVar(
            value=app.cfg["baud"] if app.cfg["baud"] in BAUD_RATES else BAUD_RATES[0])
        self.var_fw = tk.StringVar(value=app.cfg["fw_path"])
        self.var_key = tk.StringVar(value=app.cfg["key_path"])
        self.var_use_key = tk.BooleanVar(value=app.cfg["use_key"])
        self.var_app_reset = tk.StringVar(value=app.cfg["app_reset"])
        self.var_app_reset_hex = tk.StringVar(value=app.cfg["app_reset_hex"])
        self.var_use_hex_reset = tk.BooleanVar(value=app.cfg["use_hex_reset"])
        self.var_status = tk.StringVar(value=i18n.t("gui.status_ready"))
        self.var_detail = tk.StringVar(value="")
        self.var_fw_info = tk.StringVar(value=i18n.t("gui.fw_none"))
        self.var_key_info = tk.StringVar(value="")

        self._build()
        self.refresh_ports()
        # Restore the firmware image object from the saved path, if still valid.
        fw = app.cfg["fw_path"]
        if fw and os.path.isfile(fw):
            try:
                img = FirmwareImage.load(fw)
                self._image = img
                self._fw_meta = (img.name, img.size, img.secver, img.sha256.hex())
                self._render_fw_info()
            except Exception:
                self._image = None
        self.after(100, self._pump)

    # ------------------------------------------------------------------ layout
    def _tr(self, widget, attr, key, **kw):
        """Set a translatable attribute and remember it for live language switch.

        Returns the widget so it can be chained straight into a layout call:
        ``self._tr(ttk.Button(...), "text", "gui.browse").grid(...)``.
        """
        def apply():
            widget.configure(**{attr: i18n.t(key, **kw)})
        apply()
        self.app._tr_registry.append(apply)
        return widget

    def _build(self):
        row = 0

        # -- connection ------------------------------------------------------
        box = ttk.LabelFrame(self, padding=10)
        self._tr(box, "text", "gui.serial")
        box.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)
        lbl_port = ttk.Label(box)
        self._tr(lbl_port, "text", "gui.port")
        lbl_port.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.cmb_port = ttk.Combobox(box, textvariable=self.var_port,
                                     state="readonly", width=42)
        self.cmb_port.grid(row=0, column=1, sticky="ew")
        self._tr(ttk.Button(box, width=6, command=self.refresh_ports), "text",
                 "gui.refresh").grid(row=0, column=2, padx=(6, 0))
        self._tr(ttk.Label(box, text="波特率"), "text", "gui.baud").grid(
            row=0, column=3, padx=(12, 6))
        self.cmb_baud = ttk.Combobox(box, textvariable=self.var_baud,
                                     values=BAUD_RATES, state="readonly", width=9)
        self.cmb_baud.grid(row=0, column=4)
        row += 1

        # -- firmware --------------------------------------------------------
        box = ttk.LabelFrame(self, padding=10)
        self._tr(box, "text", "gui.firmware")
        box.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)
        self._tr(ttk.Label(box, text="QAPP .bin"), "text", "gui.qapp_bin").grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(box, textvariable=self.var_fw, state="readonly").grid(
            row=0, column=1, sticky="ew")
        self._tr(ttk.Button(box, width=8, command=self.pick_firmware), "text",
                 "gui.browse").grid(row=0, column=2, padx=(6, 0))
        ttk.Label(box, textvariable=self.var_fw_info, foreground="#555555").grid(
            row=1, column=1, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        # -- signing ---------------------------------------------------------
        box = ttk.LabelFrame(self, padding=10)
        self._tr(box, "text", "gui.signing")
        box.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(2, weight=1)
        self._tr(ttk.Checkbutton(box, variable=self.var_use_key,
                                 command=self._toggle_key), "text", "gui.send_sign"
                 ).grid(row=0, column=0, sticky="w")
        self._tr(ttk.Label(box, text="私钥"), "text", "gui.private_key").grid(
            row=0, column=1, sticky="w", padx=(12, 6))
        self.ent_key = ttk.Entry(box, textvariable=self.var_key, state="readonly")
        self.ent_key.grid(row=0, column=2, sticky="ew")
        self.btn_key = ttk.Button(box, width=8, command=self.pick_key)
        self._tr(self.btn_key, "text", "gui.browse")
        self.btn_key.grid(row=0, column=3, padx=(6, 0))
        ttk.Label(box, textvariable=self.var_key_info, foreground="#555555").grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(4, 0))
        row += 1

        # -- APP -> QBOOT reset command -------------------------------------
        box = ttk.LabelFrame(self, padding=10)
        self._tr(box, "text", "gui.app_reset")
        box.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)
        self._tr(ttk.Checkbutton(box, variable=self.var_use_hex_reset,
                                 command=self._toggle_hex_reset), "text",
                 "gui.app_reset_use_hex").grid(row=0, column=0, sticky="w")
        self._tr(ttk.Label(box, text="文本指令"), "text",
                 "gui.app_reset_text").grid(row=1, column=0, sticky="w",
                                           padx=(0, 6))
        self.ent_app_reset = ttk.Entry(box, textvariable=self.var_app_reset)
        self.ent_app_reset.grid(row=1, column=1, columnspan=2, sticky="ew")
        self._tr(ttk.Label(box, text="十六进制"), "text",
                 "gui.app_reset_hex").grid(row=2, column=0, sticky="w",
                                          padx=(0, 6))
        self.ent_app_reset_hex = ttk.Entry(
            box, textvariable=self.var_app_reset_hex)
        self.ent_app_reset_hex.grid(row=2, column=1, columnspan=2, sticky="ew")
        self._tr(ttk.Label(box, foreground="#555555", wraplength=520), "text",
                 "gui.app_reset_hint").grid(row=3, column=0, columnspan=3,
                                           sticky="w", pady=(4, 0))
        self._toggle_hex_reset()
        row += 1

        # -- actions ---------------------------------------------------------
        bar = ttk.Frame(self)
        bar.grid(row=row, column=0, sticky="ew", pady=(2, 8))
        self.btn_start = ttk.Button(bar, width=14, command=self.start)
        self._tr(self.btn_start, "text", "gui.start")
        self.btn_start.pack(side="left")
        self.btn_cancel = ttk.Button(bar, width=10, command=self.cancel,
                                    state="disabled")
        self._tr(self.btn_cancel, "text", "gui.cancel")
        self.btn_cancel.pack(side="left", padx=(8, 0))
        self.btn_probe = ttk.Button(bar, width=10, command=self.probe)
        self._tr(self.btn_probe, "text", "gui.probe")
        self.btn_probe.pack(side="left", padx=(8, 0))
        self.btn_clear = ttk.Button(bar, width=10, command=self.clear_log)
        self._tr(self.btn_clear, "text", "gui.clear_log")
        self.btn_clear.pack(side="right")
        row += 1

        # -- progress --------------------------------------------------------
        box = ttk.Frame(self)
        box.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(0, weight=1)
        self.pbar = ttk.Progressbar(box, mode="determinate", maximum=1000)
        self.pbar.grid(row=0, column=0, sticky="ew")
        self.lbl_status = ttk.Label(box, textvariable=self.var_status, width=34,
                                    anchor="w")
        self.lbl_status.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.lbl_detail = ttk.Label(box, textvariable=self.var_detail,
                                    foreground="#555555")
        self.lbl_detail.grid(row=1, column=1, sticky="e", pady=(4, 0))
        row += 1

        # -- log -------------------------------------------------------------
        box = ttk.LabelFrame(self, padding=6)
        self._tr(box, "text", "gui.log")
        box.grid(row=row, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.txt = tk.Text(box, height=14, wrap="none", state="disabled",
                           font=("Consolas", 10), background="#FBFBF9",
                           relief="flat", borderwidth=0)
        ys = ttk.Scrollbar(box, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=ys.set)
        self.txt.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        for tag, color in LOG_COLORS.items():
            self.txt.tag_configure(tag, foreground=color)
        row += 1

        self.columnconfigure(0, weight=1)
        self.rowconfigure(row - 1, weight=1)

        self.log("info", i18n.t("gui.ready_1"))
        self.log("info", i18n.t("gui.ready_2"))

    # ------------------------------------------------------------------ helpers
    def log(self, level, text):
        stamp = time.strftime("%H:%M:%S")
        self.txt.configure(state="normal")
        self.txt.insert("end", "[%s] %s\n" % (stamp, text), level)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    def _toggle_key(self):
        state = "readonly" if self.var_use_key.get() else "disabled"
        self.ent_key.configure(state=state)
        self.btn_key.configure(state="normal" if self.var_use_key.get() else "disabled")

    def _toggle_hex_reset(self):
        use = self.var_use_hex_reset.get()
        self.ent_app_reset_hex.configure(state="normal" if use else "disabled")
        self.ent_app_reset.configure(state="disabled" if use else "normal")

    def refresh_ports(self):
        try:
            self._ports = ports_mod.list_ports()
        except RuntimeError as e:
            self.log("err", str(e))
            return
        labels = [p.label() for p in self._ports]
        self.cmb_port.configure(values=labels)
        if labels:
            cur = self.app.cfg["port"]
            if cur in labels:
                self.var_port.set(cur)
            elif self.var_port.get() not in labels:
                self.var_port.set(labels[0])
        else:
            self.var_port.set("")
            self.log("warn", i18n.t("gui.no_ports"))

    def _selected_port(self):
        """Resolve the chosen entry to a device name.

        Index first: two identical-looking dongles (same driver, same
        description) would otherwise be ambiguous by label.
        """
        try:
            idx = self.cmb_port.current()
        except Exception:
            idx = -1
        if 0 <= idx < len(self._ports):
            return self._ports[idx].device
        label = self.var_port.get()
        if not label:
            return ""
        for p in self._ports:
            if p.label() == label:
                return p.device
        return label.split()[0]

    def _render_fw_info(self):
        if not self._fw_meta:
            self.var_fw_info.set(i18n.t("gui.fw_none"))
            return
        name, size, secver, sha = self._fw_meta
        if secver is None:
            self.var_fw_info.set(i18n.t("gui.fw_info_secver_none",
                                        name=name, size=size / 1024.0, sha=sha[:16]))
            self.log("warn", i18n.t("gui.fw_warn_no_secver"))
        else:
            self.var_fw_info.set(i18n.t("gui.fw_info_secver", name=name,
                                        size=size / 1024.0, sha=sha[:16],
                                        ver=secver))

    def _render_key_info(self):
        if not self._key_pk:
            self.var_key_info.set("")
            return
        self.var_key_info.set(i18n.t("gui.key_info", pk=self._key_pk.hex()[:24]))

    def _render_status_idle(self):
        if self._worker is None or not self._worker.is_alive():
            self.var_status.set(i18n.t("gui.status_ready"))

    def pick_firmware(self):
        path = filedialog.askopenfilename(
            title=i18n.t("gui.qapp_bin"),
            initialdir=self.app.cfg["last_dir"] or None,
            filetypes=[("Firmware image", "*.bin"), ("All files", "*.*")])
        if not path:
            return
        try:
            img = FirmwareImage.load(path)
        except ImageError as e:
            messagebox.showerror(i18n.t("gui.dlg_invalid_fw_title"), str(e))
            return
        self._image = img
        self.var_fw.set(path)
        self._fw_meta = (img.name, img.size, img.secver, img.sha256.hex())
        self._render_fw_info()
        self.log("info", img.summary())
        config.update(fw_path=path, last_dir=os.path.dirname(path))

    def pick_key(self):
        path = filedialog.askopenfilename(
            title=i18n.t("gui.private_key"),
            initialdir=self.app.cfg["last_dir"] or None,
            filetypes=[("Key", "*.hex"), ("All files", "*.*")])
        if not path:
            return
        try:
            seed = ed25519.load_seed_hex(path)
            pk = ed25519.pubkey_from_seed(seed)
        except Exception as e:
            messagebox.showerror(i18n.t("gui.dlg_invalid_key_title"), str(e))
            return
        self.var_key.set(path)
        self._key_pk = pk
        self._render_key_info()
        self.log("info", i18n.t("gui.key_loaded", name=os.path.basename(path)))
        config.update(key_path=path, last_dir=os.path.dirname(path))

    # ------------------------------------------------------------------ worker
    def start(self):
        if self._worker is not None and self._worker.is_alive():
            return
        port = self._selected_port()
        if not port:
            messagebox.showwarning(i18n.t("gui.dlg_no_port_title"),
                                   i18n.t("gui.dlg_no_port"))
            return
        if self._image is None:
            messagebox.showwarning(i18n.t("gui.dlg_no_fw_title"),
                                   i18n.t("gui.dlg_no_fw"))
            return
        if self.var_use_key.get() and not self.var_key.get():
            if not messagebox.askyesno(
                    i18n.t("gui.dlg_no_key_title"), i18n.t("gui.dlg_no_key")):
                return

        try:
            baud = int(self.var_baud.get())
        except ValueError:
            baud = 115200

        # Resolve and validate the APP -> QBOOT reset command. The text form is
        # used unless the hex toggle is on (then hex wins, text is ignored).
        app_reset = self.var_app_reset.get()
        app_reset_hex = (self.var_app_reset_hex.get()
                         if self.var_use_hex_reset.get() else "")
        try:
            parse_app_reset_command(app_reset, app_reset_hex)
        except ValueError as e:
            messagebox.showerror(i18n.t("gui.dlg_invalid_reset_title"),
                                 i18n.t("gui.dlg_invalid_reset", msg=str(e)))
            return

        # Persist the choices the operator just made.
        config.update(fw_path=self.var_fw.get(),
                      key_path=self.var_key.get() if self.var_use_key.get() else "",
                      use_key=self.var_use_key.get(),
                      port=port, baud=self.var_baud.get(),
                      app_reset=app_reset,
                      app_reset_hex=app_reset_hex,
                      use_hex_reset=self.var_use_hex_reset.get())

        self._cancel_evt.clear()
        self._started_at = time.time()
        self._last_bytes = 0
        self._last_time = self._started_at
        self._last_done = 0
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.pbar.configure(mode="indeterminate")
        self.pbar.start(12)
        self.var_status.set(i18n.t("gui.status_connecting"))

        key = self.var_key.get() if self.var_use_key.get() else None
        image = self._image

        def work():
            sess = Session(port, baud, key_path=key,
                           on_log=lambda lvl, msg: self._queue.put(("log", lvl, msg)),
                           on_progress=lambda ph, d, t: self._queue.put(("prog", ph, d, t)),
                           cancel=self._cancel_evt.is_set,
                           reset_cmd=app_reset, reset_cmd_hex=app_reset_hex)
            try:
                result = sess.run(image)
                self._queue.put(("done", result))
            except UpgradeCancelled:
                self._queue.put(("cancelled", None))
            except PortOpenError as e:
                self._queue.put(("port_error", e.kind, str(e)))
            except UpgradeError as e:
                self._queue.put(("failed", str(e)))
            except Exception as e:                       # noqa: BLE001
                self._queue.put(("failed", "%s: %s" % (type(e).__name__, e)))

        self._worker = threading.Thread(target=work, name="quilla-upgrade", daemon=True)
        self._worker.start()

    def cancel(self):
        if self._worker is not None and self._worker.is_alive():
            self._cancel_evt.set()
            self.btn_cancel.configure(state="disabled")
            self.var_status.set(i18n.t("gui.status_cancelled"))
            self.log("warn", i18n.t("sess.cancel_requested"))

    def probe(self):
        """Read the banner and the shell fingerprints without upgrading."""
        if self._worker is not None and self._worker.is_alive():
            return
        port = self._selected_port()
        if not port:
            messagebox.showwarning(i18n.t("gui.dlg_no_port_title"),
                                   i18n.t("gui.dlg_no_port"))
            return
        try:
            baud = int(self.var_baud.get())
        except ValueError:
            baud = 115200
        self.btn_start.configure(state="disabled")
        self.pbar.configure(mode="indeterminate")
        self.pbar.start(12)
        self.var_status.set(i18n.t("gui.status_probe_done"))

        def work():
            app_reset = self.var_app_reset.get()
            app_reset_hex = (self.var_app_reset_hex.get()
                             if self.var_use_hex_reset.get() else "")
            sess = Session(port, baud,
                           on_log=lambda lvl, msg: self._queue.put(("log", lvl, msg)),
                           on_progress=lambda *a: None,
                           cancel=self._cancel_evt.is_set,
                           reset_cmd=app_reset, reset_cmd_hex=app_reset_hex)
            try:
                sess._open()
                banner = sess._drain_text(4.0)
                self._queue.put(("log", "info", "banner=%r" % banner))
                for cmd in (b"part\n", b"pinfo\n"):
                    out = sess._query_line(cmd, 2.0)
                    self._queue.put(("log", "info", "%s -> %r"
                                     % (cmd.strip().decode(), out)))
                self._queue.put(("probe_done", None))
            except PortOpenError as e:
                self._queue.put(("port_error", e.kind, str(e)))
            except Exception as e:                       # noqa: BLE001
                self._queue.put(("failed", str(e)))
            finally:
                sess.close()

        self._worker = threading.Thread(target=work, name="quilla-probe", daemon=True)
        self._worker.start()

    # -------------------------------------------------------------------- pump
    def _pump(self):
        try:
            while True:
                item = self._queue.get_nowait()
                self._handle(item)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _handle(self, item):
        kind = item[0]

        if kind == "log":
            self.log(item[1], item[2])
            return

        if kind == "prog":
            _, phase, done, total = item
            self._on_progress(phase, done, total)
            return

        if kind == "done":
            result = item[1]
            self.pbar.stop()
            self.pbar.configure(mode="determinate", value=1000)
            self.var_status.set(i18n.t("gui.status_success"))
            self.var_detail.set(i18n.t("gui.detail_done",
                                       total=result.elapsed,
                                       write=result.write_elapsed,
                                       speed=result.speed))
            self.log("ok", i18n.t("gui.done_msg", result=result))
            messagebox.showinfo(i18n.t("gui.dlg_success_title"),
                                i18n.t("gui.dlg_success", stamp=result.stamp))
            self._finish()
            return

        if kind == "cancelled":
            self.pbar.stop()
            self.pbar.configure(mode="determinate", value=0)
            self.var_status.set(i18n.t("gui.status_cancelled"))
            self.log("warn", i18n.t("gui.dlg_cancelled"))
            self._finish()
            return

        if kind == "port_error":
            kind_of_error, msg = item[1], item[2]
            self.pbar.stop()
            self.pbar.configure(mode="determinate", value=0)
            self.var_status.set(i18n.t("gui.status_port_err"))
            self.log("err", msg)
            title = {
                "busy": i18n.t("gui.port_err_busy"),
                "not_ready": i18n.t("gui.port_err_not_ready"),
                "not_found": i18n.t("gui.port_err_not_found"),
            }.get(kind_of_error, i18n.t("gui.port_err_other"))
            messagebox.showerror(title, msg)
            self._finish()
            return

        if kind == "failed":
            self.pbar.stop()
            self.pbar.configure(mode="determinate", value=0)
            self.var_status.set(i18n.t("gui.status_failed"))
            self.log("err", item[1])
            messagebox.showerror(i18n.t("gui.dlg_fail_title"), item[1])
            self._finish()
            return

        if kind == "probe_done":
            self.pbar.stop()
            self.pbar.configure(mode="determinate", value=0)
            self.var_status.set(i18n.t("gui.status_probe_done"))
            self.log("info", i18n.t("gui.probe_done"))
            self._finish()
            return

    def _on_progress(self, phase, done, total):
        if phase == Progress.WRITE and total:
            if str(self.pbar.cget("mode")) != "determinate":
                self.pbar.stop()
                self.pbar.configure(mode="determinate", value=0)
            self._last_done = done
            pct = done * 100.0 / total
            self.pbar.configure(value=int(done * 1000 / total))
            now = time.time()
            dt = now - self._last_time
            speed = ""
            eta = ""
            if dt >= 0.5:
                inst = (done - self._last_bytes) / dt
                self._last_bytes = done
                self._last_time = now
                if inst > 0:
                    speed = i18n.t("gui.detail_speed", speed=inst / 1024.0)
                    remain = (total - done) / inst
                    eta = i18n.t("gui.detail_eta", eta=remain)
            self.var_status.set(i18n.t("gui.writing_pct", pct=pct))
            self.var_detail.set(" ".join(x for x in (
                i18n.t("gui.detail_progress", done=done, total=total), speed, eta) if x))
            return

        # Phase-only transitions: show an indeterminate bar with a clear label.
        # END is deliberately not in this list - it follows a full determinate
        # write, and flipping the bar back to a marquee would read as a regression.
        if phase in (Progress.SIGN, Progress.VERIFY, Progress.ENTER,
                     Progress.DETECT):
            if str(self.pbar.cget("mode")) != "indeterminate":
                self.pbar.configure(mode="indeterminate")
                self.pbar.start(12)
            self.var_status.set(_phase_text(phase))
            if phase == Progress.SIGN:
                self.var_detail.set(i18n.t("gui.sign_detail"))
            elif phase == Progress.VERIFY:
                self.var_detail.set(i18n.t("gui.verify_detail"))
            return

    def _finish(self):
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self._cancel_evt.clear()
        self._worker = None
        config.update(port=self._selected_port(), baud=self.var_baud.get())


class KeyToolPage(ttk.Frame):
    """Key management: generate a keypair, or derive the public key from a seed.

    Deliberately on a separate tab. Signing keys are a different job from
    flashing a board: an operator on the bench should never generate a key by
    accident, and the private seed is the one thing in this tool that must never
    leave the signing station.

    The page never displays a private seed. It shows the path, the public key,
    and the macro to bake into QBOOT - nothing that would be dangerous in a
    screenshot.
    """

    def __init__(self, master, app):
        ttk.Frame.__init__(self, master, padding=12)
        self.master = master
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self.var_dir = tk.StringVar(value=app.cfg["key_dir"])
        self.var_priv = tk.StringVar()
        self._last_pub = None

        # -- generate ---------------------------------------------------------
        box = ttk.LabelFrame(self, padding=10)
        self._tr(box, "text", "gui.gen_keys")
        box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)
        self._tr(ttk.Label(box, text="输出目录"), "text", "gui.output_dir").grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(box, textvariable=self.var_dir).grid(row=0, column=1, sticky="ew")
        self._tr(ttk.Button(box, width=8, command=self._pick_dir), "text",
                 "gui.select").grid(row=0, column=2, padx=(6, 0))
        self._tr(ttk.Button(box, width=12, command=self.generate), "text",
                 "gui.gen_keys_btn").grid(row=0, column=3, padx=(6, 0))
        self._tr(ttk.Label(box, foreground="#555555", text=""), "text",
                 "gui.gen_keys_hint").grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(4, 0))

        # -- derive -----------------------------------------------------------
        box = ttk.LabelFrame(self, padding=10)
        self._tr(box, "text", "gui.derive_title")
        box.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)
        self._tr(ttk.Label(box, text="私钥文件"), "text", "gui.priv_file").grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(box, textvariable=self.var_priv).grid(row=0, column=1, sticky="ew")
        self._tr(ttk.Button(box, width=8, command=self._pick_priv), "text",
                 "gui.select").grid(row=0, column=2, padx=(6, 0))
        self._tr(ttk.Button(box, width=12, command=self.derive), "text",
                 "gui.derive_btn").grid(row=0, column=3, padx=(6, 0))
        self._tr(ttk.Label(box, foreground="#555555", text=""), "text",
                 "gui.derive_hint").grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(4, 0))

        # -- result -----------------------------------------------------------
        box = ttk.LabelFrame(self, padding=6)
        self._tr(box, "text", "gui.result")
        box.grid(row=2, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.txt = tk.Text(box, height=10, wrap="word", state="disabled",
                           font=("Consolas", 10), background="#FBFBF9",
                           relief="flat", borderwidth=0)
        ys = ttk.Scrollbar(box, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=ys.set)
        self.txt.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        for tag, color in LOG_COLORS.items():
            self.txt.tag_configure(tag, foreground=color)

        bar = ttk.Frame(box)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._tr(ttk.Button(bar, width=10, command=self._copy_pub), "text",
                 "gui.copy_pub").pack(side="left")
        self._tr(ttk.Button(bar, width=12, command=self._copy_macro), "text",
                 "gui.copy_macro").pack(side="left", padx=(8, 0))
        self._tr(ttk.Button(bar, width=8, command=self._clear), "text",
                 "gui.clear").pack(side="right")

        self._write([("warn", i18n.t("gui.key_warn") + "\n")])

    # ---------------------------------------------------------------- helpers
    def _tr(self, widget, attr, key, **kw):
        def apply():
            widget.configure(**{attr: i18n.t(key, **kw)})
        apply()
        self.app._tr_registry.append(apply)
        return widget

    def _write(self, items):
        self.txt.configure(state="normal")
        for tag, text in items:
            self.txt.insert("end", text, tag)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _clear(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    def _pick_dir(self):
        d = filedialog.askdirectory(title=i18n.t("gui.output_dir"),
                                    initialdir=self.app.cfg["last_dir"] or None)
        if d:
            self.var_dir.set(d)
            config.update(key_dir=d)

    def _pick_priv(self):
        p = filedialog.askopenfilename(title=i18n.t("gui.private_key"),
                                      initialdir=self.app.cfg["last_dir"] or None,
                                      filetypes=[("Key", "*.hex"), ("All files", "*.*")])
        if p:
            self.var_priv.set(p)
            config.update(last_dir=os.path.dirname(p))

    def _copy(self, text, what):
        if not text:
            messagebox.showinfo(i18n.t("gui.dlg_no_clip_title"),
                                i18n.t("gui.dlg_no_clip"))
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._write([("ok", i18n.t("kt.copied", what=what) + "\n")])

    def _copy_pub(self):
        self._copy(self._last_pub.hex() if self._last_pub else "",
                   i18n.t("kt.pub_hex").strip())

    def _copy_macro(self):
        self._copy(ed25519.pubkey_macro(self._last_pub) if self._last_pub else "",
                   i18n.t("kt.macro_head").strip())

    # ---------------------------------------------------------------- actions
    def generate(self):
        d = self.var_dir.get().strip()
        if not d:
            messagebox.showwarning(i18n.t("gui.dlg_no_dir_title"),
                                   i18n.t("gui.dlg_no_dir"))
            return
        sk = os.path.join(d, "private.hex")
        pk = os.path.join(d, "public.hex")
        if os.path.exists(sk):
            if not messagebox.askyesno(
                    i18n.t("gui.dlg_key_exists_title"),
                    i18n.t("gui.dlg_key_exists", path=sk),
                    icon="warning", default="no"):
                return
        try:
            _seed, pkb = ed25519.keygen(d)
        except Exception as e:                            # noqa: BLE001
            messagebox.showerror(i18n.t("gui.dlg_gen_fail_title"), str(e))
            return
        self._last_pub = pkb
        self._clear()
        self._write([
            ("ok", i18n.t("kt.generated")),
            ("info", i18n.t("kt.seed_line", path=sk)),
            ("info", i18n.t("kt.pub_line", path=pk)),
            ("info", i18n.t("kt.pub_hex")),
            ("info", pkb.hex() + "\n\n"),
            ("info", i18n.t("kt.macro_head")),
            ("ok", ed25519.pubkey_macro(pkb) + "\n\n"),
            ("warn", i18n.t("gui.key_warn") + "\n"),
        ])

    def derive(self):
        p = self.var_priv.get().strip()
        if not p:
            messagebox.showwarning(i18n.t("gui.dlg_no_key_title"),
                                   i18n.t("gui.dlg_no_key"))
            return
        try:
            seed = ed25519.load_seed_hex(p)
            pkb = ed25519.pubkey_from_seed(seed)
        except Exception as e:                            # noqa: BLE001
            messagebox.showerror(i18n.t("gui.dlg_invalid_key_title"), str(e))
            return
        self._last_pub = pkb
        self._clear()
        self._write([
            ("ok", i18n.t("kt.derived")),
            ("info", i18n.t("kt.pub_hex")),
            ("info", pkb.hex() + "\n\n"),
            ("info", i18n.t("kt.macro_head")),
            ("ok", ed25519.pubkey_macro(pkb) + "\n"),
        ])


class UpdaterApp(ttk.Frame):
    """Window shell: the upgrade page, plus the key tool on a second tab."""

    def __init__(self, master):
        ttk.Frame.__init__(self, master)
        self.pack(fill="both", expand=True)
        self.master = master

        self.cfg = config.load_config()
        i18n.set_language(self.cfg["lang"])
        self._tr_registry = []

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)

        self.upgrade = UpgradePage(self.nb, self)
        self.keys = KeyToolPage(self.nb, self)
        self.nb.add(self.upgrade, text=i18n.t("gui.fw_upgrade"))
        self.nb.add(self.keys, text=i18n.t("gui.key_tool"))

        self._build_lang_bar()
        self._set_title()

    # --------------------------------------------------------- language switch
    def _build_lang_bar(self):
        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=6, pady=(6, 0))
        self._tr_label = ttk.Label(top, text="")
        self._tr(self._tr_label, "text", "gui.lang")
        self._tr_label.pack(side="left")

        self.var_lang = tk.StringVar(value=self._lang_label(self.cfg["lang"]))
        self.cmb_lang = ttk.Combobox(top, textvariable=self.var_lang,
                                    state="readonly", width=9,
                                    values=[self._lang_label(c) for c, _ in LANG_CHOICES])
        self.cmb_lang.pack(side="left", padx=(6, 0))
        self.cmb_lang.bind("<<ComboboxSelected>>", self._on_lang_change)

    @staticmethod
    def _lang_label(code):
        for c, key in LANG_CHOICES:
            if c == code:
                return i18n.t(key)
        return i18n.t(LANG_CHOICES[0][1])

    def _on_lang_change(self, _evt=None):
        label = self.var_lang.get()
        code = next((c for c, key in LANG_CHOICES
                     if i18n.t(key) == label), "auto")
        self.cfg["lang"] = code
        config.update(lang=code)
        self._apply_language()

    def _apply_language(self):
        i18n.set_language(self.cfg["lang"])
        for fn in self._tr_registry:
            fn()
        # The picker entries are autonyms, but the combobox values still have to
        # be rebuilt because i18n may resolve them differently after a switch.
        self.cmb_lang.configure(values=[self._lang_label(c) for c, _ in LANG_CHOICES])
        self.var_lang.set(self._lang_label(self.cfg["lang"]))
        self.nb.tab(0, text=i18n.t("gui.fw_upgrade"))
        self.nb.tab(1, text=i18n.t("gui.key_tool"))
        self._set_title()
        self.upgrade._render_status_idle()
        self.upgrade._render_fw_info()
        self.upgrade._render_key_info()

    def _set_title(self):
        self.master.title(i18n.t("gui.title"))

    def _tr(self, widget, attr, key, **kw):
        def apply():
            widget.configure(**{attr: i18n.t(key, **kw)})
        apply()
        self._tr_registry.append(apply)
        return widget

    def __getattr__(self, name):
        """Transparently expose the upgrade page's widgets on the shell.

        Keeps `app.var_fw` / `app._ports` working for scripts and tests without
        wrapping every attribute by hand. Only called when normal lookup fails.
        """
        try:
            upgrade = self.__dict__["upgrade"]
        except KeyError:
            raise AttributeError(name)
        return getattr(upgrade, name)


def main():
    root = tk.Tk()
    root.geometry("900x700")
    root.minsize(780, 600)
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", padding=(14, 6))
        style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TCombobox", padding=(4, 3))
    except Exception:
        pass
    UpdaterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
