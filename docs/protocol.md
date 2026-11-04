# QBOOT serial upgrade protocol

**English** · [中文](protocol.zh-CN.md)

The wire protocol the QBOOT bootloader speaks over UART, and the exact subset
this tool implements. Everything here is derived from the firmware sources, not
from documentation:

| Topic | Firmware source of truth |
|---|---|
| Frame format, command dispatch | `os/services/quilla-qboot/quilla-qiap.c` |
| CRC algorithm | `os/lib/crc16.c` (`crc16_add` / `crc16_data`) |
| Partition layout, page size, unlock key | `os/services/quilla-qboot/quilla-qboot-hal.h` |
| Signature verification, security version read | `os/services/quilla-qboot/quilla-qboot-secure.c` |
| `.quilla_secver` layout | `os/sys/quilla-app-secver.h`, `os/sys/quilla-version.h` |

If the two ever disagree, the firmware wins.

---

## 1. Frame format

Identical in both directions.

```
+------+-----+----------+------------------+----------+
| SOF  | CMD | LEN (LE) | PAYLOAD          | CRC16 LE |
| 1 B  | 1 B | 2 B      | LEN bytes        | 2 B      |
+------+-----+----------+------------------+----------+
  0xA5
```

* `CRC16` covers `CMD | LEN | PAYLOAD`. The `SOF` byte is **not** covered.
* Algorithm: polynomial `0x1021`, reflected, initial accumulator `0`. This is a
  byte-at-a-time replication of `crc16_add()`, not a table-driven CRC.
* The accumulated CRC is chainable: `crc16(b, crc16(a)) == crc16(a + b)`. The
  device relies on this to fold each DATA payload into a running total.

Any byte other than `0xA5` at the SOF position is discarded, which is how the
host ignores the device's text banner (`[BOOT] Quilla V...`) and shell echo on
the same wire.

## 2. Commands

| CMD | Name | Payload (host to device) | ACK | ACK payload |
|---|---|---|---|---|
| `0x01` | ENTER | `app_start` u32 LE + `unlock_key` 8 B | `0x81` | `status` u8 |
| `0x02` | DATA | `start` u32 + `end` u32 + `data` ≤ 256 B | `0x82` | `start` u32 (echo) |
| `0x03` | END | `total_len` u32 + `total_crc16` u16 | `0x83` | `status` u8 |
| `0x04` | SIGN | `signature` 64 B (Ed25519) | `0x84` | `status` u8 |

`status == 0` means success.

A rejection uses `CMD = 0xC0 | phase`:

| NAK | Phase | Meaning |
|---|---|---|
| `0xC1` | ENTER | rejected during ENTER |
| `0xC2` | DATA | rejected during DATA |
| `0xC3` | other | frame-level failure (usually CRC) |
| `0xC4` | SIGN | rejected during SIGN |

Payload is a single reason byte:

| Reason | Tag | Cause |
|---|---|---|
| `0x01` | ADDR | address out of the APP region |
| `0x02` | KEY | unlock key mismatch |
| `0x03` | CRC | frame/field CRC error |
| `0x04` | ERASE | flash page erase failed |
| `0x05` | PROG | flash program/readback failed |
| `0x06` | LEN | total length or total CRC mismatch |
| `0x07` | SZ | length field does not match data length |
| `0x08` | SIGN | signature did not verify (unsigned or key mismatch) |
| `0x09` | VER | no usable security-version region in the image |
| `0x0A` | ROLLBACK | image version is below the device floor |

**Only reason `0x03` is retransmittable.** Everything else is a parameter,
key, or flash fault; resending the same frame just wastes a 40-second transfer
and hides the real cause, so this tool aborts immediately.

## 3. Session flow

```
host                                    device
 |                                        |
 |  ("qiap" text command, if in shell)    |
 |--------------------------------------->|
 |                                        |
 |  ENTER(app_start, unlock_key)          |
 |--------------------------------------->|  validates app_start against the
 |<--------------------------------- 0x81 |  APP region, sets the QIAP flag
 |                                        |
 |  DATA(start, end, chunk)               |  erases the page when the first
 |--------------------------------------->|  byte of a new page arrives,
 |<--------------------------------- 0x82 |  programs, echoes start
 |            ... repeated ...            |
 |                                        |
 |  END(total_len, total_crc)             |
 |--------------------------------------->|  verifies chained CRC and length
 |<--------------------------------- 0x83 |  QBOOT_CHECK: commits + resets
 |                                        |  SEALED/SEC: only ACKs, waits for SIGN
 |  SIGN(signature)                       |
 |--------------------------------------->|  SHA-256 + Ed25519, inline
 |<--------------------------------- 0x84 |  commits, writes APP flag, resets
 |                                        |
 |  === completion verdict, all variants ===|  before the reset
 |  ... device reboots ...                |
 |<------ "[QAPP] <name> V<ver>" ---------|  optional post-confirmation
```

`END` behaves differently depending on the QBOOT build variant:

