"""Host networking: Windows Mobile Broadband profiles; no implicit route changes."""
from __future__ import annotations

import json
import locale
import platform
import re
import subprocess


def usb_parent(instance: str) -> str | None:
    """Match composite USB interfaces by physical parent, never shared MACs."""
    match = re.fullmatch(r"USB\\(VID_[0-9A-F]{4}&PID_[0-9A-F]{4})&MI_[0-9A-F]{2}\\(.+)&[0-9A-F]{4}", instance.upper())
    return f"{match[1]}\\{match[2]}" if match else None


def windows_usb_ports() -> dict[str, str]:
    import winreg

    result = {}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Enum\USB") as usb:
        for index in range(winreg.QueryInfoKey(usb)[0]):
            try:
                device = winreg.EnumKey(usb, index)
                if not device.upper().startswith("VID_2C7C&"):
                    continue
                with winreg.OpenKey(usb, device) as instances:
                    for child in range(winreg.QueryInfoKey(instances)[0]):
                        try:
                            instance = winreg.EnumKey(instances, child)
                            with winreg.OpenKey(instances, instance + r"\Device Parameters") as params:
                                port = winreg.QueryValueEx(params, "PortName")[0]
                            with winreg.OpenKey(instances, instance) as entry:
                                name = winreg.QueryValueEx(entry, "FriendlyName")[0]
                            parent = usb_parent(f"USB\\{device}\\{instance}")
                            if parent and re.search(r"\bAT\s+Port\b", name, re.I):
                                result[parent] = port
                        except OSError:
                            continue
            except OSError:
                # A composite device can disappear between enumeration and read.
                continue
    return result


def annotate_adapters(adapters: list[dict], ports: dict[str, str]) -> list[dict]:
    """Add conservative host configuration diagnostics; no Internet claims."""
    for adapter in adapters:
        adapter["device_port"] = ports.get(usb_parent(adapter.get("PnPDeviceID") or ""))
        mac = adapter.get("MacAddress", "")
        peers = [a["Name"] for a in adapters if a is not adapter and mac and a.get("MacAddress") == mac]
        adapter["duplicate_mac"] = bool(peers)
        adapter["conflicts"] = peers
        usable = [ip for ip in adapter.get("ipv4", []) if ip.get("state") == "Preferred" and not ip["address"].startswith(("169.254.", "127."))]
        adapter["host_configured"] = bool(adapter.get("Status") == "Up" and usable and adapter.get("gateways"))
        adapter["internet_verified"] = False
    return adapters


def windows_adapters() -> list[dict]:
    # .NET reads IP Helper state without WMI/admin requirements. Intersecting
    # with live interfaces avoids stale registry adapters after re-enumeration.
    script = r"""
[Console]::OutputEncoding=[Text.UTF8Encoding]::new()
$result = @([Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | ForEach-Object {
    $nic = $_
    try {
    $ip = $nic.GetIPProperties(); $v4 = $null
    if ($nic.Supports([Net.NetworkInformation.NetworkInterfaceComponent]::IPv4)) { $v4 = $ip.GetIPv4Properties() }
    $path = 'HKLM:\SYSTEM\CurrentControlSet\Control\Network\{4d36e972-e325-11ce-bfc1-08002be10318}\' + $nic.Id + '\Connection'
    $pnp = (Get-ItemProperty -LiteralPath $path -ErrorAction SilentlyContinue).PnpInstanceID
    [pscustomobject]@{
        Name=$nic.Name; InterfaceDescription=$nic.Description; Status=$nic.OperationalStatus.ToString()
        InterfaceGuid=$nic.Id; ifIndex=$v4.Index; PnPDeviceID=$pnp
        MacAddress=$nic.GetPhysicalAddress().ToString(); dhcp=$v4.IsDhcpEnabled
        ipv4=@($ip.UnicastAddresses | Where-Object {$_.Address.AddressFamily -eq 'InterNetwork'} | ForEach-Object { @{address=$_.Address.ToString();state=$_.DuplicateAddressDetectionState.ToString()} })
        gateways=@($ip.GatewayAddresses | Where-Object {$_.Address.AddressFamily -eq 'InterNetwork'} | ForEach-Object {$_.Address.ToString()})
        dns=@($ip.DnsAddresses | ForEach-Object {$_.ToString()})
    }
    } catch {
        [pscustomobject]@{Name=$nic.Name; InterfaceDescription=$nic.Description; Status='Unknown'; InterfaceGuid=$nic.Id; query_error=$_.Exception.Message}
    }
})
ConvertTo-Json -InputObject $result -Depth 5 -Compress
"""
    completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                               capture_output=True, timeout=20, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip() or "Could not enumerate Windows adapters")
    adapters = json.loads(completed.stdout.decode("utf-8-sig"))
    return annotate_adapters(adapters, windows_usb_ports())


