#!/usr/bin/env python3
"""Unit tests for zonefile.py"""

import unittest
from ipaddress import ip_address, IPv4Address, IPv6Address
import zonefile as zf


class TestUtilityFunctions(unittest.TestCase):
    """Test utility helper functions"""

    def test_is_array_with_list(self):
        """is_array should return True for lists"""
        self.assertTrue(zf.is_array([1, 2, 3]))
        self.assertTrue(zf.is_array([]))

    def test_is_array_with_non_list(self):
        """is_array should return False for non-lists"""
        self.assertFalse(zf.is_array("hello"))
        self.assertFalse(zf.is_array(42))
        self.assertFalse(zf.is_array(None))

    def test_to_array_with_list(self):
        """to_array should return list as-is"""
        self.assertEqual(zf.to_array([1, 2, 3]), [1, 2, 3])
        self.assertEqual(zf.to_array([]), [])

    def test_to_array_with_scalar(self):
        """to_array should wrap scalar in list"""
        self.assertEqual(zf.to_array("hello"), ["hello"])
        self.assertEqual(zf.to_array(42), [42])

    def test_to_array_with_none(self):
        """to_array should return empty list for None/empty"""
        self.assertEqual(zf.to_array(None), [])
        self.assertEqual(zf.to_array(""), [])

    def test_is_dict_str_any_valid(self):
        """is_dict_str_any should accept dict with string keys"""
        self.assertTrue(zf.is_dict_str_any({"key": "value"}))
        self.assertTrue(zf.is_dict_str_any({}))

    def test_is_dict_str_any_invalid(self):
        """is_dict_str_any should reject non-dicts or non-string keys"""
        self.assertFalse(zf.is_dict_str_any([1, 2, 3]))
        self.assertFalse(zf.is_dict_str_any("string"))
        self.assertFalse(zf.is_dict_str_any({1: "value"}))

    def test_is_dict_key_any_valid(self):
        """is_dict_key_any should accept dict with K enum keys"""
        self.assertTrue(zf.is_dict_key_any({"name": "value", "ttl": 3600}))
        self.assertTrue(zf.is_dict_key_any({}))

    def test_is_dict_key_any_invalid(self):
        """is_dict_key_any should reject non-K keys"""
        self.assertFalse(zf.is_dict_key_any({"invalid_key": "value"}))
        self.assertFalse(zf.is_dict_key_any([1, 2, 3]))

    def test_get_table_existing(self):
        """get_table should return existing table"""
        data = {"section": {"key": "value"}}
        result = zf.get_table(data, "section")
        self.assertEqual(result, {"key": "value"})

    def test_get_table_missing_returns_empty(self):
        """get_table should return empty dict for missing key"""
        data = {}
        result = zf.get_table(data, "missing")
        self.assertEqual(result, {})

    def test_get_table_with_default(self):
        """get_table should use provided default"""
        data = {}
        result = zf.get_table(data, "missing", {"default": "value"})
        self.assertEqual(result, {"default": "value"})

    def test_get_table_invalid_type(self):
        """get_table should raise TypeError for non-dict value"""
        data = {"section": "not a dict"}
        with self.assertRaises(TypeError):
            zf.get_table(data, "section")


class TestParseHostStr(unittest.TestCase):
    """Test parse_host_str function"""

    def test_parse_host_str_simple(self):
        """parse_host_str should create FQDN from hostname and zone"""
        result = zf.parse_host_str("ctx", "www", "example.com.")
        self.assertEqual(result, "www.example.com.")

    def test_parse_host_str_with_fqdn(self):
        """parse_host_str should handle FQDN input (ending with .)"""
        result = zf.parse_host_str("ctx", "www.example.com.", "example.com.")
        self.assertEqual(result, "www.example.com.")

    def test_parse_host_str_at_symbol(self):
        """parse_host_str @ should return zone apex"""
        result = zf.parse_host_str("ctx", "@", "example.com.")
        self.assertEqual(result, "example.com.")

    def test_parse_host_str_wildcard(self):
        """parse_host_str should handle wildcards"""
        result = zf.parse_host_str("ctx", "*", "example.com.")
        self.assertEqual(result, "*.example.com.")

    def test_parse_host_str_strips_whitespace(self):
        """parse_host_str should strip whitespace"""
        result = zf.parse_host_str("ctx", "  www  ", "example.com.")
        self.assertEqual(result, "www.example.com.")

    def test_parse_host_str_no_zone_name(self):
        """parse_host_str with non-FQDN and no zone_name should raise"""
        with self.assertRaises(ValueError):
            zf.parse_host_str("ctx", "www", None)