* **QBOOT_CHECK** (CHECK mode, no public key): `END` commits and resets. `SIGN`
  is never sent.
* **QBOOT_SEALED / QBOOT_SEC** (SEALED / SECURE mode, public key): `END` only
  acknowledges. The APP flag is written and the MCU resets only after `SIGN`
  verifies. Skipping `SIGN` leaves the upgrade uncommitted.

`commit_app()` runs before the completion ACK on both paths, so the host's
verdict is available **before the reset** for all three variants. See section
7.3 for why the boot stamp is not that verdict.

The host cannot tell which case it is in from the protocol alone - there is no
capability query - so it probes the device's behaviour instead: after `ACK 0x83`
it listens briefly for `[QIAP] flash complete. Rebooting into APP...` (older
QBOOT builds print `[QIAP] success. Rebooting...`), which QBOOT emits only after
`done=1`, immediately before the commit reset. Seen → the device already
committed, and `SIGN` is skipped. Not seen → the device is a keyed build
waiting for the signature.

Sending `SIGN` to a device that already committed is not merely redundant: the
APP shell does not speak QIAP, so no `ACK 0x84` can be produced and the host
would wait the full `SIGN_TIMEOUT` on a board that is already running the new
firmware.

## 4. Entering upgrade mode

The device may be in any of four states. The operator should not have to know
which, so the host probes:

| State | Fingerprint (`part` reply) | Host action |
|---|---|---|
| A. upgrade-idle, QIAP flag left over | banner contains `enter upgrade mode` | send ENTER directly |
| B. QBOOT shell | echo contains `qboot` | send `qiap`, wait for `enter upgrade mode`, ENTER |
| C. APP shell (firmware running) | echo contains `app1` | send `swqboot`, wait for `[BOOT]`, then B |
| D. upgrade-idle, raw sink | empty reply, no echo | send ENTER directly |

A "send a newline and look for a `>` prompt" probe cannot distinguish B from D:
the shell does not reprint its prompt on an empty line, so both return nothing.
The `part` echo is the discriminator, and a binary ENTER frame still reaches the
state machine in state D even though text commands are swallowed.

## 5. Signed object

`SIGN` carries a 64-byte Ed25519 signature over:

```
image_len (u32 LE) || SHA-256(image)
```

This matches `quilla_qboot_secure_verify_descriptor()`.

The security version is **not** part of the signed object. QBOOT reads it from
the image itself, at `APP_START + 0x400`:

```c
struct {
    uint32_t magic;    /* 0x31564151, "QAV1" little-endian */
    uint32_t version;  /* QUILLA_APP_SECURITY_VERSION */
} quilla_app_secver_t;
```

and rejects the image when `version` is below its anti-rollback floor
(`NAK 0x0A`). The host cannot supply or lower the version: it is covered by the
signature as ordinary image content, and the comparison is done on the device.

Cross-check before a long transfer: this tool reads the same 8 bytes out of the
`.bin` and shows the version in the UI, so a downgrade is caught before 40
seconds of writing rather than after.

## 6. Partition layout

Physical order is BOOT → META → APP.

| Region | Address | Size | Notes |
|---|---|---|---|
| QBOOT | `0x08000000` | 24 KiB | read-only in normal operation |
| META | `0x08006000` | 4 KiB | wear-levelled dual slots: flag, floor, seal, manifest |
| APP | `0x08007000` → `SOC_FLASH_END` | MCU dependent | the upgrade target |

`APP_START` is fixed by the META layout and is identical on every current MCU.
`APP_END` depends on `SOC_FLASH_END` (PY32F040xB = 128 KiB → `0x0801FFFF`,
GD32F502VE = 512 KiB), so the host **never** hard-codes it: it asks the device
via the `pinfo` shell command and uses the reply as its pre-write ceiling. If
`pinfo` is unavailable (old firmware, or already in the raw sink) the host skips
its own check and lets the device's `ADDR` NAK (`0x01`) enforce the real bound.

Erase granularity is one page (256 B), so only page alignment matters.

## 7. Timing constraints

These are firmware properties, not tuning knobs. Changing them breaks the link.

### 7.1 Receive path: QBOOT rings, not the APP's shell port

The upgrade runs entirely inside QBOOT, so the sizing constraint is QBOOT's
receive path and not the APP's shell port:

| Stage | Size | Behaviour |
|---|---|---|
| USART2 RX DMA | 1024 B, CIRCULAR | never re-armed; keeps filling while the loop is blocked in a flash page erase |
| QBOOT bridge ring | 512 B | `qboot_rx_sink()` drops on overflow; sized to hold one whole 270 B frame |
| QIAP payload buffer | `PAGE_SIZE + 8` = 264 B | `QUILLA_QIAP_MAX_PAYLOAD` |

`CHUNK = 256` → DATA frame `8 + 256 = 264` bytes of payload, `270` bytes on the
wire; SIGN frame `6 + 64 = 70` bytes. The old "64-byte NORMAL (ping-pong) DMA"
limit described a firmware generation that has since been replaced by circular
DMA.

