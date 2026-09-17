# Hardware and command reference

[Documentation](README.md) · [简体中文](zh-CN/hardware-support.md)

Sources checked: 2026-09-16, with command review on 2026-09-17. This project runs Python on the host computer and controls standard AT firmware; it does not require QuecPython inside the module. Original files are local research material in `docs/vendor/`. The [source manifest](vendor-sources.json) records URLs, versions, publication dates and SHA-256 hashes.

Manual page numbers below refer to the **printed footer**, not the PDF viewer index. For example, printed page 137 of the E AT manual is PDF page 138.

## Product distinctions

| Property | EC200A-EU | EC801E-CN |
| --- | --- | --- |
| LTE category | Cat 4, up to 150 Mbps down / 50 Mbps up | Cat 1, up to 10 Mbps down / 5 Mbps up |
| LTE-FDD bands | B1/3/5/7/8/20/28 | B1/3/5/8 |
| LTE-TDD bands | B38/40/41 | B34/38/39/40/41 |
| Windows interfaces in product specification | USB serial, RNDIS | USB serial, RNDIS |
| Linux interfaces in product specification | USB serial, RNDIS, ECM | USB serial, RNDIS, ECM; some V1.0 entries carry an in-development footnote |
| Voice hardware | Digital voice, VoLTE, PCM and analog microphone/receiver listed | No voice, VoLTE or audio interface listed in the industrial V1.0 specification |
| GNSS | EU column does not list GNSS; CN optional support is a separate variant | No GNSS support documented in the reviewed specifications |

Sources: EC200A product specification V1.6, pages 1-3; EC801E-CN product specification V1.0, pages 1-2. The EC801E specification explicitly covers the industrial module. Separate industrial and consumer hardware manuals are in the collection. These products are 4G modules; they do not demonstrate 5G support.

Use `ATI`, `AT+CGMM` and `AT+CGMR`/`AT+QGMR` together. An EC200A may identify only as `EC200A`; the regional and V1 revision must be interpreted with its firmware and hardware part number. Keep physical-device observations in [hardware validation](hardware-validation.md).

## USB network control

The E AT manual V1.3 page 51 and A AT manual V1.4 page 54 define `AT+QCFG="usbnet"` as a query when no mode argument is supplied: `1` is ECM and `3` is RNDIS. Writing the mode saves configuration and requires a restart. Discovery should only query it.

The E manual's page 40 EC801E QCFG applicability note is more restrictive than responses observed on later firmware. Old enumerations are not exhaustive guarantees about later firmware. Likewise, an EC200A variant that actually enumerates as a Windows mobile broadband interface should use the observed interface; do not infer its protocol solely from an older table.

