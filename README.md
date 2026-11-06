# Quilla Updater

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-3--clause%20BSD-brightgreen.svg" alt="3-clause BSD license"></a>
  <a href="https://github.com/JiChiRen/Quilla"><img src="https://img.shields.io/badge/works%20with-Quilla%20QBOOT-00599C.svg" alt="works with Quilla QBOOT"></a>
  <img src="https://img.shields.io/badge/python-3.8%2B-blue.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/dependencies-pyserial%20only-orange.svg" alt="one dependency: pyserial">
  <img src="https://img.shields.io/badge/UI-%E4%B8%AD%E6%96%87%20%7C%20English-blueviolet.svg" alt="bilingual UI: Chinese | English">
</p>

**English** · [中文](README.zh-CN.md)

Host-side UART upgrader for **Quilla QBOOT** boards. Pick a serial port, pick a
`.bin`, click start. Same engine on the command line for production lines and CI.

The protocol is the one QBOOT already speaks (see [docs/protocol.md](docs/protocol.md),
also in [中文](docs/protocol.zh-CN.md)); this project is the missing window around
it. It is a re-implementation and extension of `tools/quilla_host_updater.py`
from the [Quilla](https://github.com/JiChiRen/Quilla) tree, with a UI, a
cooperative cancel path, and pre-flight checks that catch a doomed upgrade before
it costs you a minute.

```
+----------------------+        +---------+        +------------------+
|  GUI (Tk) / CLI      |  UART  |  QBOOT  |  flash |  APP region      |
|  core: protocol +    | <----> |  QIAP   | -----> |  0x08007000..    |
|  session + signer    |        |         |        |                  |
+----------------------+        +---------+        +------------------+
```

## Features

- **Zero setup** - Python 3.8+, one dependency (`pyserial`). No Qt, no Node, no
  installer.
- **The board's state does not matter** - running firmware, QBOOT shell, or a
  leftover interrupted upgrade are all detected and handled.
- **Signature is optional and explicit** - no key means no `SIGN` frame, and the
  UI says so instead of failing 40 seconds later with `NAK 0x08`. If the device
  does hold a public key, the run stops right after `END` and names the missing
  key instead of waiting out the boot-stamp window.
- **Pre-flight** - shows the image size, SHA-256, and the anti-rollback security
  version read straight out of the `.bin`, before anything is written.
- **Honest progress** - the long silent stretches are labelled. During `SIGN` the
  device verifies Ed25519 inline and the link goes quiet; the UI names that
  phase and says "do not power off" instead of looking frozen.
- **Cooperative cancel** - stops between frames, leaves the board recoverable
  (the QIAP flag stays set, so a re-run resumes).
- **Completion before the reset** - QIAP commits before it ACKs, so CHECK,
  SEALED and SECURE builds are all reported complete on QBOOT-side evidence;
  the verdict depends on neither the boot stamp nor the UART the APP prints on.
- **Remembers your setup** - firmware path, key path, port and baud rate survive
  a restart, so a second upgrade is one click.
- **Bilingual UI** - Chinese / English, switchable at runtime from the top bar,
  or automatically from the system locale. The CLI follows the same setting and
  takes `--lang` to override it.

## Settings

Operator preferences live in `~/.quilla_updater/config.json` (outside the repo -
they are personal to whoever runs the tool, not part of the project source):

| Key | Meaning |
|---|---|
| `fw_path` | last firmware `.bin` |
| `key_path` | last private key |
| `use_key` | whether the `SIGN` frame is enabled |
| `port` / `baud` | last serial port and baud rate |
| `lang` | `auto` / `zh` / `en` |
| `last_dir` / `key_dir` | last directories used by the file dialogs |

The file is best-effort: if the home directory is not writable the tool still
runs, it just does not remember choices across launches.

Language selection is `auto` by default, which resolves to Chinese on a
Chinese-locale host and English everywhere else. Pick an explicit value in the
top bar to override it; the choice is persisted and applies to the CLI too.

## Quick start

### Prebuilt executable (Windows, no Python needed)

Download the latest `QuillaUpdater.exe` from
[Releases](https://github.com/JiChiRen/QuillaUpdater/releases) and run it. It is a
single file with the interpreter, `pyserial` and Tk bundled; nothing is installed
and nothing is written outside `%USERPROFILE%\.quilla_updater\`.

`quflash.exe` from the same release is the console build, for a production line
or a CI step that cannot click a button.

The executables are unsigned, so SmartScreen will warn the first time. Verify the
SHA-256 published with the release before running it on a production bench.

### GUI from source (Windows)

```bat
run.bat
```

Installs `pyserial` on first run if missing, then opens the window.

### GUI (Linux / macOS)

```bash
./run.sh
# Debian/Ubuntu, if tkinter is missing:
#   sudo apt install python3-tk
```

### CLI

```bash
pip install pyserial

python -m quilla_updater --list-ports
python -m quilla_updater COM7 firmware.bin                     # unsigned
python -m quilla_updater COM7 firmware.bin -b 115200 \
       --key keys/private.hex                                  # signed
python -m quilla_updater COM7 --probe                          # what state is the board in?
python -m quilla_updater --self-test                           # offline checks, no hardware
python -m quilla_updater --audit-i18n                          # translation table check
python -m quilla_updater --lang en COM7 firmware.bin            # force English output
```

After `pip install .` the same commands are available as `quflash`.

### Language

The CLI follows the language chosen in the GUI. Override it per invocation:

```bash
python -m quilla_updater --lang zh COM7 firmware.bin
python -m quilla_updater --lang en COM7 firmware.bin
```

`--help` renders in the requested language too, so the parser is built after
the language is resolved.

### The port will not open

Three different causes, three different fixes - the tool classifies them and
prints the matching steps, but here is the table for when you are reading this
before you have the error in front of you:

| What you see | Cause | Fix |
|---|---|---|
| `Access is denied` / `PermissionError(5)` | another program holds the port exclusively | close the serial assistant / PuTTY / an old copy of the upgrader; stop the Keil debug session |
| `Cannot configure port ... PermissionError(13, ..., 31)` | Windows `ERROR_GEN_FAILURE`. The port exists and the device tree says "status OK", but `SetCommState` is refused | see below - this one is almost never what it looks like |
| `could not find` / `FileNotFoundError(2)` | the port number changed or the cable is out | replug, then hit **Refresh** and reselect |

The `ERROR_GEN_FAILURE` case is worth spelling out because every diagnostic in
Windows says the device is fine:

- **A WCH-Link / J-Link / CMSIS-DAP probe shares one USB link between the debug
  interface and the CDC serial port.** While Keil sits in a debug session (or
  right after a download, before it detaches), the COM port is still listed and
  its status is still OK, and every attempt to configure it is refused. `Debug
  -> Stop`, or quit Keil, and the port comes back with no replug.
- If no debugger is running, the CDC state machine is stuck. Unplug the probe
  for three seconds and plug it back in - a different USB port if the same one
  fails twice.
- A soft reset without touching the cable, from an **administrator** shell:

  ```powershell
  $d = Get-PnpDevice -Class Ports | Where-Object FriendlyName -like '*COM7*'
  Disable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false
  Start-Sleep 2
  Enable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false
  ```

The tool retries a `not_ready` open twice (0.15 s, 0.5 s) before giving up,
because a probe that just left debug mode often fails the first `SetCommState`
and then works. It does not retry `busy` - that one will never succeed on its
own.

Note that the device manager reporting the port as healthy proves only that the
driver loaded. It says nothing about whether the port can be configured, which
is exactly the state this failure lives in.

### Keys

**In the GUI**: the **Key tool** (密钥工具) tab - the second tab, not the upgrade
page - generates a keypair or derives the public key from an existing
`private.hex`. Use the derive path to confirm the key in your hand matches the one
baked into the board - a `NAK 0x08` on SIGN is almost always a mismatch here, and
finding it that way costs a full transfer.

The tab never displays a private seed, only paths, the public key, and the build
macro, so it is safe to screenshot.

**From the CLI**:

```bash
python tools/keygen.py keygen --dir keys
python tools/keygen.py pubkey --key keys/private.hex
```

writes `keys/private.hex` (32-byte seed, **keep secret**) and `keys/public.hex`,
and prints the macro to compile into QBOOT:

```
-DQUILLA_SECURE_BOOT_PUBKEY={0x..,0x..,...}
```

Once a public key is flashed, QBOOT rejects any image without a valid `SIGN`
frame. `keys/` is in `.gitignore` for a reason.

## How success is decided

The verdict is reached **before the reset**, on QBOOT-side evidence. QIAP calls
`commit_app()` (`app_page_commit()` -> `flag=APP1` -> `done=1`) *before* it
sends its completion ACK, so that ACK is a completion code, not merely "the
frame arrived". All three QBOOT build variants commit before
`qboot_qiap_run()` reboots:

| Variant | Boot mode | Commit point | Completion evidence |
|---|---|---|---|
| `QBOOT_CHECK` | CHECK, no public key | inside `END` | `ACK 0x83` + `[QIAP] flash complete. Rebooting into APP...` |
| `QBOOT_SEALED` | SEALED, public key | after `SIGN` | `ACK 0x84` (`ACK_SIGN`) |
| `QBOOT_SEC` | SECURE, public key | after `SIGN` | `ACK 0x84` (`ACK_SIGN`) |

SEALED and SEC differ only **after** the reset: SEALED compares the seal in
~0.6 s, SECURE re-runs Ed25519 on every boot (~20 s). A verdict that waited
for the new APP's `[QAPP] <name> V<ver>` stamp would therefore take 20 s on a
SECURE build, and would fail outright on an APP that prints on another UART.
`run()` reports completion at the commit evidence and never waits for a reboot.

`ACK 0x83` alone is **not** a completion code: on a keyed build `END` only
acknowledges and waits for `SIGN`. The host tells the two cases apart with the
pre-reset announcement, which QBOOT prints only after `done=1`. Both the
current banner (`[QIAP] flash complete...`) and the older `[QIAP] success...`
spelling are recognised, so this host works with either QBOOT version;
`tools/verify_fixes.py` checks them against the firmware source when the Quilla
tree is available next to this one.

The `[QAPP]` stamp is an **optional post-confirmation**: `run()` checks for
0.5 s at bytes that arrived alongside the completion code (matched against
`FirmwareImage.expected_stamp`, so a stale banner from the old firmware is not
mistaken for the new one) and then returns. That window is shorter than every
boot path; it never waits for the reboot.

Two things follow from the firmware's commit rules, and both used to be wrong
here:

**END can end the conversation.** On `QBOOT_CHECK` the END handler commits,
QBOOT prints `[QIAP] flash complete. Rebooting into APP...` and resets. The
tool used to send `SIGN` regardless, wait `SIGN_TIMEOUT` (90 s) for an ACK that
the APP shell would never produce, and then report a failed upgrade on a board
that was already running the new firmware. `end()` now listens for the commit
announcement and skips `SIGN` when it arrives.

**Banners must survive frame parsing.** The commit announcement and the boot
stamp travel through the same port as the ACK frames, and they arrive exactly
while the host is waiting for an ACK. The old receiver built a throwaway parser
per call and discarded every byte that was not part of a frame, so the answer
being waited for was destroyed by the act of waiting. The receiver now keeps one
persistent parser plus a bounded raw log; markers already in the log are
honoured before any read, so an ACK and a banner in the same USB packet are both
seen.

Note on framing: the upgrade runs in QBOOT, so the size limit is its receive
path - a 1024-byte CIRCULAR DMA ring behind a 512-byte bridge ring, with a
`PAGE_SIZE + 8` payload buffer. The bridge ring is a byte stream rather than a
frame buffer, but it is sized to hold one whole 270 B frame, so a frame enters
atomically; it is drained to empty every loop pass, so occupancy tracks the
backlog between passes, not the frame size.

One DATA frame carries a full 256-byte page (264 B of payload, 270 B on the
wire), which is exactly `QUILLA_QIAP_MAX_PAYLOAD` - the device drops any frame
whose LEN exceeds it, so 256 is a ceiling, not a tuning knob. Page-aligned chunks
mean one erase per page instead of one per six frames. The arithmetic estimate is
4-4.5 KiB/s at 115200; a measured 15.3 KiB image moved in about 2 s (~7.7 KiB/s),
so the estimate is conservative. The "64-byte NORMAL DMA" limit cited by older
docs described firmware that no longer exists.

If the reset drops the port (composite debug probes: WCH-Link, J-Link), the
tool records the reset as **weak** completion evidence: the reset does follow
`done=1`, but a cable pull looks identical, so the log says so explicitly and
asks the operator to re-check the board. This is the only path where the
verdict does not rest on a QBOOT-side completion code. A still-live port with
no completion ACK, no announcement and no boot stamp is reported as a failure.

## What is not in this repository

Deliberately:

- **No private keys.** Not even a sample one. Any key committed here would let
  anyone sign an image your devices accept.
- **No firmware images.** The `.bin` is whatever you build.
- **No device-specific constants beyond the protocol.** `APP_END` is queried from
  the board at run time, never guessed - a hard-coded PY32F040xB ceiling once
  rejected perfectly valid GD32 images.

## Layout

```
quilla_updater/
  protocol.py   frame codec, CRC16, constants - mirrors the firmware
  session.py    state machine: detect -> ENTER -> DATA* -> END -> [SIGN] -> boot
  image.py      .bin loading, SHA-256, .quilla_secver, expected boot stamp
  ed25519.py    RFC 8032 signing, stdlib only
  ports.py      port enumeration with USB-bridge identification
  config.py     persisted operator settings (~/.quilla_updater/config.json)
  i18n.py       bilingual string table + locale detection
  cli.py        headless entry point
  gui.py        Tk front end
tools/keygen.py     key generation
tools/verify_fixes.py regression checks for config / commit-and-stamp / i18n
tools/build_exe.py  PyInstaller build for the two standalone executables
docs/protocol.md     wire format, timing constraints, power-loss behaviour
docs/protocol.zh-CN.md   Chinese translation of the above
```

The layers are strict: `protocol.py` knows nothing about serial ports,
`session.py` knows nothing about Tk, and the GUI knows nothing about frames. The
bundled UI is Tk because it ships with Python; swapping in Qt means rewriting
`gui.py` only.

## Tests

```bash
python -m quilla_updater.cli --self-test    # frame codec, CRC, Ed25519 vectors
python -m quilla_updater.cli --audit-i18n   # missing translations, key collisions
python tools/verify_fixes.py                # config persistence, SIGN semantics, GUI smoke
```

`tools/verify_fixes.py` needs no hardware: it drives the session against a fake
serial port and builds the Tk window headlessly. The fake device reproduces both
commit paths (END-commits and SIGN-commits), so the "finished but still waiting"
regression is covered end to end instead of only unit by unit.

## Verified against

- CRC16 and frame encoding: byte-identical to `os/lib/crc16.c` /
  `quilla_host_updater.py`, checked over random payloads.
- Ed25519: RFC 8032 section 7.1 vectors, plus signatures byte-identical to
  `tools/quilla_ed25519_sign.py` for a real 16.5 KiB QAPP image.
- `.quilla_secver`: parses `magic="QAV1"` + version out of a real PY32F040xB
  build at offset `0x400`.
- End to end on hardware: PY32F040xB over a WCH-Link CDC port at 115200, signed
  upgrade of a 15688-byte QAPP. One complete upgrade was run in each of the
  three boot modes - CHECK, SEALED and SECURE - and all three completed;
  `[QAPP] Project V0.10.0001` was observed after the reset. An earlier run on a
  board with no public key also exercised the commit-during-`END` path that used
  to hang for 90 s.
- Configurable APP-to-QBOOT reset command: both the default text command
  `swqboot` and a raw hexadecimal command are verified. On a board running an
  APP that does not expose the Quilla shell, sending `06 F0 5A 51 42 4F 54 80`
  (the literal "QBOT" embedded) reset the MCU into the QBOOT shell, after
  which a full signed upgrade completed. The hex path sends the bytes verbatim
  with no trailing newline; the run confirmed this - the post-reset `part`
  reply came back clean (`part\r\nqboot\r\n> `).

What is still untested: MCUs other than PY32F040xB (the APP ceiling depends on
their `pinfo` reply); the port-dropped-reopen path, which needs a probe that
actually removes the COM port on reset; the no-key-with-public-key error path,
which needs a board with a provisioned public key and a run deliberately started
without `--key`; and the weak-evidence path where the completion ACK is lost and
only a reset is seen.

## Building a standalone executable

```bash
pip install -e .[build]
python tools/build_exe.py            # both programs into dist/
python tools/build_exe.py --gui      # GUI only
python tools/build_exe.py --cli      # CLI only
python tools/build_exe.py --icon X.ico  # override the embedded Quilla logo
```

The Quilla logo (`quilla.ico`) is embedded in both executables by default;
pass `--icon` to use a different one. The GUI also shows the mark as its
window icon.

Produces `dist/QuillaUpdater.exe` (windowed, Tk bundled) and `dist/quflash.exe`
(console). Both are `--onefile`: no Python, no `pip install`, no DLLs to ship
alongside. `dist/` and `build/` are git-ignored, so a release is a build artifact
rather than a committed binary.

Two details the build handles explicitly, because a frozen build fails
differently from a source checkout:

- `pyserial` loads its platform backend lazily, so both `serial.serialwin32` and
  `serial.serialposix` plus `serial.tools.list_ports` are declared as hidden
  imports.
- A frozen Windows console inherits the host's ANSI code page (cp936 on a Chinese
  install) while this program emits UTF-8. `cli.main()` switches the console to
  code page 65001 and pins the stream encoders, otherwise every Chinese log line
  and port description renders as mojibake in Windows Terminal and VS Code.

Publish the release with the SHA-256 of each executable; the binaries are
unsigned.

## License

BSD-3-Clause, with the same copyright holder and terms as the Quilla project
this tool serves. Every source file carries the header, so a file lifted out of
this tree keeps its terms. `quilla_updater/ed25519.py` is ported from Quilla's
own `tools/quilla_ed25519_sign.py`, Copyright (c) 2026 JiChiRen Info. Tech.,
same license.

This repository contains no contiki-NG code. The Quilla tree does, and those
files keep their original Swedish Institute of Computer Science licence. The
header used here is not derived from theirs and does not restate it.
