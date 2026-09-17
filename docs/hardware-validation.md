# Hardware validation

[Documentation](README.md) · [简体中文](zh-CN/hardware-validation.md)

These are dated observations from physical devices on Windows with the manufacturer's drivers installed. They describe the tested hardware and firmware, not every revision or carrier. Device labels below are local to this record; phone numbers, SIM identifiers, unique device identifiers and adapter addresses are omitted.

## Test inventory

| Label | Module | Firmware | SIM |
| --- | --- | --- | --- |
| A | EC200A-EU/EUV1 | `EC200AEUV1HAR02A08M16` | Ready |
| E1 | EC801E-CN | `EC801ECNCGR07A03M02` | Ready |
| E2–E5 | Four EC801E-CN modules | `EC801ECNCGR07A03M02` | Absent |

EC801E enumerated with USB VID/PID `2C7C:0903`; EC200A used `2C7C:6005`. The AT interface was `MI_03`. Model and firmware queries distinguished products; multiple USB ports belonging to one module were not counted as separate modules. COM port names changed during the investigation and are not stable device identities.

## 2026-09-16 — Initial integration

- All six AT ports responded and `cellulary scan` found all six devices. No-SIM `+CME ERROR: 10` responses mapped to SIM absent while the modules remained online.
- A and E1 were attached to data service with active PDP contexts. A was registered on its home network; E1 was registered while roaming.
- Windows reported A's mobile broadband interface connected and exposed its existing profiles. Read-only `QCFG="usbnet"` queries returned mode `2` for A and `3` for E1; no USB mode was changed.
- E1's `QNETDEVCTL?` returned `3,1,1,1`, an already configured automatic USB connection in connected state. Cellulary did not start or stop that pre-existing session during this validation.
- The live web API reported six modules and two ready SIMs, matching serial responses.
- The dashboard was checked at 1265×712 and 390×844. Device selection, data reads, call-state reads, errors and event filtering worked without whole-page horizontal overflow or browser-console errors.
- A accepted `CLCC` and reported no active calls. E1 returned `ERROR` for the same query; this did not establish EC801E voice support.

This phase did not send SMS, initiate or answer calls, change APNs, activate/deactivate connections or switch system routing. Existing connected-state reports did not verify the computer's actual Internet path.

## 2026-09-17 — EC801E data path investigation

### Capability and subscriber-number checks

A returned a subscriber-number record through `CNUM`; the number is intentionally not reproduced here. E1 returned `OK` with no number records. Its `CPBS=?`, `CMGF=?`, `CMGF?`, `CPMS?`, `CSCA?`, `CLCC` and `QGPS` queries returned `ERROR` on the tested firmware.

A read-only SIM-file investigation confirmed E1's missing number: `CRSM` file metadata for `EF_MSISDN` described five records of 30 bytes each, and all five records had an empty number-length field (`0xFF`). No SIM records were written. This SIM does not store its own number in that file; neither `CNUM` nor reading `EF_MSISDN` can recover an absent record. It remains an unknown number, independently of working data service.

The SMS command failures agree with the E AT V1.3 manual's EC801E restriction. SMS was not repaired or declared supported. EC801E voice and GNSS were not demonstrated.

### Diagnosis and recovery

E1 was registered on LTE band B3 while roaming and already had a PDP address. The observed failure was therefore not a failure to find a supported radio band.

All five EC801E RNDIS interfaces exposed the same MAC address. Correlating each AT port and network adapter through its USB parent showed that E1's host adapter had an APIPA/link-local address, while an adapter belonging to a module without a SIM held a DHCP lease. Friendly interface names and the duplicate MAC alone could not safely identify the correct adapter.

Recovery released the DHCP lease only on that verified no-SIM adapter and renewed DHCP only on E1's adapter. E1 then obtained a valid lease and gateway. No unrelated or primary network adapter was changed, and no persistent modem settings were altered.

### Internet-path verification

Requests explicitly selected E1's host interface, so successful traffic could not simply be attributed to another desktop connection:

- A UDP DNS query for `example.com` selected E1 with `IP_UNICAST_IF`, bound its source address and used the modem-assigned DNS server. The response matched the transaction ID, returned success (`rcode=0`) and contained two answers.
- An HTTP request used Windows `IP_UNICAST_IF` with the interface index in network byte order, plus a source-address bind. The remote endpoint returned HTTP **301**.
- An HTTPS request used `curl.exe --interface` with E1's source address and Windows TLS trust. `www.cloudflare.com` returned HTTP **200**.
- A separate Python HTTPS request combined `IP_UNICAST_IF` and a source-address bind with certificate verification enabled. It negotiated **TLS 1.3** and received HTTP **200** from `www.cloudflare.com`, confirming the encrypted path on the selected interface.

These checks verified DNS, HTTP and HTTPS traffic through this EC801E at that time. They did not measure throughput, long-term stability or failover.

The duplicate-MAC condition remains. Sustained use with multiple active SIMs needs documented, unique per-module MAC provisioning or another validated interface strategy. No persistent MAC change or related reboot was performed during this recovery.

## What remains unverified

| Area | Outstanding acceptance work |
| --- | --- |
| SMS | Actual send/receive and delivery on SMS-capable hardware, including multipart delivery and carrier behavior |
| Voice | Real incoming/outgoing calls and an audio path on voice-capable hardware |
| Connection control | Deliberate APN changes, connect/disconnect transitions and recovery across target firmware |
| Multi-modem data | Concurrent active SIMs, unique adapter identity, sustained traffic and reconnect behavior |
| EC25 / GNSS | Physical EC25 variant, receiver control, antenna and position fixes; current coverage is protocol testing |
| Other platforms | Physical validation and host-network integration beyond Windows |

Automated tests exercise protocol parsing and request behavior with simulated responses; they do not replace these acceptance checks. `tools/probe_hardware.py` can repeat read-only hardware inspection after stopping the web service to release its serial ports. It contains no SMS-send, call, reboot, PIN-entry or network-state write commands.