The bridge ring is a byte-stream buffer rather than a frame buffer, but it is
sized to absorb one complete frame (512 B against a 270 B frame), so a frame
enters atomically and is never split across passes. QBOOT drains it to empty
every pass, so occupancy is the backlog between two passes (one host write
burst), not the frame size. What would break it is pipelining frames, not long
ones.

What actually keeps the rings safe is the **stop-and-wait handshake**: one frame
in flight, ACK before the next. No bytes are on the wire during a page erase, so
the bridge ring never receives a burst larger than one frame and never overflows.
That is why a 1024-byte DMA ring is enough for a ~460-byte erase window.

Consequences the host must respect:

* Keep exactly one frame in flight. Pipelining frames is what would overflow the
  bridge ring, not the frame size.
* `CHUNK = 256` is the hard ceiling: `QUILLA_QIAP_MAX_PAYLOAD` is `PAGE_SIZE + 8`
  and the device drops any frame whose LEN exceeds it back to SOF. 256 also makes
  one frame exactly one page, which is why the write is one erase per page
  instead of one per six frames.
* A DATA frame that echoes a *different* start address means a whole frame was
  lost; resending cannot self-heal, so the session is reported as misaligned and
  the operator must reset the board.

On a 115200 baud link, a 270-byte frame (23 ms) plus one ACK round trip (~2 ms)
plus a ~30–40 ms page erase puts the practical ceiling at roughly 4–4.5 KiB/s: a
128 KiB image takes about 30–35 s, down from 40–60 s at `CHUNK = 48`.

### 7.2 SIGN needs a long timeout

On receiving `SIGN` the device runs a full verification inline:

| Step | Time @ 8 MHz (PY32F040) |
|---|---|
| SHA-256 over the image | ~0.56 s |
| Ed25519 verify | ~20.11 s |
| **Total** | **~20.6 s** |

Those figures are instruction-count arithmetic for a stock implementation. The
reference PY32F040xB board running the current QBOOT answers `SIGN` with
`ACK 0x84` about 3 s after the frame is sent, so treat the table as an upper
bound rather than a measurement.

* ACK timeout for `SIGN` must exceed the worst case; this tool uses 90 s and does
  not lower it, because the cost of being wrong is a false failure on a board
  that already flashed correctly.
* `SIGN` is sent **once**. A retransmit would make the device verify twice and
  desynchronise the state machine.
* The UI must say so, otherwise the operator pulls the cable during a healthy
  upgrade. It names the phase without promising a fixed duration.

### 7.3 Completion verdict and boot stamp

The upgrade is reported complete **before the reset**, on QBOOT-side evidence:

| Variant | Mode | Completion evidence |
|---|---|---|
| QBOOT_CHECK | CHECK (no key) | `ACK 0x83` + `[QIAP] flash complete...` |
| QBOOT_SEALED | SEALED (key) | `ACK 0x84` after `SIGN` |
| QBOOT_SEC | SECURE (key) | `ACK 0x84` after `SIGN` |

A lost ACK can be covered by the commit announcement or by a matching `[QAPP]`
stamp; a port lost to the reset is accepted as **weak** evidence and logged as
such, because a cable pull is indistinguishable. With a still-live port and no
evidence at all, the run fails.

After the reset the device re-runs its startup checks before the APP starts:

| Mode | Startup cost |
|---|---|
| CHECK | SHA-256 integrity check, ~0.1 s |
| SEALED (default) | SHA-256 + seal compare, ~0.6 s |
| SECURE | full Ed25519 verify, seconds to tens of seconds |

Because these costs differ by two orders of magnitude, the host does **not**
wait for any of them. It checks for 0.5 s at bytes that arrived alongside the
completion code; `[QAPP]` is recorded, matched against
`FirmwareImage.expected_stamp`, and otherwise ignored. `wait_app_stamp()` (45 s)
remains available for callers that explicitly want to watch the new firmware
boot, but it is not part of `run()`'s verdict.

## 8. What this tool does not do

* No `.hex` parsing — the upgrade path takes a raw `.bin` only.
* No A/B slot management, no image staging: `ENTER` begins an in-place write to
  the APP region.
* No key provisioning. The public key is baked into QBOOT at build time with
  `-DQUILLA_SECURE_BOOT_PUBKEY={...}`; this tool only signs with a private key.

## 9. Power-loss behaviour

Once `ENTER` is accepted the QIAP flag is set, so a power loss before the commit
leaves the device in the upgrade-idle state on the next boot (state A above)
instead of jumping into a half-written image. Re-running the tool recovers it.

The window that is *not* protected: losing power between the APP flag write and
the reset, after `SIGN` has verified. What QBOOT does in that case depends on how
that build handles a committed-but-unreset flag. That path is outside what this
host tool can observe, and has not been verified here - if it matters for your
product, test it on the target rather than trusting this document.
