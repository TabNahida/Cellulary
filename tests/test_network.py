from cellulary.network import parse_adapters, parse_mbn_interfaces


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
