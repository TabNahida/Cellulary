# Troubleshooting

[Documentation](README.md) · [简体中文](zh-CN/troubleshooting.md)

Record the model, firmware, failing command and sanitized response first. A modem can remain online while an individual feature is unavailable. Remove phone numbers, message bodies, SIM identifiers and device identifiers before sharing logs.

## The AT port is busy or missing

Use `cellulary ports` to find the AT interface. Diagnostic, download and modem interfaces are not interchangeable. Stop the Cellulary web service, terminal programs and other serial clients before opening the same port elsewhere. Re-enumerate after moving USB ports or changing drivers; cached port names may be stale.

## EC801E SMS fails

The downloaded E AT V1.3 page 95 explicitly excludes EC801E SMS. Check the actual firmware response to `AT+CMGF=?`; a rejected command or missing PDU mode is an unsupported SMS capability, not an empty inbox. The tested firmware's behavior is in [hardware validation](hardware-validation.md).

On firmware supporting PDU, `CMGF=0` pairs with numeric `CMGL=4` for all messages. `CMGL="ALL"` belongs to text mode. Do not repeatedly retry an unsupported mode or send. A partially submitted SMS must be surfaced with its submission references because automatic retries can duplicate messages.

## A SIM has no displayed phone number

`CNUM` reads what the SIM stores. Some SIMs return a number; others return only `OK`. The latter means unknown. It does not prevent the SIM from registering or carrying data. `CPBS="ON"` is not supported by every firmware and is not a guaranteed remedy. Do not infer a number from IMSI/ICCID or write the SIM phonebook to make the field appear populated.

## The module is connected but the computer has no Internet

Check the layers independently:

1. SIM ready and LTE registered, including whether registration is roaming.
2. PDP context and module-assigned address.
3. `QNETDEVCTL?` state on supported RNDIS/ECM firmware, or the enumerated MBN interface.
4. The correct host adapter's DHCP address and gateway; an APIPA/link-local address is not a cellular lease.
5. Routing and DNS, followed by a request bound to that adapter to verify its actual egress.

A general browser request can use another network connection and does not prove the selected modem works. Correlate AT ports and network adapters through their USB parent device. Friendly adapter names and MAC addresses alone may be ambiguous.

Multiple EC801E units can expose the same MAC address. A DHCP lease on a modem without a SIM and an APIPA address on the registered modem is a host-adapter association problem worth checking before blaming LTE bands. Any lease release/renew must target the verified adapter; a blanket release can disrupt unrelated connections. See the dated [recovery evidence](hardware-validation.md).

For sustained multi-SIM use, investigate unique per-module MAC configuration with the applicable firmware documentation. Such changes may persist and require restart; discovery and the documented one-off recovery do not apply them automatically.

## Calls have no audio

Call state and audio transport are separate. Confirm voice-capable firmware, SIM/carrier service, VoLTE configuration where required, and the carrier board's analog/PCM/UAC audio path. The dashboard does not route browser microphone/speaker audio. EC801E has no verified voice path in this project.

## GNSS is unavailable or has no fix

EC200A-EU and EC801E do not have a documented supported GNSS path in the current drivers. EC25's GNSS protocol implementation still requires receiver/variant and hardware validation. For a supported receiver, disabled and awaiting-fix are distinct states; a valid position also requires an appropriate antenna and signal conditions.

Use `gnss_status()` or `gnss_location()` to inspect support, receiver state and fix. Start/stop are explicit actions, not automatic side effects of viewing the page.

## A web write request is rejected

Open the dashboard at its local address and let it obtain its current session token. For scripted API use, inspect the current API schema and follow its session requirements. Do not remove origin/host checks to resolve a stale session. Stop and restart the service if a stale client still owns a port.
