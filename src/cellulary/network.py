"""Host networking: Windows Mobile Broadband profiles; no implicit route changes."""
from __future__ import annotations

import json
import locale
import platform
import re
import subprocess


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
            result["note"] = "此版本主机拨号适配器支持 Windows MBN；Linux 请使用 NetworkManager/ModemManager。"
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
        script = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); @(Get-NetAdapter | Select-Object Name,InterfaceDescription,Status,LinkSpeed,ifIndex) | ConvertTo-Json -Compress"
        try:
            completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            if completed.returncode == 0:
                adapters = json.loads(completed.stdout.decode("utf-8-sig") or "[]")
                result["adapters"] = adapters if isinstance(adapters, list) else [adapters]
            else:
                result["errors"].append("Windows 网卡详细查询不可用；MBN 接口信息仍可单独读取。")
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            result["errors"].append(str(exc))
        if not result["adapters"]:
            try:
                result["adapters"] = parse_adapters(run(["netsh", "interface", "show", "interface"], read_only=True))
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                result["errors"].append(str(exc))
        result["note"] = "MBN 使用 Windows 已有配置文件。RNDIS/ECM 网卡通过模块 USB 数据拨号及 DHCP 上网；PDP 激活不代表电脑已联网。"
        return result

    def connect(self, interface: str, profile: str):
        state = self.status()
        if not any(p["interface"] == interface and p["name"] == profile for p in state["profiles"]):
            raise ValueError("请选择该 MBN 接口已有的 Windows 配置文件")
        return {"message": run(["netsh", "mbn", "connect", f"interface={interface}", "connmode=name", f"name={profile}"], timeout=60)}

    def disconnect(self, interface: str):
        if interface not in {i["name"] for i in self.status()["interfaces"]}:
            raise ValueError("未找到该 MBN 接口")
        return {"message": run(["netsh", "mbn", "disconnect", f"interface={interface}"])}
