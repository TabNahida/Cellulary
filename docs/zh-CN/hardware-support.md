# 硬件与命令依据

[文档目录](README.md) · [English](../hardware-support.md)

资料核对日期：2026-09-16；命令复核：2026-09-17。本项目在主机运行 Python，通过标准 AT 固件管理模块，不要求模块内部运行 QuecPython。原件保存在 `docs/vendor/`，[资料清单](../vendor-sources.json) 记录 URL、版本、发布日期和 SHA-256。

下文页码均指 **PDF 页脚印刷页码**。例如 E AT 手册第 137 页是 PDF 阅读器中的第 138 页。

## 型号区别

| 项目 | EC200A-EU | EC801E-CN |
| --- | --- | --- |
| LTE 类别 | Cat 4，最高下行 150 / 上行 50 Mbps | Cat 1，最高下行 10 / 上行 5 Mbps |
| LTE-FDD | B1/3/5/7/8/20/28 | B1/3/5/8 |
| LTE-TDD | B38/40/41 | B34/38/39/40/41 |
| 规格列出的 Windows 接口 | USB 串口、RNDIS | USB 串口、RNDIS |
| 规格列出的 Linux 接口 | USB 串口、RNDIS、ECM | USB 串口、RNDIS、ECM；V1.0 部分项目标记开发中 |
| 语音硬件 | 列出数字语音、VoLTE、PCM 与模拟麦克风/听筒 | 工业级 V1.0 规格未列语音、VoLTE 或音频接口 |
| GNSS | EU 栏没有 GNSS；CN 可选支持属于另一变体 | 已复核规格未记录 GNSS 支持 |

来源：EC200A 产品规格 V1.6 第 1-3 页、EC801E-CN 产品规格 V1.0 第 1-2 页。后者明确适用于工业级，资料库另有工业级与消费级硬件手册。这些都是 4G 模块，不能用于证明 5G 适配。

通过 `ATI`、`AT+CGMM`、`AT+CGMR`/`AT+QGMR` 联合识别。EC200A 可能只返回系列名称，地区及 V1 修订版还需结合固件与料号。真实设备结果单独保存在[硬件验证](hardware-validation.md)。

## USB 数据连接

E AT V1.3 第 51 页、A AT V1.4 第 54 页定义：无模式参数的 `AT+QCFG="usbnet"` 为查询，`1` 表示 ECM，`3` 表示 RNDIS。写入模式会保存配置并需要重启；设备发现阶段只查询。

E 手册第 40 页 EC801E QCFG 适用说明比后续固件实测更严格，旧表格不能穷尽新固件能力。EC200A 如果在 Windows 中实际枚举为移动宽带接口，应使用该接口，不能仅靠旧表推断协议。

