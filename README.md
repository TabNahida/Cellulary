<div align="center">

# Cellulary

**Your cellular modems. One Python API. One local dashboard.**

SMS · Mobile data · Call control · SIM information · GNSS

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue)](LICENSE)

[Quick start](#quick-start) · [Supported hardware](#supported-hardware) · [Documentation](docs/README.md) · [简体中文](README.zh-CN.md)

</div>

Cellulary brings USB cellular modules into a single workspace: a Python library for your applications, a CLI for scripts, and a web console for daily operation. Discover multiple modems, inspect their SIM and network state, read messages, and control supported services from your own computer.

Model-specific drivers keep vendor commands and firmware differences behind a common API. The first hardware targets are **Quectel EC200A-EU/EUV1** and **EC801E-CN**. An **EC25** driver provides a protocol implementation, including GNSS, awaiting hardware validation.

## What you can build

| Capability | What Cellulary provides |
| --- | --- |
| Multiple modems | AT-port discovery, model and firmware identification, SIM readiness, signal and registration state |
| SMS | PDU messaging, GSM 7-bit and UCS2, multipart messages, and partial-submission reporting on capable firmware |
| Mobile data | APN/PDP management, EC200A/EC801E USB network control, and existing Windows mobile broadband profiles |
| Call control | Dial, answer, hang up, and inspect calls when the module, firmware and SIM support voice |
| SIM information | Subscriber-number lookup where the SIM exposes it; an empty number remains unknown |
| GNSS | Driver-specific receiver control and position queries; EC25 protocol support, no GNSS assumption for EC200A-EU or EC801E |
| Local dashboard | Device overview, service actions, capability feedback and event history, backed by FastAPI |

## Quick start

Install Python **3.11 or later** and the USB drivers for your module, then connect it to your computer. Use the module's **AT port**; diagnostic and modem ports serve different purposes.

```sh
git clone https://github.com/TabNahida/Cellulary.git
cd Cellulary
python -m pip install -e .
cellulary web
```

Open **http://127.0.0.1:8765**. Interactive API documentation is at **http://127.0.0.1:8765/docs**.

The dashboard starts in English, with a Chinese language option and system, light and dark themes. Select a modem once and switch between its overview, messages, network, calls and GNSS. The Network tab also identifies the matching host adapter and flags duplicate MAC addresses.

With [uv](https://docs.astral.sh/uv/), run `uv sync --extra dev` followed by `uv run cellulary web`.

The web service owns the AT ports it opens. Stop it with **Ctrl+C** before using the CLI or another Python process on those same ports. [Troubleshooting →](docs/troubleshooting.md)

## Use it from Python

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

Choose the intended device before performing an action. On SMS-capable firmware, `modem.list_sms()` reads messages and `modem.send_sms(recipient, text)` submits a message. Reading can mark a message as read. A submission response confirms acceptance by the module, not delivery to the recipient; multipart SMS can incur multiple charges.

## Use it from the terminal

Replace `COM7` with an AT port reported by `cellulary ports`.

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

Run `cellulary --help` for available commands. Configuration, sending, calling and connection changes are explicit operations.

## Supported hardware

| Module | Status | Important distinctions |
| --- | --- | --- |
| Quectel EC200A-EU / EUV1 | Initial hardware target | LTE Cat 4; voice requires matching firmware, carrier service and audio hardware; EU GNSS is not claimed |
| Quectel EC801E-CN | Initial hardware target | LTE Cat 1; RNDIS/ECM; SMS depends on firmware, and the downloaded E-series manual explicitly excludes it for this model |
| Quectel EC25 | Protocol driver | SMS, call/data and GNSS command integration; not yet tested on physical EC25 hardware in this project |
| Other 4G / 5G modules | Extension path | Add a vendor/model driver and validation evidence before declaring support |

[Compatibility matrix](docs/compatibility.md) · [Official command references](docs/hardware-support.md) · [Dated hardware validation](docs/hardware-validation.md)

An active PDP context or successful USB dial request does not establish that the computer has an address, working DNS or an Internet route. Windows host-network integration uses interfaces and profiles already installed on the computer.

Call control does not stream browser microphone or speaker audio. The dashboard exposes device capabilities; a missing SIM, an unsupported command and a missing GNSS fix are different conditions.

## Designed to extend

```text
Python API · CLI · Web console
              │
         Modem / Manager
              │
        Driver registry
              │
   drivers/quectel/
   ├── ec200a.py
   ├── ec801e.py
   └── ec25.py
              │
     Serial transport + URCs
```

Shared transport handles serial transactions and unsolicited notifications. Vendor/model drivers define command behavior and capabilities. Host-network integration handles operating-system interfaces separately. See the [architecture guide](docs/architecture.md) for adding a module.

## Documentation

- [Compatibility](docs/compatibility.md) — hardware selection and capability boundaries.
- [Hardware and command reference](docs/hardware-support.md) — official manuals, commands and firmware caveats.
- [Troubleshooting](docs/troubleshooting.md) — ports, SMS, SIM numbers, data and GNSS.
- [Architecture](docs/architecture.md) — driver organization and extension guidelines.
- [Hardware validation](docs/hardware-validation.md) — dated observations and outstanding acceptance tests.
- [中文文档](docs/zh-CN/README.md) — Chinese companions to the English documentation.

The service binds to loopback by default and protects write requests with origin/host checks and a local session token. It is intended for local administration. No Quectel website credentials are needed to run Cellulary.

## Development

```sh
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
uv build
```

Automated tests use simulated serial responses. Hardware acceptance is recorded separately so protocol coverage is not confused with carrier delivery, audio or Internet validation.

## License

Cellulary is licensed under [GPL-3.0-only](LICENSE). Vendor documents remain the property of their respective owners. Original Quectel files are kept locally under the ignored `docs/vendor/` directory; the [source manifest](docs/vendor-sources.json) records provenance and checksums.
