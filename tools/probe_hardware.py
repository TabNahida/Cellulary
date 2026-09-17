"""Read-only hardware evidence. No SMS, calls, resets or connection changes."""
import concurrent.futures
import json
import time

import serial
from serial.tools import list_ports


def probe(port):
    result = {"port": port.device, "description": port.description, "responses": {}}
    try:
        with serial.Serial(port.device, 115200, timeout=0.15, write_timeout=2) as connection:
            for command in ("AT", "ATI", "AT+CGMM", "AT+CGMR", "AT+CPIN?", "AT+CSQ", "AT+CEREG?", "AT+COPS?", "AT+CGATT?", "AT+CGACT?", 'AT+QCFG="usbnet"'):
                connection.write((command + "\r").encode())
                deadline = time.monotonic() + 3
                data = b""
                while time.monotonic() < deadline:
                    data += connection.read(connection.in_waiting or 1)
                    if any(token in data for token in (b"\r\nOK\r\n", b"\r\nERROR\r\n", b"+CME ERROR:", b"+CMS ERROR:")):
                        break
                result["responses"][command] = data.decode("ascii", errors="replace").strip()
    except Exception as error:
        result["error"] = str(error)
    return result


if __name__ == "__main__":
    ports = [p for p in list_ports.comports() if p.vid == 0x2C7C and "AT Port" in p.description]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        print(json.dumps(list(pool.map(probe, ports)), ensure_ascii=False, indent=2))
