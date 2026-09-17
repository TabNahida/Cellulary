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
    parser = argparse.ArgumentParser(prog="cellulary", description="Cellular modem toolkit and local web console")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ports", help="List Quectel AT ports without opening them")
    sub.add_parser("scan", help="Identify all devices and read status")
    serve = sub.add_parser("web", help="Run the local web console")
    serve.add_argument("--port", type=int, default=8765)
    status = sub.add_parser("status", help="Read status from an AT port")
    status.add_argument("port")
    sms = sub.add_parser("sms", help="Read or send SMS")
    sms.add_argument("port")
    sms.add_argument("--to", dest="number")
    sms.add_argument("--text")
    call = sub.add_parser("call", help="Control voice calls; audio requires module hardware support")
    call.add_argument("port")
    call.add_argument("action", choices=["list", "dial", "answer", "hangup"])
    call.add_argument("number", nargs="?")
    data = sub.add_parser("data", help="Control modem PDP contexts")
    data.add_argument("port")
    data.add_argument("action", choices=["status", "configure", "activate", "deactivate"])
    data.add_argument("--apn")
    data.add_argument("--cid", type=int, default=1)
    usb = sub.add_parser("usb-data", help="Control USB data sessions (RNDIS/ECM)")
    usb.add_argument("port")
    usb.add_argument("action", choices=["status", "connect", "disconnect"])
    usb.add_argument("--cid", type=int, default=1)
    network = sub.add_parser("network", help="Read host adapters and mobile broadband profiles")
    network.add_argument("--port", help="Only show host adapters belonging to this AT port")
    numbers = sub.add_parser("numbers", help="Read subscriber numbers stored on the SIM")
    numbers.add_argument("port")
    gnss = sub.add_parser("gnss", help="Read or control supported GNSS receivers")
    gnss.add_argument("port")
    gnss.add_argument("action", choices=["status", "start", "stop", "location"])
    args = parser.parse_args(argv)
    if args.command == "sms" and bool(args.number) != bool(args.text):
        parser.error("Sending SMS requires both --to and --text")
    if args.command == "call" and args.action == "dial" and not args.number:
        parser.error("Dial requires a phone number")
    if args.command == "data" and args.action == "configure" and not args.apn:
        parser.error("Configuration requires --apn")
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
            output(HostNetwork().device_status(args.port) if args.port else HostNetwork().status())
        else:
            from .modem import Modem
            with Modem(args.port) as modem:
                if args.command == "status":
                    output(modem.status())
                elif args.command == "numbers":
                    output(modem.subscriber_numbers())
                elif args.command == "gnss":
                    method = {"status": "gnss_status", "start": "start_gnss", "stop": "stop_gnss", "location": "gnss_location"}[args.action]
                    output(getattr(modem, method)())
                elif args.command == "sms":
                    if args.number is None and args.text is None:
                        output(modem.list_sms())
                    elif args.number and args.text:
                        output(modem.send_sms(args.number, args.text))
                    else:
                        parser.error("Sending SMS requires both --to and --text")
                elif args.command == "call":
                    if args.action == "dial" and not args.number:
                        parser.error("Dial requires a phone number")
                    method = "list_calls" if args.action == "list" else args.action
                    output(getattr(modem, method)(args.number) if args.action == "dial" else getattr(modem, method)())
                elif args.command == "data":
                    if args.action == "status":
                        output(modem.data_status())
                    elif args.action == "configure":
                        if not args.apn:
                            parser.error("Configuration requires --apn")
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
