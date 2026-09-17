from cellulary.network import annotate_adapters, parse_adapters, parse_mbn_interfaces, usb_parent


def test_localized_mbn_interfaces():
    assert parse_mbn_interfaces("""
There is 1 interface on the system:
    Name : 手机网络 18
    Description : Generic Mobile Broadband Adapter
    State : Connected
    Provider Name : CMLink
""") == [{"name": "手机网络 18", "description": "Generic Mobile Broadband Adapter", "state": "Connected", "kind": "mbn", "provider": "CMLink"}]
    assert parse_mbn_interfaces("    名称 : 手机网络\n    状态 : 已连接") == [{"name": "手机网络", "state": "已连接", "kind": "mbn"}]


def test_interface_names_can_contain_spaces():
    assert parse_adapters("Enabled        Connected      Dedicated        以太网 7\nDisabled       Disconnected   Dedicated        WLAN 6") == [
        {"Name": "以太网 7", "Status": "Connected", "InterfaceDescription": "Dedicated"},
        {"Name": "WLAN 6", "Status": "Disconnected", "InterfaceDescription": "Dedicated"},
    ]


def test_usb_parent_mapping_does_not_confuse_identical_modem_macs():
    first = r"USB\VID_2C7C&PID_0903&MI_00\9&abc&1&0000"
    second = r"USB\VID_2C7C&PID_0903&MI_00\9&def&1&0000"
    serial = r"USB\VID_2C7C&PID_0903&MI_03\9&abc&1&0003"
    assert usb_parent(first) == usb_parent(serial)
    assert usb_parent(first) != usb_parent(second)
    assert usb_parent("PCI\\unrelated") is None
    adapters = annotate_adapters([
        {"Name": "Cell 1", "Status": "Up", "PnPDeviceID": first, "MacAddress": "3089846A96AB", "ipv4": [{"address": "192.168.43.100", "state": "Preferred"}], "gateways": ["192.168.43.1"]},
        {"Name": "Cell 2", "PnPDeviceID": second, "MacAddress": "3089846A96AB", "ipv4": [{"address": "169.254.2.3", "state": "Tentative"}]},
        {"Name": "Unrelated", "PnPDeviceID": None},
    ], {usb_parent(serial): "COM11", usb_parent(second): "COM12"})
    assert [a["device_port"] for a in adapters] == ["COM11", "COM12", None]
    assert adapters[0]["conflicts"] == ["Cell 2"]
    assert adapters[0]["host_configured"] is True
    assert adapters[1]["host_configured"] is False
    assert adapters[0]["internet_verified"] is False


def test_tentative_address_with_gateway_is_not_usable():
    adapter = {"Name": "Cell", "Status": "Up", "ipv4": [{"address": "192.168.43.100", "state": "Tentative"}], "gateways": ["192.168.43.1"]}
    assert annotate_adapters([adapter], {})[0]["host_configured"] is False


def test_disconnected_static_adapter_is_not_ready():
    adapter = {"Name": "Cell", "Status": "Down", "ipv4": [{"address": "192.168.43.100", "state": "Preferred"}], "gateways": ["192.168.43.1"]}
    assert annotate_adapters([adapter], {})[0]["host_configured"] is False