class TestValidationFunctions(unittest.TestCase):
    """Test validation/parsing functions"""

    def test_validate_int_valid(self):
        """validate_int should accept valid integers"""
        source = {zf.K.TTL: 3600}
        # Should not raise
        zf.validate_int("ctx", source, zf.K.TTL, (0, 86400))

    def test_validate_int_out_of_range(self):
        """validate_int should reject out-of-range values"""
        source = {zf.K.TTL: 999999}
        with self.assertRaises(ValueError):
            zf.validate_int("ctx", source, zf.K.TTL, (0, 86400))

    def test_validate_int_wrong_type(self):
        """validate_int should reject non-integer"""
        source = {zf.K.TTL: "3600"}
        with self.assertRaises(ValueError):
            zf.validate_int("ctx", source, zf.K.TTL, (0, 86400))

    def test_validate_int_missing(self):
        """validate_int should reject missing key"""
        source = {}
        with self.assertRaises(ValueError):
            zf.validate_int("ctx", source, zf.K.TTL, (0, 86400))

    def test_validate_bool_valid(self):
        """validate_bool should accept boolean"""
        source = {zf.K.WITH_PTR: True}
        # Should not raise
        zf.validate_bool("ctx", source, zf.K.WITH_PTR)

    def test_validate_bool_invalid(self):
        """validate_bool should reject non-boolean"""
        source = {zf.K.WITH_PTR: "true"}
        with self.assertRaises(ValueError):
            zf.validate_bool("ctx", source, zf.K.WITH_PTR)

    def test_validate_email_valid(self):
        """validate_email should accept properly formatted email"""
        source = {zf.K.EMAIL: "admin.example.com."}
        # Should not raise
        zf.validate_email("ctx", source)

    def test_validate_email_missing_dot(self):
        """validate_email should reject email without trailing dot"""
        source = {zf.K.EMAIL: "admin.example.com"}
        with self.assertRaises(ValueError):
            zf.validate_email("ctx", source)

    def test_validate_host_valid(self):
        """validate_host should accept valid FQDN"""
        source = {zf.K.NAME: "www.example.com."}
        # Should not raise
        zf.validate_host("ctx", source, zf.K.NAME)

    def test_validate_host_too_long(self):
        """validate_host should reject names > 253 chars"""
        long_name = "a" * 250 + ".com."
        source = {zf.K.NAME: long_name}
        with self.assertRaises(ValueError):
            zf.validate_host("ctx", source, zf.K.NAME)

    def test_validate_host_missing_trailing_dot(self):
        """validate_host should reject non-FQDN"""
        source = {zf.K.NAME: "www.example.com"}
        with self.assertRaises(ValueError):
            zf.validate_host("ctx", source, zf.K.NAME)


class TestConvertStrToIp(unittest.TestCase):
    """Test convert_str_to_ip function"""

    def test_convert_ipv4(self):
        """convert_str_to_ip should convert IPv4 addresses"""
        result = zf.convert_str_to_ip("ctx", "192.168.1.1")
        self.assertIsInstance(result, IPv4Address)
        self.assertEqual(str(result), "192.168.1.1")

    def test_convert_ipv6(self):
        """convert_str_to_ip should convert IPv6 addresses"""
        result = zf.convert_str_to_ip("ctx", "2001:db8::1")
        self.assertIsInstance(result, IPv6Address)
        self.assertEqual(str(result), "2001:db8::1")

    def test_convert_invalid_ip(self):
        """convert_str_to_ip should reject invalid IP"""
        with self.assertRaises(ValueError):
            zf.convert_str_to_ip("ctx", "not an ip")


class TestCalcSerial(unittest.TestCase):
    """Test calc_serial function"""

    def test_calc_serial_increments(self):
        """calc_serial should increment by 1"""
        from datetime import date

        today = date.today()
        date_serial = int(today.strftime("%Y%m%d00"))
        new_serial = zf.calc_serial(date_serial)
        self.assertEqual(new_serial, date_serial + 1)

    def test_calc_serial_uses_date_when_higher(self):
        """calc_serial should use current date format when higher"""
        from datetime import datetime

        now = datetime.now()
        expected_min = now.year * 1000000 + now.month * 10000 + now.day * 100

        old_serial = 0
        new_serial = zf.calc_serial(old_serial)
        self.assertGreaterEqual(new_serial, expected_min)


