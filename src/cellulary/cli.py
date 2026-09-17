"""Cellulary command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="cellulary", description="蜂窝模块工具库与本地管理台")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ports", help="列出移远 AT 端口，不打开串口")
    sub.add_parser("scan", help="识别所有模块并读取状态")
    serve = sub.add_parser("web", help="运行本地 Web 管理台")
    serve.add_argument("--port", type=int, default=8765)
    status = sub.add_parser("status", help="读取指定 AT 端口状态")
    status.add_argument("port")
    sms = sub.add_parser("sms", help="列出或发送短信")
    sms.add_argument("port")
    sms.add_argument("--to", dest="number")
    sms.add_argument("--text")
    call = sub.add_parser("call", help="语音呼叫控制；音频需模块硬件支持")
    call.add_argument("port")
    call.add_argument("action", choices=["list", "dial", "answer", "hangup"])
    call.add_argument("number", nargs="?")
    data = sub.add_parser("data", help="模块 PDP 上下文控制")
    data.add_argument("port")
    data.add_argument("action", choices=["status", "configure", "activate", "deactivate"])
    data.add_argument("--apn")
    data.add_argument("--cid", type=int, default=1)
    usb = sub.add_parser("usb-data", help="EC801E USB 网卡拨号控制（RNDIS/ECM）")
    usb.add_argument("port")
    usb.add_argument("action", choices=["status", "connect", "disconnect"])
    usb.add_argument("--cid", type=int, default=1)
    sub.add_parser("network", help="读取电脑网卡和移动宽带配置")
    args = parser.parse_args(argv)
    if args.command == "sms" and bool(args.number) != bool(args.text):
        parser.error("发送短信需同时提供 --to 与 --text")
    if args.command == "call" and args.action == "dial" and not args.number:
        parser.error("拨号需要电话号码")
    if args.command == "data" and args.action == "configure" and not args.apn:
        parser.error("配置需要 --apn")
    try:
        if args.command == "web":
            import uvicorn

            from .web.app import create_app
            print(f"Cellulary: http://127.0.0.1:{args.port}")
            uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)
        elif args.command == "ports":
            from .discovery import discover_ports
            output([asdict(p) for p in discover_ports()])
        elif args.command == "scan":
            from .manager import DeviceManager
            manager = DeviceManager()
            try:
                output(manager.scan())
            finally:
                manager.close()
        elif args.command == "network":
            from .network import HostNetwork
            output(HostNetwork().status())
        else:
            from .modem import Modem
            with Modem(args.port) as modem:
                if args.command == "status":
                    output(modem.status())
                elif args.command == "sms":
                    if args.number is None and args.text is None:
                        output(modem.list_sms())
                    elif args.number and args.text:
                        output(modem.send_sms(args.number, args.text))
                    else:
                        parser.error("发送短信需同时提供 --to 与 --text")
                elif args.command == "call":
                    if args.action == "dial" and not args.number:
                        parser.error("拨号需要电话号码")
                    method = "list_calls" if args.action == "list" else args.action
                    output(getattr(modem, method)(args.number) if args.action == "dial" else getattr(modem, method)())
                elif args.command == "data":
                    if args.action == "status":
                        output(modem.data_status())
                    elif args.action == "configure":
                        if not args.apn:
                            parser.error("配置需要 --apn")
                        output(modem.configure_apn(args.apn, context_id=args.cid))
                    else:
                        output(getattr(modem, args.action + "_data")(context_id=args.cid))
                elif args.command == "usb-data":
                    if args.action == "status":
                        output(modem.usb_data_status())
                    else:
                        output(getattr(modem, args.action + "_usb_data")(context_id=args.cid))
    except (Exception, KeyboardInterrupt) as exc:
        print(f"Cellulary: {exc}", file=sys.stderr)
        return 1
    return 0
