#!/usr/bin/env python
import psutil
import signal
import time
import sys
import syslog
from .dhcp_cfggen import DhcpServCfgGenerator
from .dhcp_lease import LeaseManager
from dhcp_server.common.utils import DhcpDbConnector

KEA_DHCP4_CONFIG = "/etc/kea/kea-dhcp4.conf"
KEA_DHCP4_PROC_NAME = "kea-dhcp4"
KEA_LEASE_FILE_PATH = "/tmp/kea-lease.csv"
REDIS_SOCK_PATH = "/var/run/redis/redis.sock"
DHCP_SERVER_IPV4_SERVER_IP = "DHCP_SERVER_IPV4_SERVER_IP"
DHCP_SERVER_INTERFACE = "eth0"
AF_INET = 2


class DhcpServd(object):
    def __init__(self, dhcp_cfg_generator, db_connector, kea_dhcp4_config_path=KEA_DHCP4_CONFIG):
        self.dhcp_cfg_generator = dhcp_cfg_generator
        self.db_connector = db_connector
        self.kea_dhcp4_config_path = kea_dhcp4_config_path

    def _notify_kea_dhcp4_proc(self):
        """
        Send SIGHUP signal to kea-dhcp4 process
        """
        for proc in psutil.process_iter():
            if KEA_DHCP4_PROC_NAME in proc.name():
                proc.send_signal(signal.SIGHUP)
                break

    def dump_dhcp4_config(self):
        """
        Generate kea-dhcp4 config file and dump it to config folder
        """
        kea_dhcp4_config = self.dhcp_cfg_generator.generate()
        with open(self.kea_dhcp4_config_path, "w") as write_file:
            write_file.write(kea_dhcp4_config)
            # After refresh kea-config, we need to SIGHUP kea-dhcp4 process to read new config
            self._notify_kea_dhcp4_proc()

    def _update_dhcp_server_ip(self):
        """
        Add ip address of "eth0" inside dhcp_server container as dhcp_server_ip into state_db
        """
        dhcp_server_ip = None
        for _ in range(10):
            dhcp_interface = psutil.net_if_addrs().get(DHCP_SERVER_INTERFACE, [])
            for address in dhcp_interface:
                if address.family == AF_INET:
                    dhcp_server_ip = address.address
                    self.db_connector.state_db.hset("{}|{}".format(DHCP_SERVER_IPV4_SERVER_IP, DHCP_SERVER_INTERFACE),
                                                    "ip", dhcp_server_ip)
                    return
            else:
                time.sleep(5)
                syslog.syslog(syslog.LOG_INFO, "Cannot get ip address of {}".format(DHCP_SERVER_INTERFACE))
        sys.exit(1)

    def start(self):
        self.dump_dhcp4_config()
        self._update_dhcp_server_ip()
        lease_manager = LeaseManager(self.db_connector, KEA_LEASE_FILE_PATH)
        lease_manager.start()

        # TODO Add config db subcribe to re-generate kea-dhcp4 config after config_db change.

    def wait(self):
        while True:
            time.sleep(5)


def main():
    dhcp_db_connector = DhcpDbConnector(redis_sock=REDIS_SOCK_PATH)
    dhcp_cfg_generator = DhcpServCfgGenerator(dhcp_db_connector)
    dhcpservd = DhcpServd(dhcp_cfg_generator, dhcp_db_connector)
    dhcpservd.start()
    dhcpservd.wait()


if __name__ == "__main__":
    main()
