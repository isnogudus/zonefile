import unittest
from datetime import datetime
import io
from ipaddress import IPv4Address, IPv6Address
import yaml
import pprint

import zonefile


class TestZonefile(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pp = pprint.PrettyPrinter()
        self.print = self.pp.pprint

    def test_serial_calc(self):
        now = datetime.now()
        serial = now.year * 1000000 + now.month * 10000 + now.day * 100
        self.assertEqual(zonefile.calc_serial(0), serial)

    def test_serial_calc_next(self):
        now = datetime.now()
        old_serial = now.year * 1000000 + now.month * 10000 + now.day * 100
        self.assertEqual(zonefile.calc_serial(old_serial), old_serial + 1)

    def test_serial_supercede(self):
        """given serial supercedes calc_serial"""
        serial = 9900000000
        self.assertEqual(zonefile.calc_serial(serial), serial + 1)

    def test_serial_old(self):
        """calc_serial generates serial from actual date feeding with old date"""
        serial = 1990010203
        self.assertGreater(zonefile.calc_serial(serial), serial + 1)

    def test_serial_zero(self):
        """calc_serial generates serial from date"""
        serial = 0
        self.assertGreater(zonefile.calc_serial(serial), serial + 1)

    def test_serial_increment(self):
        """every call to calc_serial increments serial at least by one"""
        serial = zonefile.calc_serial(0)
        self.assertEqual(zonefile.calc_serial(serial), serial + 1)

    def process(self, yaml_str: str, serial, format="unbound"):
        parsed_input = yaml.safe_load(yaml_str)
        writer = io.StringIO()
        zonefile.process(parsed_input, writer, serial, format)
        writer.seek(0)
        return tuple(map(lambda line: line.split(), writer.readlines()))

    def asseert_soa(
        self,
        soa,
        domain,
        nameserver,
        email,
        serial,
        ttl=zonefile.TTL,
        refresh=zonefile.REFRESH,
        retry=zonefile.RETRY,
        expire=zonefile.EXPIRE,
        nrc_ttl=zonefile.NRC_TTL,
    ):
        self.assertEqual(
            soa,
            [
                "local-data:",
                f'"{domain}',
                str(ttl),
                "IN",
                "SOA",
                nameserver,
                email,
                str(serial),
                str(refresh),
                str(retry),
                str(expire),
                f'{nrc_ttl}"',
            ],
        )

    def assert_header(
        self,
        header,
        domain,
        nameserver,
        email,
        serial,
        ttl=zonefile.TTL,
        refresh=zonefile.REFRESH,
        retry=zonefile.RETRY,
        expire=zonefile.EXPIRE,
        nrc_ttl=zonefile.NRC_TTL,
    ):
        self.assertEqual(header[0], ["server:"])
        self.assertEqual(header[1], [])
        self.assertEqual(header[2], ["local-zone:", domain, "static"])
        self.asseert_soa(header[3], domain, nameserver, email, serial, ttl, refresh, retry, expire, nrc_ttl)

    def assert_a_record(self, data, name, ip_addr):
        self.assertIn(["local-data:", f'"{name}', "IN", "A", f'{ip_addr}"'], data)

    def assert_aaaa_record(self, data, name, ip_addr):
        self.assertIn(["local-data:", f'"{name}', "IN", "AAAA", f'{ip_addr}"'], data)

    def assert_ptr_record(self, data, name, ip_addr):
        self.assertIn(["local-data-ptr:", f'"{ip_addr}', f'{name}"'], data)

    def assert_a_ptr_records(self, data, name, ip_addr):
        self.assert_a_record(data, name, ip_addr)
        self.assert_ptr_record(data, name, ip_addr)

    def assert_aaaa_ptr_records(self, data, name, ip_addr):
        self.assert_aaaa_record(data, name, ip_addr)
        self.assert_ptr_record(data, name, ip_addr)

    def assert_ns_record(self, data, domain, name):
        self.assertIn(["local-data:", f'"{domain}', "IN", "NS", f'{name}"'], data)

    def assert_mx_record(self, data, domain, name, prio):
        self.assertIn(["local-data:", f'"{domain}', "IN", "MX", str(prio), f'{name}"'], data)

    def test_minimal(self):
        yaml_str = """
        home.arpa:
          email: test@home.arpa
          nameserver: ns1.home.arpa.
        """
        serial = 4711

        output = self.process(yaml_str, serial)

        self.assert_header(output, "home.arpa.", "ns1.home.arpa.", "test.home.arpa.", serial)
        self.assert_ns_record(output, "home.arpa.", "ns1.home.arpa.")

    def test_ns_array(self):
        yaml_str = """
        home.arpa:
          email: test@home.arpa
          nameserver: 
            - ns1.home.arpa.
            - ns2
            - ns3.home.arpa.
        """
        serial = 4711

        output = self.process(yaml_str, serial)

        self.assertEqual(len(output), 7)

        self.assert_header(output, "home.arpa.", "ns1.home.arpa.", "test.home.arpa.", serial)
        self.assert_ns_record(output, "home.arpa.", "ns1.home.arpa.")
        self.assert_ns_record(output, "home.arpa.", "ns2.home.arpa.")
        self.assert_ns_record(output, "home.arpa.", "ns3.home.arpa.")

    def test_ns_obj(self):
        yaml_str = """
        home.arpa:
          email: test@home.arpa
          nameserver: 
            ns1.home.arpa.: 192.168.0.1
            ns2.home.arpa.: 192.168.0.2
            ns3: 192.168.0.3
        """
        serial = 4711

        output = self.process(yaml_str, serial)

        self.assertEqual(len(output), 13)

        self.assert_header(output, "home.arpa.", "ns1.home.arpa.", "test.home.arpa.", serial)
        self.assert_ns_record(output, "home.arpa.", "ns1.home.arpa.")
        self.assert_ns_record(output, "home.arpa.", "ns2.home.arpa.")
        self.assert_ns_record(output, "home.arpa.", "ns3.home.arpa.")
        self.assert_a_ptr_records(output, "ns1.home.arpa.", "192.168.0.1")
        self.assert_a_ptr_records(output, "ns2.home.arpa.", "192.168.0.2")
        self.assert_a_ptr_records(output, "ns3.home.arpa.", "192.168.0.3")

    def test_ns_host_expansion(self):
        yaml_str = """
        home.arpa:
          email: test@home.arpa
          nameserver: ns1
        """
        serial = 4711

        output = self.process(yaml_str, serial)

        self.assert_header(output, "home.arpa.", "ns1.home.arpa.", "test.home.arpa.", serial)
        self.assert_ns_record(output, "home.arpa.", "ns1.home.arpa.")

    def test_ns_ignore_duplicate_ip(self):
        yaml_str = """
        home.arpa:
          email: test@home.arpa
          nameserver: 
            ns1.home.arpa.: 192.168.0.1
          hosts:
            host1: [ns1,192.168.0.1]
        """
        serial = 4711

        output = self.process(yaml_str, serial)

        self.assertEqual(len(output), 8)

        self.assert_header(output, "home.arpa.", "ns1.home.arpa.", "test.home.arpa.", serial)
        self.assert_ns_record(output, "home.arpa.", "ns1.home.arpa.")
        self.assert_a_record(output, "ns1.home.arpa.", "192.168.0.1")
        self.assert_a_ptr_records(output, "host1.home.arpa.", "192.168.0.1")

    def test_ns_exception_duplicate_ip(self):
        yaml_str = """
        home.arpa:
          email: test@home.arpa
          nameserver: 
            ns1.home.arpa.: 192.168.0.2
          hosts:
            host1: [ns1,192.168.0.1]
        """
        serial = 4711

        with self.assertRaises(ValueError):
            self.process(yaml_str, serial)

    def test_to_ip(self):
        self.assertEqual(zonefile.to_ip(2), 2)
        self.assertEqual(zonefile.to_ip("host1"), "host1")
        self.assertIsInstance(zonefile.to_ip("host"), str)
        self.assertIsInstance(zonefile.to_ip("192.168.0.1"), IPv4Address)
        self.assertIsInstance(zonefile.to_ip("fe80::"), IPv6Address)

    def test_mx(self):
        yaml_str = """
        home.arpa:
          email: test@home.arpa
          nameserver: 
            ns1.home.arpa.: 192.168.0.1
          mx:
            mail: [10,192.168.0.2]
        """
        serial = 4711

        output = self.process(yaml_str, serial)

        self.assertEqual(len(output), 10)

        self.assert_header(output, "home.arpa.", "ns1.home.arpa.", "test.home.arpa.", serial)
        self.assert_ns_record(output, "home.arpa.", "ns1.home.arpa.")
        self.assert_mx_record(output, "home.arpa.", "mail.home.arpa.", 10)
        self.assert_a_ptr_records(output, "ns1.home.arpa.", "192.168.0.1")
        self.assert_a_ptr_records(output, "mail.home.arpa.", "192.168.0.2")

    def test_mx_ignore_duplicate_ip(self):
        yaml_str = """
        home.arpa:
          email: test@home.arpa
          nameserver: 
            ns1.home.arpa.: 192.168.0.1
          mx:
            mail: [10,192.168.0.2]
          hosts:
            host1: [mail, 192.168.0.2]
        """
        serial = 4711

        output = self.process(yaml_str, serial)

        self.assertEqual(len(output), 11)

        self.assert_header(output, "home.arpa.", "ns1.home.arpa.", "test.home.arpa.", serial)
        self.assert_ns_record(output, "home.arpa.", "ns1.home.arpa.")
        self.assert_mx_record(output, "home.arpa.", "mail.home.arpa.", 10)
        self.assert_a_ptr_records(output, "ns1.home.arpa.", "192.168.0.1")
        self.assert_a_record(output, "mail.home.arpa.", "192.168.0.2")
        self.assert_a_ptr_records(output, "host1.home.arpa.", "192.168.0.2")


if __name__ == "__main__":
    unittest.main()
