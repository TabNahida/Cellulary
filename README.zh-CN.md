<div align="center">

# Cellulary

**用一个 Python API 和本地管理台，连接你的蜂窝模块。**

短信 · 移动数据 · 通话控制 · SIM 信息 · GNSS

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue)](LICENSE)

[快速开始](#快速开始) · [硬件支持](#硬件支持) · [文档](docs/zh-CN/README.md) · [English](README.md)

</div>

Cellulary 将 USB 蜂窝模块接入统一工作空间：用 Python 工具库集成应用，用 CLI 编写脚本，用 Web 管理台处理日常操作。在自己的电脑上发现多个模块，查看 SIM 和网络状态、读取短信，并控制硬件支持的服务。

独立的厂商与型号驱动负责 AT 命令及固件差异。首批硬件目标为 **移远 EC200A-EU/EUV1** 和 **EC801E-CN**，同时提供 **EC25** 协议驱动及 GNSS 接口，等待真实硬件验证。

## 功能

| 能力 | Cellulary 提供的功能 |
| --- | --- |
| 多模块管理 | AT 端口发现、型号和固件识别、SIM 状态、信号与网络注册 |
| 短信 | 在支持的固件上收发 PDU 短信，处理 GSM 7-bit/UCS2、长短信及部分提交失败 |
| 移动数据 | APN/PDP 管理、EC200A/EC801E USB 网卡控制及现有 Windows 移动宽带配置 |
| 通话控制 | 在模块、固件及 SIM 支持语音时拨号、接听、挂断和查询通话 |
| SIM 信息 | 查询 SIM 中保存的本机号码；未保存号码时显示未知 |
| GNSS | 按驱动控制接收器与查询定位；EC25 提供协议支持，不假定 EC200A-EU/EC801E 具有 GNSS |
| 本地管理台 | 设备总览、业务操作、能力反馈与事件记录，由 FastAPI 提供接口 |

## 快速开始

安装 **Python 3.11 或更新版本**以及模块对应的 USB 驱动，然后连接模块。使用模块的 **AT 端口**；诊断与 Modem 端口各有其他用途。

```sh
git clone https://github.com/TabNahida/Cellulary.git
cd Cellulary
python -m pip install -e .
cellulary web
```

打开 **http://127.0.0.1:8765**。交互式 API 文档位于 **http://127.0.0.1:8765/docs**。

也可使用 [uv](https://docs.astral.sh/uv/)：运行 `uv sync --extra dev`，再运行 `uv run cellulary web`。

Web 服务独占它打开的 AT 端口。用 CLI 或另一个 Python 进程操作同一端口前，先按 **Ctrl+C** 停止 Web 服务。[故障排查 →](docs/zh-CN/troubleshooting.md)

管理页面默认英文，可切换中文，以及跟随系统、浅色和深色主题。顶部选择一次模块，即可在总览、短信、网络、通话和 GNSS 之间切换；网络页会匹配对应的主机网卡并提示重复 MAC 地址。

## Python 用法

```python
from cellulary import Modem, discover_ports

ports = discover_ports()
for port in ports:
    print(port.port, port.description)

if ports:
    with Modem(ports[0].port) as modem:
        print(modem.identify())
        print(modem.status())
        print(modem.data_status())
        print(modem.subscriber_numbers())
        print(modem.gnss_status())
```

执行操作前先选定目标设备。在支持短信的固件上，`modem.list_sms()` 读取短信，`modem.send_sms(recipient, text)` 提交短信。读取可能改变未读标记；提交成功表示模块接受了请求，不代表对方已收到。长短信可能按多条计费。

## 命令行

把 `COM7` 替换为 `cellulary ports` 显示的 AT 端口。

```sh
cellulary ports
cellulary scan
cellulary status COM7
cellulary numbers COM7
cellulary gnss COM7 status
cellulary sms COM7
cellulary data COM7 status
cellulary usb-data COM7 status
cellulary call COM7 list
cellulary network --port COM7
```

运行 `cellulary --help` 查看完整命令。配置、发送、呼叫与连接切换均通过显式操作执行。

## 硬件支持

| 模块 | 状态 | 主要区别 |
| --- | --- | --- |
| 移远 EC200A-EU / EUV1 | 首批硬件目标 | LTE Cat 4；语音需要匹配的固件、运营商服务及音频硬件；不声明 EU 支持 GNSS |
| 移远 EC801E-CN | 首批硬件目标 | LTE Cat 1；RNDIS/ECM；短信取决于固件，已下载 E 系列手册明确排除此型号的短信支持 |
| 移远 EC25 | 协议驱动 | 已集成短信、通话/数据与 GNSS 命令；本项目尚未在真实 EC25 上验证 |
| 其他 4G / 5G 模块 | 可扩展 | 添加厂商/型号驱动并取得验证证据后，再声明支持 |

[兼容性矩阵](docs/zh-CN/compatibility.md) · [官方命令依据](docs/zh-CN/hardware-support.md) · [硬件验证记录](docs/zh-CN/hardware-validation.md)

PDP 已激活或 USB 拨号请求成功，并不代表电脑已获得地址、DNS 与互联网路由。Windows 联网集成使用系统中已经安装的接口和配置文件。

通话控制不传输浏览器麦克风或扬声器音频。管理台按设备能力提供操作；无 SIM、命令不支持和 GNSS 尚未定位是不同状态。

## 扩展结构

```text
Python API · CLI · Web 管理台
              │
         Modem / Manager
              │
           驱动注册表
              │
   drivers/quectel/
   ├── ec200a.py
   ├── ec801e.py
   └── ec25.py
              │
       串口传输与 URC
```

共享传输层处理串口事务和异步通知，厂商/型号驱动定义命令行为与能力，主机网络层独立处理操作系统接口。新增型号请参阅[架构说明](docs/zh-CN/architecture.md)。

## 文档

- [兼容性](docs/zh-CN/compatibility.md)：选择硬件与理解能力边界。
- [硬件与命令依据](docs/zh-CN/hardware-support.md)：官方版本、命令定义和固件限制。
- [故障排查](docs/zh-CN/troubleshooting.md)：端口、短信、本机号码、数据连接和 GNSS。
- [架构](docs/zh-CN/architecture.md)：驱动组织与扩展方法。
- [硬件验证](docs/zh-CN/hardware-validation.md)：按日期记录实测与待验收项目。
- [English documentation](docs/README.md)：英文文档。

服务默认绑定本机回环地址，写请求使用来源/Host 校验与本机会话令牌。它面向本地管理，运行时不需要移远官网账号。

## 开发

```sh
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
uv build
```

自动化测试使用模拟串口响应。真实硬件验收单独记录，避免将协议测试等同于运营商送达、音频或上网验证。

## 许可证

Cellulary 使用 [GPL-3.0-only](LICENSE)。厂商资料版权归相应权利人所有；移远原始资料保存在被 Git 忽略的 `docs/vendor/` 中，[资料清单](docs/vendor-sources.json) 记录来源与校验值。
