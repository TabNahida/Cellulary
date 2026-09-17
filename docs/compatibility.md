# Compatibility

[Documentation](README.md) · [简体中文](zh-CN/compatibility.md)

A driver implements a protocol; a successful test on physical hardware verifies a particular module and firmware. Neither guarantees every carrier, SIM plan or hardware variant. See [hardware validation](hardware-validation.md) for dated observations.

| Capability | EC200A-EU / EUV1 | EC801E-CN | EC25 |
| --- | --- | --- | --- |
| Identity, SIM and registration | Initial hardware target | Initial hardware target | Protocol driver; hardware unverified |
| SMS | PDU interface; delivery requires carrier testing | Firmware-dependent; E AT V1.3 explicitly excludes this model, so runtime capability checks are essential | Protocol driver; hardware unverified |
| Host data | Windows MBN where enumerated; QNETDEVCTL driver on applicable USB-network firmware | RNDIS/ECM USB control via `QNETDEVCTL` | Driver implementation; host setup requires validation |
| Call control | Requires voice firmware and service | Unsupported by the current driver; no documented voice/audio path | Protocol driver; hardware unverified |
| Subscriber numbers | SIM-stored numbers, when available | SIM-stored numbers, when available | SIM-stored numbers, when available |
| GNSS | Not claimed for EU/EUV1; CN optional variants are a separate target | Not documented as supported | QGPS-family protocol support; receiver hardware unverified |
| Browser audio | Not implemented | Not implemented | Not implemented |

## Platform scope

The Python package requires Python 3.11 or later. Serial access uses pyserial. Current physical validation and host-network management target Windows; other systems need their own interface permissions, drivers and network integration. The presence of a serial device alone does not verify cross-platform operation.

Automatic discovery selects recognized Quectel AT interfaces. A USB VID/PID can be shared by multiple products and a single module can expose several ports, so driver selection also uses manufacturer, model and firmware identification. Unsupported devices should retain an explicit unknown capability state.

## Firmware-sensitive behavior

EC801E is not a smaller EC200A with interchangeable commands. Its official manual limits SMS, character-set and other commands, and deployed firmware may differ from that manual. Probe the relevant capability and preserve the exact reason for an unavailable feature. A missing SIM must not be turned into permanent hardware incompatibility.

`CNUM` reads the SIM's own-number records. A valid empty response means the SIM did not provide a number; it does not identify a network fault. Phonebook fallback is optional and must not overwrite SIM records.

A successful AT command confirms the module's response. It does not prove SMS delivery, working call audio, a GNSS fix or host Internet access. The application keeps those outcomes distinct.

## Source status

The local source collection contains **15 official Quectel PDFs**, including A/E AT manuals, USB descriptors, hardware, PPP, audio, UAC and IMS documentation. They were downloaded from the official Chinese website; provenance, versions and hashes are recorded in [vendor-sources.json](vendor-sources.json). Originals are in the ignored `docs/vendor/` directory and are not redistributed with the package.

The [command reference](hardware-support.md) identifies the sections used for implementation. A document appearing in the collection does not imply that every feature it describes applies to every module. In particular, the E-series audio guide does not list EC801E in its applicability table.

## Adding support

Add a vendor/model driver, command and parsing tests, source references and a dated hardware validation record. Use unknown or unsupported states until evidence supports each capability. New 5G modules require explicit handling for their USB layout, network registration fields, data mode and voice support.