The [official EC801E forum reply](https://forumschinese.quectel.com/t/topic/10409), post 2, states that EC801E does not support MBIM/QMI. This is not an EC200A restriction. EC801E USB descriptors V1.3 page 9 list shared VID/PID `2C7C:0903`; USB identity alone cannot uniquely identify the model. The descriptor guide notes that Windows ECM needs an appropriate ECM driver.

The E AT manual pages 137-138 and A AT manual pages 175-176 define:

```text
AT+QNETDEVCTL=<type>,<cid>[,<URC_en>]
```

| Item | Meaning |
| --- | --- |
| `type=0` | Disconnect the USB network connection |
| `type=1` | Connect once |
| `type=3` | Connect automatically; this configuration is saved |
| `cid` | PDP context identifier, documented range 1-15; query the firmware's supported values |
| `URC_en=0/1` | Disable/enable `+QNETDEVSTATUS` notifications |
| `AT+QNETDEVCTL=?` | Test supported parameter ranges |
| `AT+QNETDEVCTL?` | Read `type,cid,URC_en,state`, with state 0 disconnected or 1 connected |
| `AT+QNETDEVCTL=1,1,1` | Connect context 1 once and enable notifications |
| `AT+QNETDEVCTL=0,1,0` | Disconnect context 1 and disable notifications |
| `+QNETDEVSTATUS: 0/1` | Unsolicited disconnected/connected notification |

The documented maximum command response time is two seconds. An `OK` accepts the request; later state and host-network checks establish its outcome. The manuals contain a sample that labels a parameter-range response with `QNETDEVCTL?`; the formal syntax table distinguishes `=?` from `?` and should guide the implementation.

The [official support thread 5976](https://forumschinese.quectel.com/t/topic/5976), posts 4 and 6, corroborates the connect/disconnect commands. It also illustrates that a valid PDP address can coexist with failed host DHCP. `QNETDEVSTATUS` is a notification, not an assumed query command; the thread's firmware rejects `AT+QNETDEVSTATUS=?`.

APN/context configuration, USB connection, host DHCP, DNS and routing are separate stages. Do not automatically change USB mode, reboot, alter routing or enable persistent auto-connect during device discovery.

PPP varies by firmware. The V1.0 EC801E specification marks it in development; [thread 4637](https://forumschinese.quectel.com/t/topic/4637) describes a firmware without it, while a later support reply mentions support. Probe rather than infer universal availability.

## SMS: model applicability comes before generic syntax

The E AT manual V1.3 (2025-07-22), **page 95**, explicitly states that EC600Z-CN, EC800Z-CN and **EC801E-CN temporarily do not support SMS commands**. Its subsequent generic SMS sections do not override that model restriction.

Pages 96-97 define `CMGF=0` for PDU and `CMGF=1` for text on applicable firmware. Pages 101-102 define numeric status **4** for all messages in PDU mode, versus the string **"ALL"** in text mode. Sending `CMGL="ALL"` while in PDU mode is a protocol mismatch. A rejected `CMGF` should produce an unsupported-feature result, not cascade into an apparently empty inbox.

The A AT manual V1.4 describes `CMGF`, `CPMS`, `CMGL`, `CMGR`, `CMGS`, `CMGD` and `CNMI`. The implementation must handle GSM 7-bit/UCS2, multipart messages, unsolicited notifications and partial submission. Reading messages can change unread flags. Do not retry a timed-out or partially submitted send automatically.

Later firmware can differ from the E manual. Use conservative driver defaults and relevant runtime tests; retain the command result and reason when the feature is unavailable. SIM absence and unsupported firmware are distinct conditions.

## Subscriber numbers

`AT+CNUM` reads own-number records stored on the SIM: E AT V1.3 page 94 and A AT V1.4 page 110. It can return zero, one or several records followed by `OK`. An empty response means **unknown**, not an empty telephone number that can be reconstructed from IMSI/ICCID, and not a network registration failure.

A AT V1.4 pages 112-114 document `CPBR` and `CPBS`. Phonebook store `"ON"` is the SIM own-number/MSISDN list; some firmware does not support these commands. The E manual's phonebook chapter documents CNUM only. Therefore a future `CPBS="ON"` fallback must be optional, probe support, read bounded indices and restore the previous store. It must never write `CPBW` merely to discover a number. The current CNUM result remains valid when no fallback exists.

## Voice, audio and GNSS

Call control (`ATD`, `ATA`, `ATH`, `CLCC`) is separate from audio transport. EC200A needs suitable voice firmware, SIM service, carrier VoLTE support and a carrier-board audio path. Downloaded A audio V1.3, UAC V1.1 and IMS XML V1.1 guides provide material for further integration; browser audio is not implemented.

The E audio guide V1.0 page 6 does **not** list EC801E. It lists EC600E, EC800E, EC600Z, EC800Z and EG800Z and limits applicability to 4 MB Flash modules. Its name is not evidence of EC801E audio support.

The EC25 driver implements QGPS-family GNSS queries/control and distinguishes an unsupported receiver, a disabled receiver and a receiver awaiting a fix. No physical EC25 has been validated in this project. Its protocol implementation must not turn into a GNSS promise for EC200A-EU or EC801E.

The official catalogue lists an [EC2x/EG2x/EG9x/EM05 GNSS application note V1.4](https://www.quectel.com.cn/download/quectel_ec2xeg2xeg9xem05%e7%b3%bb%e5%88%97_gnss_%e5%ba%94%e7%94%a8%e6%8c%87%e5%af%bc_v1-4) for further EC25 review. This catalogue entry was verified; its PDF was not downloaded or body-reviewed as part of the 15-file collection.

## Initialization differences

E AT V1.3 page 28 limits EC801E `CMEE` to `0` or `1`; use numeric extended errors with `CMEE=1`. Page 29 excludes EC801E from `CSCS`, and page 129 excludes it from `CGDATA`. A failed optional command should not make the whole online module disappear.

## Downloaded source collection

The collection contains two public product specifications and thirteen authenticated official PDFs: A/E AT, A/E USB descriptors, EC200A hardware, EC801E industrial and consumer hardware, A/E PPP, A/E audio, EC200x/EC600N UAC and A IMS XML. Key specification tables and the E manual's USB, SMS restriction and dial definitions were visually checked against rendered pages. Other files remain available for focused review; downloading a file does not validate every command.

The manifest's driver-package entry remains unavailable because the already installed drivers were not replaced. Original PDFs, extracted text and download archives stay under the ignored `docs/vendor/`. No website password or session cookie is required by or stored in the project.