class TestParseNameserver(unittest.TestCase):
    """Test parse_nameserver function"""

    def setUp(self):
        """Set up test zone config"""
        self.zone = {
            zf.K.NAME: "example.com.",
            zf.K.TTL: 10800,
        }

    def test_parse_nameserver_simple_string(self):
        """parse_nameserver should handle simple string"""
        ns_records = zf.parse_nameserver("ctx", "ns1", self.zone)

        self.assertEqual(len(ns_records), 1)
        self.assertEqual(ns_records[0].name, "ns1.example.com.")
        self.assertEqual(ns_records[0].ttl, 10800)

    def test_parse_nameserver_list(self):
        """parse_nameserver should handle list of nameservers"""
        ns_records = zf.parse_nameserver("ctx", ["ns1", "ns2"], self.zone)

        self.assertEqual(len(ns_records), 2)
        self.assertEqual(ns_records[0].name, "ns1.example.com.")
        self.assertEqual(ns_records[1].name, "ns2.example.com.")

    def test_parse_nameserver_with_ttl(self):
        """parse_nameserver should handle dict with custom TTL"""
        ns_records = zf.parse_nameserver("ctx", {"name": "ns1", "ttl": 7200}, self.zone)

        self.assertEqual(ns_records[0].ttl, 7200)

    def test_parse_nameserver_missing(self):
        """parse_nameserver should raise on None"""
        with self.assertRaises(ValueError):
            zf.parse_nameserver("ctx", None, self.zone)


class TestParseMX(unittest.TestCase):
    """Test parse_mx function"""

    def setUp(self):
        self.zone = {
            zf.K.NAME: "example.com.",
            zf.K.TTL: 10800,
            zf.K.MX_PRIO: 10,
        }

    def test_parse_mx_simple_string(self):
        """parse_mx should handle simple string"""
        mx_records = zf.parse_mx("ctx", "mail", self.zone)

        self.assertEqual(len(mx_records), 1)
        self.assertEqual(mx_records[0].name, "mail.example.com.")
        self.assertEqual(mx_records[0].prio, 10)
        self.assertEqual(mx_records[0].ttl, 10800)

    def test_parse_mx_with_custom_priority(self):
        """parse_mx should handle dict with custom priority"""
        mx_records = zf.parse_mx("ctx", {"name": "mail", "prio": 20}, self.zone)

        self.assertEqual(mx_records[0].prio, 20)

    def test_parse_mx_list(self):
        """parse_mx should handle list of MX records"""
        mx_records = zf.parse_mx("ctx", ["mail1", "mail2"], self.zone)

        self.assertEqual(len(mx_records), 2)

    def test_parse_mx_missing_returns_empty(self):
        """parse_mx should return empty list when mx key missing"""
        mx_records = zf.parse_mx("ctx", None, self.zone)
        self.assertEqual(len(mx_records), 0)


class TestIntegration(unittest.TestCase):
    """Integration tests with complete TOML data"""

    def test_parse_minimal_zone(self):
        """parse should handle minimal valid TOML"""
        import tomllib

        toml_data = """
[defaults]
email = "admin@example.com"
nameserver = "ns1.example.com."

[[zone]]
name = "example.com"

[zone.hosts]
www = "192.168.1.1"
"""
        data = tomllib.loads(toml_data)
        zones = zf.parse(data, {**zf.PROGRAM_DEFAULTS, zf.K.SERIAL: 2025010100})

        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0][zf.K.NAME], "example.com.")
        self.assertGreater(len(zones[0][zf.K.A]), 0)

    def test_parse_with_multiple_zones(self):
        """parse should handle multiple zones"""
        import tomllib

        toml_data = """
[defaults]
email = "admin@example.com"
nameserver = "ns1.example.com."

[[zone]]
name = "example.com"
[zone.hosts]
www = "192.168.1.1"

[[zone]]
name = "example.org"
[zone.hosts]
mail = "192.168.1.2"
"""
        data = tomllib.loads(toml_data)
        zones = zf.parse(data, {**zf.PROGRAM_DEFAULTS, zf.K.SERIAL: 2025010100})

        self.assertEqual(len(zones), 2)
        self.assertEqual(zones[0][zf.K.NAME], "example.com.")
        self.assertEqual(zones[1][zf.K.NAME], "example.org.")

    def test_parse_with_mx_records(self):
        """parse should handle MX records"""
        import tomllib

        toml_data = """
[defaults]
email = "admin@example.com"
nameserver = "ns1.example.com."

[[zone]]
name = "example.com"
mx = ["mail1", "mail2"]

[zone.hosts]
www = "192.168.1.1"
"""
        data = tomllib.loads(toml_data)
        zones = zf.parse(data, {**zf.PROGRAM_DEFAULTS, zf.K.SERIAL: 2025010100})

        self.assertEqual(len(zones[0][zf.K.MX]), 2)

    def test_parse_with_cnames(self):
        """parse should handle CNAME records"""
        import tomllib

        toml_data = """
[defaults]
email = "admin@example.com"
nameserver = "ns1.example.com."

[[zone]]
name = "example.com"

[zone.hosts]
www = "192.168.1.1"

[zone.cname]
web = "www"
ftp = "www"
"""
        data = tomllib.loads(toml_data)
        zones = zf.parse(data, {**zf.PROGRAM_DEFAULTS, zf.K.SERIAL: 2025010100})

        self.assertEqual(len(zones[0][zf.K.CNAME]), 2)


if __name__ == "__main__":
    unittest.main()
