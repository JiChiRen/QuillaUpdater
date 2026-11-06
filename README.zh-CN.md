# Quilla Updater

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-3--clause%20BSD-brightgreen.svg" alt="3-clause BSD license"></a>
  <a href="https://github.com/JiChiRen/Quilla"><img src="https://img.shields.io/badge/works%20with-Quilla%20QBOOT-00599C.svg" alt="works with Quilla QBOOT"></a>
  <img src="https://img.shields.io/badge/python-3.8%2B-blue.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/dependencies-pyserial%20only-orange.svg" alt="one dependency: pyserial">
  <img src="https://img.shields.io/badge/UI-%E4%B8%AD%E6%96%87%20%7C%20English-blueviolet.svg" alt="bilingual UI: Chinese | English">
</p>

**中文** · [English](README.md)

**Quilla QBOOT** 板卡的串口升级工具。选择串口、选择 `.bin`、点击开始即可完成升级；
命令行入口与图形界面共用同一套引擎，可用于产线自动化与 CI。

协议就是 QBOOT 本身已经在说的一套（见 [docs/protocol.md](docs/protocol.md)，
[中文版](docs/protocol.zh-CN.md)）；本项目补齐的是它外面缺失的那层窗口。它由
[Quilla](https://github.com/JiChiRen/Quilla) 代码树中的 `tools/quilla_host_updater.py`
重新实现并扩展而来，增加了图形界面、可协作取消的流程，以及在开始写 Flash 之前就能
拦下注定失败升级的预检查。

```
+----------------------+        +---------+        +------------------+
|  图形界面 (Tk) / CLI  |  UART  |  QBOOT  |  擦写   |  APP 区           |
|  核心: protocol +     | <----> |  QIAP   | -----> |  0x08007000..    |
|  session + 签名       |        |         |        |                  |
+----------------------+        +---------+        +------------------+
```

## 功能特点

- **零配置** —— 仅需 Python 3.8+ 与唯一依赖 `pyserial`。不依赖 Qt、Node，也没有安装程序。
- **不关心板卡当前状态** —— 正在运行固件、停在 QBOOT shell、或上次升级被中断留下残留状态，
  工具都能识别并处理。
- **签名可选且显式** —— 不提供私钥就不发 `SIGN` 帧，界面会明确说明，而不是等 40 秒后
  抛一个 `NAK 0x08`。若设备确实已烧录公钥，工具会在 `END` 之后立即停止并指明缺少私钥，
  不会空等启动戳窗口。
- **预检查** —— 在写入任何数据之前，直接从 `.bin` 读出镜像大小、SHA-256 与防回滚安全版本。
- **如实反映进度** —— 长时间静默的阶段会被明确标注。`SIGN` 阶段设备在片内验签、链路没有
  任何输出，界面会点名该阶段并提示「请勿断电」，而不是看起来像卡死。
- **可协作取消** —— 在当前帧结束后停止，板卡保持可恢复状态（QIAP 标志保留，重新运行即可继续）。
- **重启之前即判定完成** —— QIAP 先提交再回 ACK，因此 CHECK、SEALED、SECURE 三种构建都依据 QBOOT 侧的证据宣布完成；完成结论既不依赖启动戳，也不依赖 APP 从哪个串口打印。
- **记住上次配置** —— 固件路径、私钥路径、串口与波特率在重启后仍然保留，第二次升级只需一次点击。
- **中英双语界面** —— 可在顶栏运行时切换，也可按系统语言自动选择。命令行沿用同一设置，
  并支持 `--lang` 覆盖。

## 配置项

操作者偏好保存在 `~/.quilla_updater/config.json`（位于仓库之外 —— 它属于运行工具的这台
机器，不属于项目源码）：

| 键 | 含义 |
|---|---|
| `fw_path` | 上次使用的固件 `.bin` |
| `key_path` | 上次使用的私钥 |
| `use_key` | 是否发送 `SIGN` 帧 |
| `port` / `baud` | 上次使用的串口与波特率 |
| `lang` | `auto` / `zh` / `en` |
| `last_dir` / `key_dir` | 文件对话框上次所在的目录 |

该文件按「尽力而为」处理：若用户主目录不可写，工具仍可正常运行，只是不会记住上次的选择。

语言默认为 `auto`，在中文系统上解析为中文，其余环境为英文。可在顶栏显式指定以覆盖自动
判断；该选择会被持久化，并对命令行同样生效。

## 快速开始

### 预编译可执行文件（Windows，无需安装 Python）

从 [Releases](https://github.com/JiChiRen/QuillaUpdater/releases) 下载最新的
`QuillaUpdater.exe` 直接运行。它是单个文件，已内置解释器、`pyserial` 与 Tk；
不安装任何东西，也不会在 `%USERPROFILE%\.quilla_updater\` 之外写入文件。

同一发布页的 `quflash.exe` 为控制台版本，适用于产线或无法点击按钮的 CI 环节。

可执行文件未做代码签名，首次运行会被 SmartScreen 拦截提示。在生产机台使用前，
请先核对发布页给出的 SHA-256。

### 从源码启动图形界面（Windows）

```bat
run.bat
```

首次运行会自动安装缺失的 `pyserial`，随后打开窗口。

### 图形界面（Linux / macOS）

```bash
./run.sh
# Debian/Ubuntu 若缺少 tkinter：
#   sudo apt install python3-tk
```

### 命令行

```bash
pip install pyserial

python -m quilla_updater --list-ports
python -m quilla_updater COM7 firmware.bin                     # 不签名
python -m quilla_updater COM7 firmware.bin -b 115200 \
       --key keys/private.hex                                  # 签名
python -m quilla_updater COM7 --probe                          # 板卡当前处于什么状态
python -m quilla_updater --self-test                           # 离线自检，无需硬件
python -m quilla_updater --audit-i18n                          # 检查翻译表完整性
python -m quilla_updater --lang en COM7 firmware.bin            # 强制英文输出
```

执行 `pip install .` 之后，上述命令同样可以写作 `quflash`。

### 语言

命令行沿用图形界面中选择的语言，也可按次覆盖：

```bash
python -m quilla_updater --lang zh COM7 firmware.bin
python -m quilla_updater --lang en COM7 firmware.bin
```

`--help` 也会按指定语言渲染，因此解析器是在语言确定之后才构建的。

### 串口打不开

三种不同成因对应三种不同处理方式。工具会先分类再打印对应的处置步骤；下表供你在
错误还没出现在眼前时查阅：

| 现象 | 成因 | 处理 |
|---|---|---|
| `Access is denied` / `PermissionError(5)` | 其他程序独占该串口 | 关闭串口助手 / PuTTY / 仍在运行的旧版升级工具；结束 Keil 调试会话 |
| `Cannot configure port ... PermissionError(13, ..., 31)` | Windows `ERROR_GEN_FAILURE`。端口存在、设备树状态显示正常，但 `SetCommState` 被拒绝 | 见下文 —— 这一条的成因几乎从不像是它表现出来的样子 |
| `could not find` / `FileNotFoundError(2)` | 端口号已变化，或线缆已断开 | 重新插拔，点击 **刷新** 后重选 |

`ERROR_GEN_FAILURE` 值得单独展开，因为 Windows 侧所有诊断都显示设备正常：

- **WCH-Link / J-Link / CMSIS-DAP 这类调试探针，把调试接口与 CDC 串口复用在同一路 USB 上。**
  只要 Keil 处于调试会话中（或刚下载完、尚未断开），COM 口依然列在设备列表里、状态依旧正常，
  但任何配置尝试都会被拒绝。执行 `Debug -> Stop` 或退出 Keil，端口随即恢复，无需重新插拔。
- 若没有调试器在运行，则是 CDC 状态机卡住。拔下探针等待 3 秒再插回；同一 USB 口连续失败
  两次时，换一个口。
- 也可以在不碰线缆的情况下软复位，需在**管理员**权限的终端中执行：

  ```powershell
  $d = Get-PnpDevice -Class Ports | Where-Object FriendlyName -like '*COM7*'
  Disable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false
  Start-Sleep 2
  Enable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false
  ```

工具对 `not_ready` 类打开失败会重试两次（0.15 秒、0.5 秒）后才放弃，因为刚退出调试模式的
探针常常第一次 `SetCommState` 失败、随后即恢复正常。对 `busy` 不重试 —— 那一类不会自行恢复。

需要注意：设备管理器报告端口状态正常，只能证明驱动已加载，与端口能否被配置无关；
而本次故障恰恰就落在这一空隙里。

### 密钥

**图形界面**：**密钥工具**（Key tool）标签页 —— 第二个标签页，不是升级页 —— 可生成密钥对，
或从已有的 `private.hex` 导出公钥。请用导出功能核对本地私钥与设备内已烧录的公钥是否配对：
`SIGN` 阶段的 `NAK 0x08` 几乎都是此处不匹配，而通过这种方式发现问题要付出一次完整传输的代价。

该标签页从不显示私钥种子，只显示路径、公钥与编译宏，因此可以安全截图。

**命令行**：

```bash
python tools/keygen.py keygen --dir keys
python tools/keygen.py pubkey --key keys/private.hex
```

会写出 `keys/private.hex`（32 字节种子，**须保密**）与 `keys/public.hex`，并打印需要编译进
QBOOT 的宏：

```
-DQUILLA_SECURE_BOOT_PUBKEY={0x..,0x..,...}
```

一旦烧录了公钥，QBOOT 会拒绝任何不带有效 `SIGN` 帧的镜像。`keys/` 被列入 `.gitignore`
正是出于这个原因。

## 成功如何判定

结论在**重启之前**就已得出，依据是 QBOOT 侧的证据。QIAP 在 `commit_app()`
（`app_page_commit()` → `flag=APP1` → `done=1`）**之后**才发送完成 ACK，因此该 ACK
是完成码，而不只是「帧已到达」。三种 QBOOT 构建都在 `qboot_qiap_run()` 复位之前完成提交：

| 构建 | 启动模式 | 提交点 | 完成证据 |
|---|---|---|---|
| `QBOOT_CHECK` | CHECK，无公钥 | `END` 内 | `ACK 0x83` + `[QIAP] flash complete. Rebooting into APP...` |
| `QBOOT_SEALED` | SEALED，有公钥 | `SIGN` 之后 | `ACK 0x84`（`ACK_SIGN`） |
| `QBOOT_SEC` | SECURE，有公钥 | `SIGN` 之后 | `ACK 0x84`（`ACK_SIGN`） |

SEALED 与 SEC 的差别**只在复位之后**：SEALED 比对封印约 0.6 秒，SECURE 每次上电都跑
一遍 Ed25519（约 20 秒）。若把新 APP 的 `[QAPP] <name> V<ver>` 启动戳当作判据，SECURE
构建就要多等 20 秒，而 APP 从另一个串口打印时更会直接误判失败。`run()` 在拿到提交证据时
即宣布完成，不等待重启。

单独的 `ACK 0x83` **不是**完成码：带公钥的构建在 `END` 只确认、不提交，仍要等 `SIGN`。
主机靠复位前公告区分这两种情况 —— 该公告只在 `done=1` 之后打印。当前文案
（`[QIAP] flash complete...`）与旧版（`[QIAP] success...`）都能识别，因此本工具对两种
QBOOT 版本都可用；`tools/verify_fixes.py` 会在 Quilla 源码树存在时，把这两个标记与固件
源码逐一核对。

`[QAPP]` 启动戳是**可选的后置确认**：`run()` 对随完成码一同到达的字节做 0.5 秒检查
（仍与 `FirmwareImage.expected_stamp` 比对，避免把旧固件残留 banner 当成新镜像），
随后即返回。该窗口短于任何一种启动路径，不会等待重启。

固件的提交规则带来两个推论，而这两点在本工具中此前都是错的：

**END 有可能直接结束整个流程。** 在 `QBOOT_CHECK` 上，END 处理函数即完成提交，QBOOT 打印
`[QIAP] flash complete. Rebooting into APP...` 并复位。工具过去在这种情况下仍照常发送 `SIGN`，为 APP shell
根本不可能产生的 ACK 空等 `SIGN_TIMEOUT`（90 秒），最后在一块已经在运行新固件的板卡上报告
升级失败。现在 `end()` 会监听提交公告，一旦收到就跳过 `SIGN`。

**banner 必须能在帧解析中存活。** 提交公告与启动戳走的是与 ACK 帧同一条串口，而且恰好
在主机等待 ACK 期间到达。旧的接收实现每次调用都新建一个临时解析器，并丢弃所有不属于帧的
字节，于是「正在等待的那个答案」被「等待」这个动作本身销毁了。现在的接收端保持一个常驻
解析器加一份有界原始日志；日志中已存在的标记会在任何读取之前先行检查，因此同一个 USB
数据包里的 ACK 与 banner 都能被看到。

关于帧长：升级全程跑在 QBOOT 中，因此尺寸约束取决于它的接收链路 —— 1024 字节 CIRCULAR
DMA 环，其后是 512 字节桥接环，加上 `PAGE_SIZE + 8` 的负载缓冲。桥接环是字节流缓冲而非
帧缓冲，但容量按容纳一整帧 270 B 设计，因此一帧会原子地进入；每轮循环都会被弹空，
因此其占用量取决于两轮之间的积压，与帧长无关。

单个 DATA 帧承载完整的一页 256 字节（负载 264 B，线上 270 B），恰好等于
`QUILLA_QIAP_MAX_PAYLOAD` —— 设备会丢弃任何 LEN 超过该值的帧，所以 256 是上限而非可调参数。
按页对齐分块意味着每页只需一次擦除，而不是每六帧一次。按算式估计，115200 下约 4–4.5 KiB/s；
实测 15.3 KiB 镜像约 2 秒传完（约 7.7 KiB/s），说明该估计偏保守。旧文档中「64 字节 NORMAL
DMA」的限制描述的是已不存在的固件版本。

若复位导致端口掉线（WCH-Link、J-Link 这类复合调试探针），工具把它记为**弱证据**：复位
确实只发生在 `done=1` 之后，但拔线与复位的表现完全相同，因此日志会明确标注并提示复核板卡。
这是唯一一条不依赖 QBOOT 侧完成码的路径。若端口仍然活着，却既没有完成 ACK、没有提交公告、
也没有启动戳，则判定为失败。

## 本仓库有意不包含的内容

- **不含任何私钥**，连示例也不提供。任何提交到仓库的私钥，都会让读到它的人签出你的设备
  愿意接受的镜像。
- **不含固件镜像**。`.bin` 由你自行编译产生。
- **除协议本身外，不含设备相关常量**。`APP_END` 在运行时向板卡查询，从不臆测 —— 曾经写死的
  PY32F040xB 上限，就把完全合法的 GD32 镜像误拒过。

## 目录结构

```
quilla_updater/
  protocol.py   帧编解码、CRC16、常量 —— 与固件保持一致
  session.py    状态机: 探测 -> ENTER -> DATA* -> END -> [SIGN] -> 启动
  image.py      .bin 加载、SHA-256、.quilla_secver、期望启动戳
  ed25519.py    RFC 8032 签名，仅用标准库
  ports.py      串口枚举，含 USB 桥接芯片识别
  config.py     操作者偏好持久化（~/.quilla_updater/config.json）
  i18n.py       双语文案表与系统语言检测
  cli.py        无界面入口
  gui.py        Tk 前端
tools/keygen.py          密钥生成
tools/verify_fixes.py    针对配置 / 提交与启动戳 / 双语的回归测试
tools/build_exe.py       用 PyInstaller 生成两个独立可执行文件
docs/protocol.md         线上格式、时序约束、掉电行为
docs/protocol.zh-CN.md   上述文档的中文版
```

分层是严格的：`protocol.py` 不知道串口的存在，`session.py` 不知道 Tk 的存在，图形界面
不知道帧格式。界面选用 Tk 是因为它随 Python 一同分发；若要换成 Qt，只需重写 `gui.py`。

## 测试

```bash
python -m quilla_updater.cli --self-test    # 帧编解码、CRC、Ed25519 测试向量
python -m quilla_updater.cli --audit-i18n   # 缺失译文、键名冲突
python tools/verify_fixes.py                # 配置持久化、SIGN 语义、界面冒烟测试
```

`tools/verify_fixes.py` 不需要硬件：它用一个模拟串口驱动整个会话，并以无头方式构建 Tk 窗口。
模拟设备复现了两条提交路径（END 提交与 SIGN 提交），因此「已经升级成功却还在等待」这一
回归是被端到端覆盖的，而不只是逐单元覆盖。

## 验证情况

- CRC16 与帧编码：与 `os/lib/crc16.c` / `quilla_host_updater.py` 逐字节一致，已在随机负载上核对。
- Ed25519：RFC 8032 第 7.1 节测试向量；并对真实的 16.5 KiB QAPP 镜像，与
  `tools/quilla_ed25519_sign.py` 产出的签名逐字节一致。
- `.quilla_secver`：能从真实的 PY32F040xB 构建产物中，于偏移 `0x400` 处解析出
  `magic="QAV1"` 与版本号。
- 硬件端到端：PY32F040xB，经 WCH-Link 的 CDC 串口，115200，对 15688 字节的 QAPP 做签名升级。
  CHECK、SEALED、SECURE 三种启动构建各完成一次完整升级，三次均通过；复位后观察到
  `[QAPP] Project V0.10.0001`。另有一次在未提供公钥的板卡上运行，覆盖了过去会空等 90 秒的
  `END` 阶段提交路径。
- 可配置的 APP→QBOOT 复位指令：默认文本指令 `swqboot` 与裸十六进制指令均已验证。
  在一块运行"不含 Quilla shell 的 APP"的板子上，发送 `06 F0 5A 51 42 4F 54 80`
  （内嵌了字面量 "QBOT"）使 MCU 复位进入 QBOOT shell，随后完整签名升级成功完成。
  十六进制路径刻意按原样发送、不追加换行，该次运行已证实：复位后的 `part` 回复
  干净无残留（`part\r\nqboot\r\n> `）。

仍未验证的部分：PY32F040xB 之外的 MCU（其 APP 区上限取决于各自的 `pinfo` 回复）；
复位导致端口掉线后的重开路径 —— 该路径需要一块复位时会真正摘除 COM 口的探针才能触发；
设备已烧录公钥而主机未给 `--key` 的错误路径 —— 需要专门构造一次不带私钥的运行；
以及完成 ACK 丢失、仅凭复位观察到完成的弱证据路径。

## 编译独立可执行文件

```bash
pip install -e .[build]
python tools/build_exe.py            # 两个程序，输出到 dist/
python tools/build_exe.py --gui      # 仅图形界面
python tools/build_exe.py --cli      # 仅命令行
python tools/build_exe.py --icon X.ico  # 覆盖内置的 Quilla logo
```

两个可执行文件默认都嵌入 Quilla logo（`quilla.ico`）；用 `--icon` 可换成别的。
图形界面还会把该徽标作为窗口图标显示。

产出 `dist/QuillaUpdater.exe`（窗口程序，已内置 Tk）与 `dist/quflash.exe`（控制台）。
两者都是 `--onefile`：无需目标机安装 Python、无需 `pip install`、无需随附 DLL。
`dist/` 与 `build/` 均已列入 git 忽略，因此发布物是构建产物，而不是提交进仓库的二进制。

有两处细节由构建流程显式处理，因为打包后的运行环境与源码运行环境的失效方式不同：

- `pyserial` 会延迟加载其平台后端，因此把 `serial.serialwin32`、`serial.serialposix` 与
  `serial.tools.list_ports` 一并声明为隐藏导入。
- 打包后的 Windows 控制台会沿用系统 ANSI 代码页（中文系统为 cp936），而本程序输出 UTF-8。
  `cli.main()` 会把控制台切到代码页 65001 并固定流编码；否则在 Windows Terminal、VS Code
  中，所有中文日志与串口描述都会显示为乱码。

发布时请同时给出每个可执行文件的 SHA-256；二进制未做签名。

## 许可

BSD-3-Clause，版权方与条款和本工具所服务的 Quilla 项目一致。
每个源文件同样带有许可证头，单个文件被取出到其他项目时条款随之保留。
`quilla_updater/ed25519.py` 移植自 Quilla 自研的 `tools/quilla_ed25519_sign.py`，
版权所有 (c) 2026 JiChiRen Info. Tech.，采用同一许可。

本仓库不含 contiki-NG 派生代码。Quilla 代码树中包含此类代码，
那些文件保留其原始许可（瑞典计算机科学研究所，SICS）。
本项目的许可证头并不派生自它们，也不复述其条款。