def run(arguments: list[str], timeout=20, *, read_only=False) -> str:
    result = subprocess.run(arguments, capture_output=True, timeout=timeout, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    encoding = "oem" if platform.system() == "Windows" else locale.getpreferredencoding(False)
    raw = result.stdout + result.stderr
    try:
        output = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        output = raw.decode(encoding, errors="replace").strip()
    # Some Windows MBN versions return 1 after a complete successful `show`.
    # Only queries may consume that output; mutations always check exit status.
    if result.returncode and not read_only:
        raise RuntimeError(output or f"Command failed ({result.returncode})")
    return output


def parse_mbn_interfaces(output: str) -> list[dict]:
    interfaces = []
    current = None
    for line in output.splitlines():
        match = re.match(r"\s*(Name|名称|名字)\s*[:：]\s*(.+)", line, re.I)
        if match:
            current = {"name": match.group(2).strip(), "kind": "mbn"}
            interfaces.append(current)
        elif current:
            match = re.match(r"\s*(Description|描述|State|状态|GUID|Model|型号|Device Id|设备 ID|Provider Name|提供商名称)\s*[:：]\s*(.+)", line, re.I)
            if match:
                key = {"description": "description", "描述": "description", "state": "state", "状态": "state", "guid": "guid", "model": "model", "型号": "model", "device id": "device_id", "设备 id": "device_id", "provider name": "provider", "提供商名称": "provider"}[match.group(1).lower()]
                current[key] = match.group(2).strip()
    return interfaces


def parse_adapters(output: str) -> list[dict]:
    adapters = []
    for line in output.splitlines():
        fields = re.split(r"\s{2,}", line.strip(), maxsplit=3)
        if len(fields) == 4 and fields[0] in {"Enabled", "Disabled", "已启用", "已禁用"}:
            adapters.append({"Name": fields[3], "Status": fields[1], "InterfaceDescription": fields[2]})
    return adapters


class HostNetwork:
    def status(self):
        result = dict(platform=platform.system(), interfaces=[], profiles=[], adapters=[], errors=[])
        if platform.system() != "Windows":
            result["note"] = "Host connection control currently supports Windows MBN. Use NetworkManager/ModemManager on Linux."
            return result
        try:
            listing = run(["netsh", "mbn", "show", "interfaces"], read_only=True)
            result["interfaces"] = parse_mbn_interfaces(listing)
            if not result["interfaces"]:
                result["errors"].append(listing)
            for interface in result["interfaces"]:
                output = run(["netsh", "mbn", "show", "profiles", f"interface={interface['name']}"], read_only=True)
                # netsh lists profile names after the dashed separator, in all locales.
                names = []
                in_profiles = False
                for line in output.splitlines():
                    if re.match(r"\s*-{3,}\s*$", line):
                        in_profiles = True
                    elif in_profiles and line.strip():
                        names.append(line.strip())
                result["profiles"].extend({"interface": interface["name"], "name": n} for n in names)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            result["errors"].append(str(exc))
        try:
            result["adapters"] = windows_adapters()
        except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            result["errors"].append(str(exc))
        if not result["adapters"]:
            try:
                result["adapters"] = parse_adapters(run(["netsh", "interface", "show", "interface"], read_only=True))
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                result["errors"].append(str(exc))
        result["note"] = "MBN uses existing Windows profiles. RNDIS/ECM needs module USB data and host DHCP. A registered modem or configured adapter does not prove Internet access."
        return result

    def device_status(self, port: str):
        state = self.status()
        adapters = [a for a in state["adapters"] if a.get("device_port") == port]
        return {"device_port": port, "adapters": adapters, "errors": state["errors"],
                "reason_code": None if adapters else "adapter_not_mapped", "note": state["note"]}

    def connect(self, interface: str, profile: str):
        state = self.status()
        if not any(p["interface"] == interface and p["name"] == profile for p in state["profiles"]):
            raise ValueError("Select an existing Windows profile for this MBN interface")
        return {"message": run(["netsh", "mbn", "connect", f"interface={interface}", "connmode=name", f"name={profile}"], timeout=60)}

    def disconnect(self, interface: str):
        if interface not in {i["name"] for i in self.status()["interfaces"]}:
            raise ValueError("MBN interface not found")
        return {"message": run(["netsh", "mbn", "disconnect", f"interface={interface}"])}