[官方论坛 10409](https://forumschinese.quectel.com/t/topic/10409) 第 2 帖说明 EC801E 不支持 MBIM/QMI，该限制不能外推至 EC200A。EC801E USB 描述符 V1.3 第 9 页列共用 VID/PID `2C7C:0903`，不能单靠 USB ID 唯一识别型号；该手册还说明 Windows ECM 需要相应驱动。

E AT 第 137-138 页、A AT 第 175-176 页定义：

```text
AT+QNETDEVCTL=<type>,<cid>[,<URC_en>]
```

| 参数或操作 | 含义 |
| --- | --- |
| `type=0` | 断开 USB 网卡连接 |
| `type=1` | 仅连接一次 |
| `type=3` | 自动连接，配置会保存 |
| `cid` | PDP 上下文编号，文档范围 1-15；仍须查询固件实际支持值 |
| `URC_en=0/1` | 关闭/开启 `+QNETDEVSTATUS` 通知 |
| `AT+QNETDEVCTL=?` | 测试支持的参数范围 |
| `AT+QNETDEVCTL?` | 读取 `type,cid,URC_en,state`，state 为 0 断开或 1 连接 |
| `AT+QNETDEVCTL=1,1,1` | 对上下文 1 连接一次并开启通知 |
| `AT+QNETDEVCTL=0,1,0` | 断开上下文 1 并关闭通知 |
| `+QNETDEVSTATUS: 0/1` | 断开/已连接的异步通知 |

手册规定最大命令响应时间为两秒。`OK` 表示接受请求，实际结果仍需后续状态与主机网络检查。手册某个例子把返回参数范围的命令写成 `QNETDEVCTL?`，正式语法表则区分 `=?` 和 `?`；实现应以语法表为准。

[官方论坛 5976](https://forumschinese.quectel.com/t/topic/5976) 第 4、6 帖佐证连接/断开命令，也展示了模块有 PDP 地址但主机 DHCP 失败的情况。`QNETDEVSTATUS` 是通知，不应假定存在查询命令；帖子中的固件拒绝 `AT+QNETDEVSTATUS=?`。

APN/上下文配置、USB 拨号、主机 DHCP、DNS 和路由属于不同阶段。发现设备时不自动切换 USB 模式、重启、修改路由或启用持久化自动拨号。

PPP 随固件变化：EC801E V1.0 规格标记开发中，[论坛 4637](https://forumschinese.quectel.com/t/topic/4637) 描述不支持的固件，后续回复又提及支持。应检测实际能力。

## 短信：先看型号适用范围

E AT V1.3（2025-07-22）**第 95 页**明确表示 EC600Z-CN、EC800Z-CN 和 **EC801E-CN 暂不支持短信命令**。后续通用短信章节不覆盖这一型号限制。

第 96-97 页为适用固件定义 `CMGF=0` PDU、`CMGF=1` 文本。第 101-102 页规定 PDU 模式列出全部短信使用数字 **4**，文本模式则使用字符串 **"ALL"**。PDU 模式下发送 `CMGL="ALL"` 不符合协议。`CMGF` 被拒绝时，应返回不支持原因，不能继续操作后显示为空收件箱。

A AT V1.4 描述 `CMGF`、`CPMS`、`CMGL`、`CMGR`、`CMGS`、`CMGD` 和 `CNMI`。实现须处理 GSM 7-bit/UCS2、长短信、URC 和部分提交失败。读取可能改变未读标记，发送超时或部分提交后不应自动重发。

新固件可能晚于 E 手册。驱动采用保守默认值并检测实际能力，在不可用时保留命令结果与原因。未插 SIM 和固件不支持应分开处理。

## 本机号码

`AT+CNUM` 读取 SIM 中保存的本机号码：E AT V1.3 第 94 页、A AT V1.4 第 110 页。允许返回零条、一条或多条记录后接 `OK`。空结果表示 **未知**，不能用 IMSI/ICCID 拼造电话号码，也不代表网络注册失败。

A AT 第 112-114 页描述 `CPBR` 和 `CPBS`，`"ON"` 为 SIM 本机号码/MSISDN 列表，部分固件不支持。E 手册的电话本章节只有 CNUM。因此未来的 `CPBS="ON"` 回退必须可选，先检测能力、限制读取索引并恢复原存储选择；不能为查号码而写入 `CPBW`。没有回退时，CNUM 返回空仍是有效结果。

## 通话、音频与 GNSS

`ATD`、`ATA`、`ATH`、`CLCC` 的通话控制与音频传输分开。EC200A 需要适用语音固件、SIM 服务、运营商 VoLTE 支持和载板音频线路。已下载 A 音频 V1.3、UAC V1.1、IMS XML V1.1 可供后续集成；浏览器音频尚未实现。

E 音频 V1.0 第 6 页 **不含 EC801E**，只列 EC600E、EC800E、EC600Z、EC800Z 和 EG800Z，且限定 4 MB Flash 模块。同系列资料名称不能作为 EC801E 音频支持依据。

EC25 驱动实现 QGPS 系列 GNSS 查询与控制，区分不支持、接收器关闭与等待定位。本项目尚未验证真实 EC25，其协议实现不能变成对 EC200A-EU 或 EC801E 的 GNSS 承诺。

官方目录提供 [EC2x/EG2x/EG9x/EM05 GNSS 应用指导 V1.4](https://www.quectel.com.cn/download/quectel_ec2xeg2xeg9xem05%e7%b3%bb%e5%88%97_gnss_%e5%ba%94%e7%94%a8%e6%8c%87%e5%af%bc_v1-4)，可用于后续 EC25 核对。本次已确认目录条目，但未下载或审阅其 PDF 正文，不计入上述 15 份资料。

## 初始化差异

E AT V1.3 第 28 页限制 EC801E `CMEE` 只支持 `0`、`1`，应使用 `CMEE=1` 获取数字扩展错误。第 29 页排除 EC801E 的 `CSCS`，第 129 页排除 `CGDATA`。可选命令失败不应导致整个在线模块消失。

## 已下载资料

资料库包含两份公开产品规格与十三份登录后下载的官方 PDF：A/E AT、A/E USB 描述符、EC200A 硬件、EC801E 工业级/消费级硬件、A/E PPP、A/E 音频、EC200x/EC600N UAC、A IMS XML。关键规格表及 E 手册的 USB、短信限制与拨号定义已通过渲染页面核对；其余资料可供按需复核，下载不代表每项命令均已验证。

资料清单中的驱动包仍标记 unavailable，因为本次没有替换已安装驱动。PDF、提取文本和下载包均留在被 Git 忽略的 `docs/vendor/`；项目不保存或依赖官网密码、会话 Cookie。
