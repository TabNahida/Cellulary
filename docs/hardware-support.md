# 首批 Quectel 模块支持与资料依据

核对日期：2026-09-16。适配对象为 PC 上运行的 Python 工具库，通过模块标准 AT 固件和 USB 驱动管理设备；不要求在模块内运行 QuecPython。原厂文件保存在 `docs/vendor/`，不随 Python 包再分发。可审计的 URL、版本和 SHA-256 见 [vendor-sources.json](vendor-sources.json)。

## 型号与网络

| 项目 | EC200A-EU / EC200A-EUV1 实物 | EC801E-CN |
|---|---|---|
| 无线制式 | EC200A-EU 规格为 LTE Cat 4，下行 150 / 上行 50 Mbps | 工业级规格为 LTE Cat 1，下行 10 / 上行 5 Mbps |
| LTE-FDD 频段 | B1/3/5/7/8/20/28 | B1/3/5/8 |
| LTE-TDD 频段 | B38/40/41 | B34/38/39/40/41 |
| Windows 官方规格列明的 USB 网络 | RNDIS；USB 转串口 | RNDIS；USB 转串口 |
| Linux 官方规格列明的 USB 网络 | RNDIS、ECM | RNDIS、ECM；V1.0 部分 Linux 能力带开发中星号 |
| 电话硬件 | EC200A 系列规格 V1.6 第 2 页列数字语音、VoLTE、PCM、模拟麦克风与听筒 | EC801E 工业级规格 V1.0 未列语音/VoLTE/音频接口，不能仅凭同品牌或 ATD 存在承诺通话 |

来源为 EC200A 产品规格书 V1.6 第 1-3 页及 EC801E-CN 产品规格书 V1.0 第 1-2 页。两份 PDF 已下载，相关驱动表已渲染核对。EC801E-CN 文档明确仅适用于工业级；官网另列消费级硬件手册，必须以具体料号和固件确认功能。两类设备都是 4G，未来 5G 适配需另加驱动配置。

本文后续手册页码均为 PDF 页脚印刷页码（封面另计；例如 E 手册印刷第 137 页是 PDF 第 138 页）。

当前实物识别应优先用 `ATI`、`AT+CGMM`、`AT+CGMR`（或 `AT+QGMR`），完整保留固件版本。EC200A 系列可只返回 `EC200A`，地区及 V1 修订版须结合固件前缀识别。主任务的真机只读检查得到 `EC200AEUV1HAR02A08M16`，因此不能把这台设备仅按较早 EC200A-EU 文档的全部细节固定处理。

## USB 上网与主机网络

官方规格的功能表不是所有后续固件的穷尽列表。2026-09-16 主任务现场检查中，EC200A `AT+QCFG="usbnet"` 返回 `2`，Windows `netsh mbn show interfaces` 实际枚举到该模块的移动宽带接口，状态 Connected。由此本机应使用可观察到的 MBN/MBIM 接口管理；不能因为旧规格只列 RNDIS 就禁用这一真实路径。EC801E 实物 `usbnet` 返回 `3`，与 E AT 手册 V1.3 第 51 页的 `3=RNDIS` 对应；同页定义 `1=ECM`。A AT 手册 V1.4 第 54 页也列这两个取值。配置 USB 模式会自动保存且需重启生效，程序不应在发现设备时修改。E 手册第 40 页对 EC801E 的 QCFG 子命令清单偏保守，而当前实机可以查询 usbnet；具体固件的只读返回比从旧清单推断更可靠。

EC801E 的官方论坛支持回复明确表示不支持 MBIM/QMI（2025-10-10，https://forumschinese.quectel.com/t/topic/10409，post 2）。该结论只用于 EC801E，不外推至 EC200A。官方规格为 EC801E 的 Windows 网络列出 RNDIS，为 Linux 列出 ECM。

正式 AT 手册定义了 USB 数据拨号：E V1.3 第 137-138 页、A V1.4 第 175-176 页。完整格式为 `AT+QNETDEVCTL=<type>,<cid>[,<URC_en>]`，最大命令响应时间为 2 秒。具体参数如下。

| 参数或操作 | 定义 |
|---|---|
| `<type>` | `0` 断开，`1` 仅连接一次，`3` 自动连接；`3` 会自动保存配置，扫描中不要启用 |
| `<cid>` | PDP 上下文编号，手册范围为 1-15；仍应查询当前固件支持的范围 |
| `<URC_en>` | `0` 关闭或 `1` 开启 `+QNETDEVSTATUS: <status>` 状态通知 |
| `AT+QNETDEVCTL=?` | 返回当前固件支持的 type、cid、URC_en 列表 |
| `AT+QNETDEVCTL?` | 返回 `+QNETDEVCTL: <type>,<cid>,<URC_en>,<state>`，state 为 0 未连接或 1 已连接 |
| `AT+QNETDEVCTL=1,1,1` | 对 PDP 1 连接一次，并开启状态通知；手册有此完整示例 |
| `AT+QNETDEVCTL=0,1,0` | 断开 PDP 1 的 USB 网卡连接，关闭状态通知；官方论坛 5976 post 4 亦给出此命令 |
| `+QNETDEVSTATUS: 0/1` | 网卡断开/连接成功的异步通知，不是主机 DHCP 与互联网可达性保证 |

