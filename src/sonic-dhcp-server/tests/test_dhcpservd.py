import pytest
import psutil
import signal
import sys
import time
from common_utils import MockProc
from dhcp_server.common.utils import DhcpDbConnector
from dhcp_server.dhcpservd.dhcp_cfggen import DhcpServCfgGenerator
from dhcp_server.dhcpservd.dhcpservd import DhcpServd
from swsscommon import swsscommon
from unittest.mock import patch, call, MagicMock

AF_INET = 2
AF_INET6 = 10


def test_dump_dhcp4_config(mock_swsscommon_dbconnector_init):
    with patch("dhcp_server.dhcpservd.dhcp_cfggen.DhcpServCfgGenerator.generate", return_value="dummy_config") as mock_generate, \
         patch("dhcp_server.dhcpservd.dhcpservd.DhcpServd._notify_kea_dhcp4_proc", MagicMock()) as mock_notify_kea_dhcp4_proc:
        dhcp_db_connector = DhcpDbConnector()
        dhcp_cfg_generator = DhcpServCfgGenerator(dhcp_db_connector,
                                                  port_map_path="tests/test_data/port-name-alias-map.txt",
                                                  kea_conf_template_path="tests/test_data/kea-dhcp4.conf.j2")
        dhcpservd = DhcpServd(dhcp_cfg_generator, dhcp_db_connector, kea_dhcp4_config_path="/tmp/kea-dhcp4.conf")
        dhcpservd.dump_dhcp4_config()
        # Verfiy whether generate() func of dhcp_cfggen is called
        mock_generate.assert_called_once_with()
        # Verify whether notify func of dhcpservd is called, which is expected to call after new config generated
        mock_notify_kea_dhcp4_proc.assert_called_once_with()


@pytest.mark.parametrize("process_list", [["proc1", "proc2", "kea-dhcp4"], ["proc1", "proc2"]])
def test_notify_kea_dhcp4_proc(process_list, mock_swsscommon_dbconnector_init, mock_get_render_template,
                               mock_parse_port_map_alias):
    proc_list = [MockProc(process_name) for process_name in process_list]
    with patch.object(psutil, "process_iter", return_value=proc_list), \
         patch.object(MockProc, "send_signal", MagicMock()) as mock_send_signal:
        dhcp_db_connector = DhcpDbConnector()
        dhcp_cfg_generator = DhcpServCfgGenerator(dhcp_db_connector)
        dhcpservd = DhcpServd(dhcp_cfg_generator, dhcp_db_connector)
        dhcpservd._notify_kea_dhcp4_proc()
        if "kea-dhcp4" in process_list:
            mock_send_signal.assert_has_calls([
                call(signal.SIGHUP)
            ])
        else:
            mock_send_signal.assert_not_called()


@pytest.mark.parametrize("mock_intf", [True, False])
def test_update_dhcp_server_ip(mock_swsscommon_dbconnector_init, mock_parse_port_map_alias, mock_get_render_template,
                               mock_intf):
    mock_interface = {} if not mock_intf else {
        "eth0": [
            MockIntf(AF_INET6, "fd00::2"),
            MockIntf(AF_INET, "240.127.1.2")
        ]
    }
    with patch.object(psutil, "net_if_addrs", return_value=mock_interface), \
         patch.object(swsscommon.DBConnector, "hset") as mock_hset, \
         patch.object(time, "sleep") as mock_sleep, \
         patch.object(sys, "exit") as mock_exit:
        dhcp_db_connector = DhcpDbConnector()
        dhcp_cfg_generator = DhcpServCfgGenerator(dhcp_db_connector)
        dhcpservd = DhcpServd(dhcp_cfg_generator, dhcp_db_connector)
        dhcpservd._update_dhcp_server_ip()
        if mock_intf:
            mock_hset.assert_has_calls([
                call("DHCP_SERVER_IPV4_SERVER_IP|eth0", "ip", "240.127.1.2")
            ])
        else:
            mock_hset.assert_not_called()
            mock_exit.assert_called_once_with(1)
            mock_sleep.assert_has_calls([call(5) for _ in range(10)])


def test_start(mock_swsscommon_dbconnector_init, mock_parse_port_map_alias, mock_get_render_template):
    with patch.object(DhcpServd, "dump_dhcp4_config") as mock_dump, \
         patch.object(DhcpServd, "_update_dhcp_server_ip") as mock_update_dhcp_server_ip:
        dhcp_db_connector = DhcpDbConnector()
        dhcp_cfg_generator = DhcpServCfgGenerator(dhcp_db_connector)
        dhcpservd = DhcpServd(dhcp_cfg_generator, dhcp_db_connector)
        dhcpservd.start()
        mock_dump.assert_called_once_with()
        mock_update_dhcp_server_ip.assert_called_once_with()


class MockIntf(object):
    def __init__(self, family, address):
        self.family = family
        self.address = address
