# Cellulary

本地运行的蜂窝网络 Python 工具库、命令行和中文 Web 管理台。第一批适配移远 **EC200A-EU** 和 **EC801E-CN**，通过 USB AT 串口控制。Python ≥ 3.11，当前主机联网适配器面向 Windows。

## 开始使用

```powershell
uv sync --extra dev
uv run cellulary web
```

打开 **http://127.0.0.1:8765**。安装过的项目也可以直接运行：

```powershell
.venv\Scripts\python.exe -m cellulary web
```

也可使用标准 pip：`python -m pip install -e ".[dev]"`，随后运行 `cellulary web`。

管理台提供设备总览、收发短信、数据连接、通话控制与事件记录。自动扫描仅探测移远的 AT 接口，不探测 DIAG、Modem 或其他厂商串口。不同模块可并行工作，同一串口的命令顺序执行。服务启动后每 20 秒更新设备状态，网页每 8 秒读取缓存；短信收件箱通过读取按钮刷新。

Web 服务独占模块 AT 端口；使用 CLI 或另外的 Python 进程操作同一模块前请先停止 Web 服务（Ctrl+C）。

## Python 工具库

```python
from cellulary import Modem, discover_ports

for port in discover_ports():
    print(port.port, port.description)

with Modem("COM23") as modem:
    print(modem.identify())
    print(modem.status())
    messages = modem.list_sms()  # GSM 7-bit / UCS2 解码，默认合并长短信
    print(messages)
    print(modem.data_status())
    print(modem.list_calls())
```

需要实际发送、拨号或配置时，显式调用：

```python
with Modem("COM23") as modem:
    # 替换为实际收件人；这些调用会操作 SIM 业务。
    result = modem.send_sms("+441234567890", "来自 Cellulary 的消息")
    modem.configure_apn("internet", context_id=1, pdp_type="IPV4V6")
    modem.activate_data(context_id=1)
    # modem.deactivate_data(context_id=1)
    # modem.dial("+441234567890")
    # modem.answer()
    # modem.hangup()
```

短信发送返回的是**模块已提交**结果，不是对方收到的证明。长短信可能按多条计费。`SMSDeliveryError` 携带已经提交的 `references` 和 `total_segments`；遇到超时或部分提交不要自动重发。读取短信可能由固件将未读标记改为已读；不会删除短信。可调用 `enable_sms_notifications()` 配置 `+CMTI` 通知，并用 `drain_urcs()` 获取异步事件。

## 命令行

```powershell
cellulary ports
cellulary scan
cellulary status COM23
cellulary sms COM23
cellulary sms COM23 --to +441234567890 --text "Hello"
cellulary data COM23 status
cellulary data COM23 configure --apn internet --cid 1
cellulary data COM23 activate --cid 1
cellulary usb-data COM11 status
cellulary usb-data COM11 connect --cid 1
cellulary usb-data COM11 disconnect --cid 1
cellulary call COM23 list
cellulary call COM23 dial +441234567890
cellulary call COM23 hangup
cellulary network
```

## 能力和边界

| 功能 | 当前实现 |
| --- | --- |
| 多模块识别 | AT 端口枚举、厂商/型号/固件/IMEI、SIM、信号、网络注册、热插拔重扫 |
| 短信 | PDU 收发、GSM 7-bit/UCS2、长短信分段与合并、部分失败报告 |
| 模块数据 | APN/PDP 类型配置、PDP 激活/停用、附着和上下文查询 |
| Windows 联网 | MBN 接口与已有配置文件发现、连接和断开，系统网卡状态查询 |
| EC801E USB 联网 | `QNETDEVCTL` RNDIS/ECM 拨号请求与状态读取，写操作前探测固件支持 |
| 通话 | `ATD` / `ATA` / `ATH` / `CLCC` 控制；实际语音能力由固件、SIM、VoLTE、音频硬件决定 |
| Web API | FastAPI `/docs`，本机同源会话令牌保护写操作 |
| 5G / 其他模块 | 预留 profile 扩展结构，尚未宣称适配或验证 |

**PDP 激活不等于电脑已经联网。** Windows MBN 使用已经存在的系统配置文件；EC801E 另外提供 USB 网卡拨号控制，要求已启用 RNDIS/ECM 功能，主机通过 DHCP 获得地址。USB 命令返回 OK 只表示已请求拨号，后续状态与主机地址/路由决定连接是否可用。程序不自动切换 USB 模式、刷新固件、重启模块或更改默认路由策略。EC200A 当前使用本机已经识别的 MBN 接口，不套用 EC801E 的 USB 拨号命令。

EC200A 规格书列出 VoLTE 与音频接口；本机 EC801E 固件的 `CLCC` 查询返回 ERROR，其语音能力不能视为已支持。网页提供呼叫控制，不传输电脑麦克风/扬声器音频。两个型号均是 4G 模块。

服务默认仅绑定 `127.0.0.1`，附带同源检查、Host 校验和写请求令牌；不应直接暴露到公网。无需配置或保存移远官网账号。官方原始资料位于本机 `docs/vendor/`，不进入版本控制；来源、版本与哈希记录见 [资料清单](docs/vendor-sources.json)，已取得资料与能力依据见 [兼容性说明](docs/compatibility.md)。

## 开发与验证

```powershell
uv run pytest -q
uv run ruff check src tests
uv build
```

测试使用可注入的串口替身，不发送真实短信、不发起真实呼叫、不改变主机网络。真实设备验收记录见 [硬件验证](docs/hardware-validation.md)。

代码按 `transport`（串口事务/URC）、`sms`（PDU）、`modem`（设备操作）、`discovery`（端口识别）、`manager`（设备生命周期）、`network`（主机网络）、`web`（API/静态管理台）划分。新增型号时先核对厂商资料、添加 profile 与接口识别规则，再补命令差异和设备测试；不能仅凭 VID/PID 就假设全部能力一致。

许可证：GPL-3.0-only；厂商文档版权归移远通信所有。
