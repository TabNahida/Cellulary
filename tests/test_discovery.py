from types import SimpleNamespace

from cellulary.discovery import discover_ports


def port(device, description, vid=0x2C7C, pid=0x0903, interface=None):
    return SimpleNamespace(device=device, description=description, vid=vid, pid=pid, interface=interface)


def test_only_labelled_quectel_at_interfaces_are_enumerated():
    found = discover_ports([
        port("COM23", "Quectel USB AT Port", pid=0x6005),
        port("COM9", "Quectel USB AT Port"),
        port("COM2", "Quectel USB DIAG Port"),
        port("COM3", "Quectel USB NMEA Port"),
        port("COM4", "Quectel USB Modem"),
        port("COM5", "USB Serial Device"),
        port("COM6", "Other AT Port", vid=0x1234),
        port("COM7", "Quectel AT DIAG Port"),
        port("COM10", "USB Serial Device", interface="Quectel USB AT Port"),
    ])
    assert [p.port for p in found] == ["COM9", "COM10", "COM23"]
    assert found[-1].to_dict()["pid"] == 0x6005


def test_linux_unknown_interfaces_are_not_blindly_probed():
    assert discover_ports([port("/dev/ttyUSB2", "EC801E")]) == []
