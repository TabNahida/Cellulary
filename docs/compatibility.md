# 型号、资料和命令依据

## 已下载的官方文件

| 文件 | 版本 | 原始文件 | 已核对内容 |
| --- | --- | --- | --- |
| EC200A 系列 LTE Standard 模块产品规格书 | V1.6 | `vendor/EC200A-specification.pdf` | EU 型号、VoLTE、模拟/PCM 音频接口、Windows RNDIS/Linux ECM |
| EC801E-CN 产品规格书 | V1.0 | `vendor/EC801E-specification.pdf` | Windows 8.1/10/11 RNDIS；部分协议带开发中脚注，不能跨固件假设可用 |

文件来自 [EC200A 官方产品页](https://www.quectel.com.cn/product/ec200a-series) 和 [EC801E 官方产品页](https://www.quectel.com.cn/product/lte-ec801e-cn)。下载源 URL、文件 SHA-256、版本和获取日期见 `vendor-sources.json`。规格书是功能概览，不能替代 AT 命令手册。

官网目录已找到 LTE Standard(A) AT 手册 V1.4、LTE Standard(E) AT 手册 V1.3，以及两款的硬件、USB、PPP 和音频资料。需要会员下载的手册尚未落盘的条目在清单中明确标为 `unavailable`，不把它们当作已阅读的指令依据。原始厂商资料不纳入 Git。

## 命令支持依据

- 身份、SIM、注册、信号、短信 PDU 与 PDP 管理使用 3GPP TS 27.007 / 27.005 及 TS 23.040 / 23.038 的标准命令与编码；具体实现以真实模块响应和回归测试校验。
- EC801E USB 拨号参考移远官方论坛[技术支持回复 5976](https://forumschinese.quectel.com/t/topic/5976)，支持员给出的请求为 `AT+QNETDEVCTL=1,1,1`，停止为 `AT+QNETDEVCTL=0,1,0`。当前库只将该路径用于 EC801E，写操作前查询命令能力。USB 连接状态不等于主机 Internet 可达。
- 官方论坛[10409](https://forumschinese.quectel.com/t/topic/10409) 不应被解读为 EC801E 已支持 MBIM/QMI。EC200A 本机实际以 Windows 移动宽带接口出现，能力来自本机枚举证据，而非对其他型号的推断。
- 官方论坛[4637](https://forumschinese.quectel.com/t/topic/4637) 提醒 PPP 支持与固件有关。该贴涉及数据拨号，不能用它证明语音呼叫可用。
- 本机 EC801E 的 `AT+CLCC` 返回 ERROR；EC200A 同指令正常。首次发布不承诺 EC801E 的电话功能或浏览器语音。

## 后续模块适配

型号选择由厂商、`CGMM` 和 profile 决定；USB VID/PID 仅用来找候选 AT 接口。当前只声明 EC200A 和 EC801E 两个 profile。新增 5G 型号时应分别适配 USB 端口布局、注册技术字段、USB 数据控制、语音能力和固件差异，并使用对应官方资料与真实设备验证。