官方论坛 https://forumschinese.quectel.com/t/topic/5976 的 post 6 同样给出 `AT+CGDCONT=1,"IP","<APN>"` 和 `AT+QNETDEVCTL=1,1,1` 的操作示例；post 5 报告未激活状态下停止可能返回 ERROR。参数使用 ASCII 引号，并校验 CID/APN 输入。模块地址可通过 `AT+CGPADDR=1` 查询。

`QNETDEVSTATUS` 在正式手册中是 URC；同帖固件日志的 `AT+QNETDEVSTATUS=?` 返回 ERROR。状态查询应使用 `QNETDEVCTL?`。手册例子把返回参数范围的命令写作 `QNETDEVCTL?`，但同一节正式语法表明确测试命令是 `QNETDEVCTL=?`，实现以语法表为准。

USB 描述符 V1.3 第 9 页列 EC801E 等系列共用 VID/PID 为 `2C7C:0903`，因此 PID 不是唯一型号。该手册说明 Windows 的 ECM 需安装对应 ECM 驱动，RNDIS 可自动读取描述符。本机采用已枚举的 RNDIS 模式即可。

模块 PDP/USB 拨号成功、Windows 网卡获得地址、默认路由、DNS 和互联网可达性是不同状态。帖子 5976 正是模块有 PDP 地址但主机 DHCP 失败的例子。首次适配不应在扫描中改变 APN、USB 模式、网络路由或重启设备；这些操作应为用户明确发起的管理动作。

PPP 支持随固件变化：EC801E 规格 V1.0 标 `PPP*`（开发中），2024-07 官方论坛 4637 提到部分固件因 flash 大小裁剪 PPP，2025-10 论坛 10409 又表示支持 PPP。保留能力探测和失败反馈，不为所有 EC801E 硬编码保证 PPP。

## 短信、通话及验证边界

A AT 手册 V1.4 的短信章节定义了 `CMGF`、`CPMS`、`CMGL`、`CMGR`、`CMGS`、`CMGD` 和 `CNMI`。Unicode、长短信分段、PDU 编解码、URC 混入响应，以及空卡/漫游/无网络应分别处理。

**EC801E-CN 不能默认标为支持短信。** E AT 手册 V1.3（2025-07-22）第 95 页明确写明 EC600Z-CN、EC800Z-CN 和 EC801E-CN 暂不支持短消息相关命令。能力界面应区分“型号/固件不支持”“SIM 未就绪”和“网络未注册”。若后续固件提供短信命令，可通过只读能力探测启用，不能仅因模块已联网就启用短信发送。

E AT 手册第 28 页说明 EC801E-CN 的 `AT+CMEE` 只支持 `0` 和 `1`，初始化宜使用 `CMEE=1`；该手册第 29 页还指出 EC801E 不支持 `CSCS`，第 129 页指出不支持 `CGDATA`。

电话控制与音频链路分开：`ATD<number>;`、`ATA`、`ATH`、`CLCC` 只涉及呼叫控制。即使获得呼叫连接状态，也不表示浏览器麦克风和扬声器已接入模块。EC200A 需要具体载板音频电路或固件支持的 UAC、PCM 链路，以及运营商语音/VoLTE 配置；已下载 A 音频 V1.3、EC200x/EC600N UAC V1.1 与 A IMS XML V1.1 供进一步适配。

E 音频指导 V1.0（2025-12-29）第 6 页的适用模块不含 EC801E，只列 EC600E/EC800E/EC600Z/EC800Z/EG800Z，并限定 4 MB Flash。因此这份同系列名称的音频手册不能作为 EC801E 电话音频支持依据。EC801E 界面应保持未验证/不可用状态，直到具体固件及音频硬件得到证实。

主任务只读检查识别到六台设备及其中两张 SIM：EC801E 的一台返回 `CEREG=5`（漫游注册），EC200A 返回 `CEREG=1`（本地注册）。这里不记录 IMEI、ICCID、IMSI 或电话号码。发送短信、拨出电话和切换实际连接没有作为只读扫描的一部分执行。

## 官方资料取得状态

已成功从移远中国官网保存 15 份 PDF：2 份公开产品规格书及登录后取得的 13 份正式技术文档。技术文档包含 A AT V1.4、E AT V1.3、A USB 描述符 V1.4、EC800Z/EC801E/EG800Z/EG901E/EG915Z USB 描述符 V1.3、EC200A 硬件 V1.3、EC801E 工业级硬件 V1.3、EC801E 消费级硬件 V1.2、两系列 PPP 指导、A/E 音频指导、EC200x/EC600N UAC 指导和 A IMS XML 指导。官网账号凭证和会话 Cookie 仅在内存中用于正常认证，未写入项目文件。

两份产品规格的驱动表，以及 E AT 的 USB 模式、短信限制和 USB 拨号定义已渲染人工核对。其余文档保留原文件与全文提取文本供后续逐项适配；不把“已下载”当作所有内容均经过验证。

所有正式 PDF 的原下载详情 URL、版本、文档日期及 SHA-256 已登记在 [vendor-sources.json](vendor-sources.json)。资料版权属于移远，原件、提取文本及打包 ZIP 均应留在 gitignore 的 `docs/vendor/` 内。驱动下载条目单独保留 unavailable 状态，现有用户已安装驱动，本次没有重新安装或替换驱动。
