#!/usr/bin/env python3
import argparse
from collections import defaultdict
from contextlib import nullcontext, suppress
from enum import Enum
from io import StringIO
import os
from pathlib import Path
import sys
from datetime import datetime
from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network, ip_network
import tomllib
from types import MappingProxyType
from typing import (
    Any,
    Mapping,
    NamedTuple,
    NoReturn,
    Tuple,
    List,
    Dict,
    Type,
    TypeGuard,
    TypeVar,
    cast,
)

MAX_INT16_SIGNED = 2**15 - 1
MAX_INT16_UNSIGNED = 2**16 - 1
MAX_INT32_SIGNED = 2**31 - 1
MAX_INT32_UNSIGNED = 2**32 - 1

# Output formatting constants
UNBOUND_COLUMN_WIDTH = 46  # Column width for DNS names in unbound format
NSD_INDENT_SPACES = 32     # Indentation for NSD zone file records


class LIMITS(Tuple[int, int], Enum):
    PORT = (0, MAX_INT16_UNSIGNED)
    SERIAL = (0, MAX_INT32_UNSIGNED)
    REFRESH = (0, MAX_INT32_SIGNED)
    RETRY = (0, MAX_INT32_SIGNED)
    EXPIRE = (0, MAX_INT32_SIGNED)
    NRC_TTL = (0, MAX_INT32_UNSIGNED)
    TTL = (0, MAX_INT32_UNSIGNED)
    SRV_PRIO = (0, MAX_INT16_UNSIGNED)
    SRV_WEIGHT = (0, MAX_INT16_UNSIGNED)
    MX_PRIO = (0, MAX_INT16_SIGNED)


class K(str, Enum):
    A = "a"
    ALIAS = "alias"
    CNAME = "cname"
    EMAIL = "email"
    EXPIRE = "expire"
    HOSTS = "hosts"
    IP = "ip"
    MX = "mx"
    MX_PRIO = "mx-prio"
    NAME = "name"
    NAMESERVER = "nameserver"
    NETWORK = "network"
    NRC_TTL = "nrc-ttl"
    PORT = "port"
    PRIO = "prio"
    PTR = "ptr"
    REFRESH = "refresh"
    RETRY = "retry"
    SERIAL = "serial"
    SPLIT = "split"
    SRV = "srv"
    SRV_PRIO = "srv-prio"
    SRV_WEIGHT = "srv-weight"
    TARGET = "target"
    TTL = "ttl"
    WEIGHT = "weight"
    WITH_PTR = "with-ptr"
    ZONE_NAME = "zone-name"


PROGRAM_DEFAULTS: Mapping[K, Any] = {
    K.EXPIRE: 1209600,
    K.MX_PRIO: 0,
    K.NRC_TTL: 3600,
    K.REFRESH: 7200,
    K.RETRY: 3600,
    K.SRV_PRIO: 5,
    K.SRV_WEIGHT: 10,
    K.TTL: 10800,
    K.WITH_PTR: True,
}


DEFAULT_SECTION_KEYS = (
    K.EMAIL,
    K.EXPIRE,
    K.MX,
    K.MX_PRIO,
    K.NAMESERVER,
    K.NRC_TTL,
    K.REFRESH,
    K.RETRY,
    K.SERIAL,
    K.SRV_PRIO,
    K.SRV_WEIGHT,
    K.TTL,
    K.WITH_PTR,
)

ZONE_SECTION_KEYS = (K.A, K.CNAME, K.NAME, K.SRV) + DEFAULT_SECTION_KEYS
REVERSE_SECTION_KEYS = DEFAULT_SECTION_KEYS

NS_SECTION_KEYS = (K.NAME, K.TTL)
MX_SECTION_KEYS = (K.NAME, K.TTL, (K.PRIO, K.MX_PRIO))
HOST_SECTION_KEYS = (K.ALIAS, K.IP, K.TTL, K.WITH_PTR)
SRV_SECTION_KEYS = (K.NAME, K.TARGET, K.TTL, K.PORT, (K.PRIO, K.SRV_PRIO), (K.WEIGHT, K.SRV_WEIGHT))
CNAME_SECTION_KEYS = (K.NAME, K.TARGET, K.TTL)


class RecordMeta(NamedTuple):
    key: K
    section_keys: Tuple[K | Tuple[K, K], ...]


class ARecord(NamedTuple):
    name: str
    ip: IPv4Address | IPv6Address
    ttl: int


class PtrRecord(NamedTuple):
    name: str
    ip: IPv4Address | IPv6Address
    ttl: int


class NsRecord(NamedTuple):
    name: str
    ttl: int


class MxRecord(NamedTuple):
    name: str
    prio: int
    ttl: int


class SrvRecord(NamedTuple):
    name: str
    target: str
    prio: int
    weight: int
    port: int
    ttl: int


class CnameRecord(NamedTuple):
    name: str
    target: str
    ttl: int


T = TypeVar("T")
RecordT = TypeVar("RecordT", CnameRecord, MxRecord, NsRecord, SrvRecord)

# Mapping macht es immutable und dokumentiert die Absicht
RecordTable: Mapping[type, RecordMeta] = MappingProxyType(
    {
        CnameRecord: RecordMeta(K.TARGET, CNAME_SECTION_KEYS),
        MxRecord: RecordMeta(K.NAME, MX_SECTION_KEYS),
        NsRecord: RecordMeta(K.NAME, NS_SECTION_KEYS),
        SrvRecord: RecordMeta(K.TARGET, SRV_SECTION_KEYS),
    }
)


def is_dict_str_any(val: Any) -> TypeGuard[Dict[str, Any]]:
    if not isinstance(val, dict):
        return False
    return all(isinstance(key, str) for key in cast(Dict[Any, Any], val))


def is_dict_key_any(val: Any) -> TypeGuard[Dict[K, Any]]:
    if not isinstance(val, dict):
        return False

    for key in cast(Dict[Any, Any], val):
        if not isinstance(key, str):
            return False
        try:
            K(key)
        except ValueError:
            return False

    return True


def is_list_type(val: Any, obj_type: Type[T]) -> TypeGuard[List[T]]:
    if not isinstance(val, list):
        return False
    return all(isinstance(key, obj_type) for key in cast(List[Any], val))


def get_table(data: Mapping[str, Any], key: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    value = data.get(key, default)
    if value is None:
        return {}
    if not is_dict_str_any(value):
        raise TypeError(f"{key} must be a table, got: {type(value).__name__}")
    return value


def is_array(obj: Any) -> TypeGuard[List[Any]]:
    return isinstance(obj, list)


def to_array(obj: Any) -> list[Any]:
    if is_array(obj):
        return obj

    return [obj] if obj else []


def parse_srv_name(context: str, source: str, zone_name: str | None = None) -> str:
    """
    Parse and validate SRV service name format.

    Service names must follow the format: _service._protocol[.domain]
    Both service and protocol must start with underscore.

    Args:
        context: Error context string for error messages
        source: Service name string (e.g., "_http._tcp" or "_http._tcp.example.com")
        zone_name: Optional zone name to qualify non-FQDN names

    Returns:
        Fully qualified service name with trailing dot.

    Raises:
        ValueError: If service/protocol format is invalid.
    """
    parts = source.strip().split(".")
    if source.find(".") == -1:
        raise ValueError(f"{context} '{source}' must have at least service and protocol (e.g., '_http._tcp')")

    service, protocol, *_ = parts

    if not service.startswith("_"):
        raise ValueError(f"{context} service name must start with '_', got: '{service}'")

    if not protocol.startswith("_"):
        raise ValueError(f"{context} protocol must start with '_', got: '{protocol}'")

    return parse_host_str(context, source, zone_name)


def parse_host_str(context: str, source: str, zone_name: str | None = None) -> str:
    """
    Parse and qualify a hostname to a fully qualified domain name (FQDN).

    Converts relative hostnames to FQDNs by appending the zone name.
    The special value "@" is converted to the zone name itself.

    Args:
        context: Error context string for error messages
        source: Hostname string (e.g., "www", "mail.example.com.", or "@")
        zone_name: Zone name to append to relative hostnames (required for non-FQDN input)

    Returns:
        Fully qualified domain name with trailing dot.

    Raises:
        ValueError: If hostname is not FQDN and zone_name is not provided.
    """
    host = source.strip()

    if host.endswith("."):
        return host

    if not zone_name:
        raise ValueError(f"{context} host must be a FQDN, got {host}")

    if host == "@":
        return zone_name

    return f"{host}.{zone_name}"


def parse_host(context: str, source: Mapping[K, Any], key: K, zone_name: str | None = None) -> str:
    """
    Extract and parse a hostname from a mapping to a FQDN.

    Convenience wrapper around parse_host_str that extracts the hostname
    from a mapping first.

    Args:
        context: Error context string for error messages
        source: Mapping containing the hostname
        key: Key to extract hostname from mapping
        zone_name: Zone name to append to relative hostnames

    Returns:
        Fully qualified domain name with trailing dot.

    Raises:
        ValueError: If key is missing or value is not a string.
    """
    value = get_typed(str, context, source, key)
    return parse_host_str(context, value, zone_name)


def init_argparse() -> argparse.ArgumentParser:
    """
    Initialize command-line argument parser.

    Returns:
        Configured ArgumentParser with all command-line options.
    """
    parser = argparse.ArgumentParser(
        prog="zonefile", usage="%(prog)s [OPTION] [FILE]...", description="Program to generate zonefiles from TOML"
    )
    parser.add_argument(
        "-i", metavar="INPUT", default=sys.stdin, dest="input", type=argparse.FileType("r"), help="Input TOML data (default stdin)."
    )
    parser.add_argument(
        "-o",
        metavar="ZONEFILE",
        default=None,
        dest="out",
        help="Output zone data file or directory (default stdout for unbound and ./nsd/ for nsd).",
    )
    parser.add_argument(
        "-s",
        metavar="SERIAL_FILE",
        default=".serial",
        dest="serial",
        help="File containing serial number.",
    )
    parser.add_argument("-f", default="unbound", dest="format", help="Output format.", choices=["unbound", "nsd"])

    return parser


def load_serial(serial_file: str) -> int:
    """
    Load serial number from file.

    Args:
        serial_file: Path to serial number file

    Returns:
        Serial number from file, or 0 if file doesn't exist or is invalid.
    """
    with suppress(FileNotFoundError, ValueError):
        return int(Path(serial_file).read_text(encoding="UTF-8"))

    return 0


def write_serial(serial_file: str, serial: int) -> None:
    """
    Write serial number to file.

    Args:
        serial_file: Path to serial number file
        serial: Serial number to write
    """
    Path(serial_file).write_text(f"{serial}\n", encoding="UTF-8")


def calc_serial(serial: int) -> int:
    """
    Calculate new serial number.

    Uses date-based format (YYYYMMDD00) and ensures monotonic increase.
    Serial number is max(current_date_format, old_serial + 1).

    Args:
        serial: Previous serial number

    Returns:
        New serial number (guaranteed to be greater than previous).
    """
    now = datetime.now()
    return max(now.year * 1000000 + now.month * 10000 + now.day * 100, serial + 1)


def get_str_list(context: str, source: Mapping[K, Any], key: K, default: List[str] | None = None) -> List[str]:
    """
    Extract string value(s) from mapping and normalize to list.

    Accepts single string or list of strings and always returns a list.
    Transformations:
    - str → [str]
    - List[str] → List[str]

    Args:
        context: Error context string for error messages
        source: Mapping to extract from
        key: Key to extract
        default: Default value if key is missing

    Returns:
        List of strings.

    Raises:
        ValueError: If value is missing or wrong type.
    """
    value = source.get(key, default)

    if value is None:
        missing_error(push_context(context, key))

    if is_list_type(value, str):
        return value
    if isinstance(value, str):
        return [value]

    type_error(push_context(context, key), value, str)


def push_context(context: str, key: K):
    return f"{context}.{key.value}"


def missing_error(context: str) -> NoReturn:
    raise ValueError(f"{context}: value is missing")


def range_error(context: str, value: int, limits: Tuple[int, int]) -> NoReturn:
    raise ValueError(f"{context}: integer must be in {limits[0]}-{limits[1]}, got {value}")


def type_error(context: str, value: Any, obj_type: Type[T] | Tuple[Type[T], ...]) -> NoReturn:
    if isinstance(obj_type, tuple):
        type_name = ",".join([t.__name__ for t in obj_type])
    else:
        type_name = obj_type.__name__
    raise ValueError(f"{context}: should be of type {type_name}, got {type(value).__name__}")


def merge_and_filter(
    source: Mapping[str, Any] | Mapping[K, Any], defaults: Mapping[K, Any], keys: Tuple[K | Tuple[K, K], ...]
) -> Dict[K, Any]:
    target: Dict[K, Any] = {}

    for key in keys:
        if isinstance(key, tuple):
            s_key, d_key = key
        else:
            s_key = d_key = key

        if s_key in source:
            if key == K.EMAIL:
                email = source[K.EMAIL].replace("@", ".")
                value = email if email.endswith(".") else f"{email}."
                target[K.EMAIL] = value
            else:
                value = source[s_key]
                if isinstance(value, str):
                    target[s_key] = value.strip()
                else:
                    target[s_key] = value
        elif d_key in defaults:
            target[s_key] = defaults[d_key]

    return target


def get_key(key: K, source: Mapping[str, Any], defaults: Mapping[K, Any]) -> Any:
    return source.get(key, defaults.get(key))


def get_typed(object_type: Type[T], context: str, source: Mapping[K, Any], key: K, default: T | None = None) -> T:
    ctx = push_context(context, key)

    value = source.get(key, default)

    if value is None:
        missing_error(ctx)

    if not isinstance(value, object_type):
        type_error(ctx, value, object_type)

    return value


def validate_int(context: str, source: Mapping[K, Any], key: K, limits: Tuple[int, int]):
    """
    Validate that an integer value from a mapping is within specified limits.

    Args:
        context: Error context string for error messages
        source: Mapping containing the integer value
        key: Key to extract integer from mapping
        limits: Tuple of (min, max) allowed values (inclusive)

    Raises:
        ValueError: If value is missing, not an integer, or out of range.
    """
    ctx = push_context(context, key)

    value = get_typed(int, context, source, key)

    min, max = limits
    if not (min <= value <= max):
        range_error(ctx, value, limits)


def validate_bool(context: str, source: Mapping[K, Any], key: K):
    """
    Validate that a boolean value exists in a mapping.

    Args:
        context: Error context string for error messages
        source: Mapping containing the boolean value
        key: Key to extract boolean from mapping

    Raises:
        ValueError: If value is missing or not a boolean.
    """
    get_typed(bool, context, source, key)


def validate_email(context: str, source: Mapping[K, Any]):
    """
    Validate DNS email format (SOA RNAME field).

    DNS email addresses use dots instead of @ and must end with a dot.
    Example: "admin.example.com." instead of "admin@example.com"

    Args:
        context: Error context string for error messages
        source: Mapping containing the email value

    Raises:
        ValueError: If email is missing, not a string, or doesn't end with a dot.
    """
    ctx = push_context(context, K.EMAIL)
    value = get_typed(str, context, source, K.EMAIL)
    if not value.endswith("."):
        raise ValueError(f"{ctx}: Email has to end with a dot")


def validate_host(context: str, source: Mapping[K, Any], key: K):
    """
    Validate DNS hostname according to RFC specifications.

    Validates:
    - Total length ≤ 253 characters
    - Must end with a dot (FQDN)
    - Each label ≤ 63 characters
    - Labels cannot start/end with hyphen
    - Labels contain only alphanumeric, hyphen, and underscore
    - Wildcard (*) must be leftmost label and occupy entire label

    Args:
        context: Error context string for error messages
        source: Mapping containing the hostname
        key: Key to extract hostname from mapping

    Raises:
        ValueError: If hostname violates any DNS naming rules.
    """
    name = get_typed(str, context, source, key)
    ctx = push_context(context, key)

    if len(name) > 253:
        raise ValueError(f"{ctx} DNS name too long (max 253 chars): {name}")

    if not name.endswith("."):
        raise ValueError(f"{ctx}: host name must be fully qualified")

    labels = name.rstrip(".").split(".")
    for i, label in enumerate(labels):
        if not label:
            raise ValueError(f"{ctx}: DNS name has empty label: {name}")
        if len(label) > 63:
            raise ValueError(f"{ctx}: DNS label too long (max 63 chars): {label}")

        # Wildcard: * must be the entire label
        if "*" in label:
            if i != 0:
                raise ValueError(f"{ctx}: Wildcard '*' must be leftmost label, got: {name}")
            if label != "*":
                raise ValueError(f"{ctx}: Wildcard '*' must be entire label, got: {label}")
            continue  # Wildcard is valid, skip further validation

        # Normal label validation
        if label.startswith("-") or label.endswith("-"):
            raise ValueError(f"{ctx}: DNS label cannot start/end with hyphen: {label}")
        # Allowed: a-z, A-Z, 0-9, -, _
        if not all(c.isalnum() or c in "-_" for c in label):
            raise ValueError(f"{ctx}: DNS label has invalid characters: {label}")


def parse_str(context: str, source: Mapping[K, Any], key: K, default: str | None = None) -> str:
    """Parse and strip character field"""
    value = get_typed(str, context, source, key, default)

    return value.strip()


def convert_str_to_ip(context: str, ip_string: str) -> IPv4Address | IPv6Address:
    """
    Convert a string to an IPv4Address or IPv6Address object.

    Args:
        context: Error context string for error messages
        ip_string: IP address string (e.g., "192.168.1.1" or "2001:db8::1")

    Returns:
        IPv4Address or IPv6Address object.

    Raises:
        ValueError: If ip_string is not a valid IP address.
    """
    try:
        return ip_address(ip_string)
    except ValueError as err:
        raise ValueError(f"{context}: {err}")


def parse_hosts(context: str, hosts: Mapping[str, Any], zone: Mapping[K, Any]) -> Tuple[List[ARecord], List[PtrRecord]]:
    """
    Parse host definitions into A/AAAA records and optional PTR records.

    Accepts flexible formats for each host:
    - String: "192.168.1.1" (single IP)
    - List: ["192.168.1.1", "10.0.0.1"] (multiple IPs)
    - Dict: {ip=["192.168.1.1"], alias=["www"], ttl=3600, with-ptr=true}

    Each host can have multiple IPs and aliases. PTR records are created
    automatically unless with-ptr is false or hostname is a wildcard.

    Args:
        context: Error context string for error messages
        hosts: Mapping of hostname to host configuration
        zone: Zone configuration mapping with defaults

    Returns:
        Tuple of (A/AAAA records list, PTR records list).

    Raises:
        ValueError: If host data is invalid or IP addresses are malformed.
    """
    a_records: List[ARecord] = []
    ptr_records: List[PtrRecord] = []
    zone_name = zone[K.NAME]

    for name, host_data in hosts.items():
        host_name = parse_host_str(f"{context}.hosts", name, zone_name)
        ctx = f"{context}.hosts({host_name})"
        entry: Dict[K, Any] = {}

        if isinstance(host_data, (str, list)):
            entry = merge_and_filter({K.IP: to_array(host_data)}, zone, HOST_SECTION_KEYS)
        elif is_dict_str_any(host_data):
            # Hosts accept any string keys (not limited to K enum) for flexibility
            entry = merge_and_filter(host_data, zone, HOST_SECTION_KEYS)
        else:
            raise TypeError(f"{ctx} {name} must be a string, a list of strings or an address object, got {type(host_data).__name__}")
        validate_int(ctx, entry, K.TTL, LIMITS.TTL)
        validate_bool(ctx, entry, K.WITH_PTR)

        ttl = entry[K.TTL]
        with_ptr = entry[K.WITH_PTR]
        ips = [convert_str_to_ip(ctx, ip) for ip in get_str_list(ctx, entry, K.IP)]
        aliases = [parse_host_str(ctx, alias, zone_name) for alias in get_str_list(ctx, entry, K.ALIAS, [])]

        for ip in ips:
            a_records.append(ARecord(host_name, ip, ttl))
            for alias in aliases:
                a_records.append(ARecord(alias, ip, ttl))
            if with_ptr and not host_name.startswith("*"):
                ptr_records.append(PtrRecord(host_name, ip, ttl))

    return a_records, ptr_records


def parse_zone_name(source: Mapping[K, Any]) -> str:
    """
    Extract and ensure zone name is a fully qualified domain name.

    Adds trailing dot if not present.

    Args:
        source: Mapping containing the zone name

    Returns:
        Zone name with trailing dot.

    Raises:
        ValueError: If zone name is missing or invalid.
    """
    name = parse_str("zone", source, K.NAME)

    if name.endswith("."):
        return name

    return f"{name}."


def convert_to_record(
    context: str, entry: Any, record_type: Type[RecordT], defaults: Mapping[K, Any], *, name: str | None = None
) -> RecordT:
    """
    Convert various input formats to a typed DNS record object.

    Generic converter that handles string, dict, or already-parsed record inputs.
    Applies defaults, parses hostnames, and validates all fields.

    Args:
        context: Error context string for error messages
        entry: Input data (string, dict, or already-parsed record)
        record_type: Target NamedTuple type (NsRecord, MxRecord, SrvRecord, CnameRecord)
        defaults: Mapping with default values (zone configuration)
        name: Optional explicit name (for CNAME/SRV records where name comes from dict key)

    Returns:
        Typed DNS record object (NsRecord, MxRecord, SrvRecord, or CnameRecord).

    Raises:
        ValueError: If entry format is invalid or validation fails.
    """
    if isinstance(entry, record_type):
        return entry

    zone_name = defaults.get(K.NAME)

    host_key = RecordTable[record_type].key
    section_keys = RecordTable[record_type].section_keys
    record: Dict[K, Any]
    if record_type != SrvRecord and isinstance(entry, str):
        if name is not None:
            base_dict = {host_key: entry, K.NAME: name}
        else:
            base_dict = {host_key: entry}
    elif is_dict_key_any(entry):
        if name is not None:
            base_dict = {**entry, K.NAME: name}
        else:
            base_dict = entry
    else:
        type_error(context, entry, (str, list))

    record = merge_and_filter(base_dict, defaults, section_keys)

    record[host_key] = parse_host(context, record, host_key, zone_name)
    validate_host(context, record, host_key)
    validate_int(context, record, K.TTL, LIMITS.TTL)
    if record_type == MxRecord:
        validate_int(context, record, K.PRIO, LIMITS.MX_PRIO)
    if record_type == SrvRecord:
        validate_int(context, record, K.PORT, LIMITS.PORT)
        validate_int(context, record, K.PRIO, LIMITS.SRV_PRIO)
        validate_int(context, record, K.WEIGHT, LIMITS.SRV_WEIGHT)

    return record_type(**record)


def parse_nameserver(context: str, data: Any, zone: Mapping[K, Any]) -> List[NsRecord]:
    """
    Parse NS (Name Server) records from TOML configuration.

    Accepts flexible input formats:
    - String: "ns1" or "ns1.example.com."
    - Dict: {name="ns1.example.com.", ttl=3600}
    - List: ["ns1", "ns2"] or mixed list with strings and dicts
    - Already parsed NsRecord objects (for defaults inheritance)

    Missing values (ttl) are filled from zone defaults.

    Args:
        context: Error context string for error messages
        data: Nameserver data (string, dict, list, or NsRecord)
        zone: Zone configuration mapping with defaults

    Returns:
        List of NsRecord objects with hostname and TTL.
    """
    ctx = push_context(context, K.NAMESERVER)

    if data is None:
        missing_error(ctx)

    ns_records: List[NsRecord] = [convert_to_record(ctx, entry, NsRecord, zone) for entry in to_array(data)]

    if len(ns_records) == 0:
        raise ValueError(f"{ctx} needs at least one nameserver")

    return ns_records


def parse_mx(context: str, data: Any, zone: Mapping[K, Any]) -> List[MxRecord]:
    """
    Parse MX (Mail Exchange) records from TOML configuration.

    Accepts flexible input formats:
    - String: "mx1" or "mx1.example.com."
    - Dict: {name="mx1", prio=10, ttl=3600}
    - List: ["mx1", "mx2"] or mixed list with strings and dicts
    - Already parsed MxRecord objects (for defaults inheritance)

    Missing values (prio, ttl) are filled from zone defaults.

    Args:
        context: Error context string for error messages
        data: MX server data (string, dict, list, or MxRecord)
        zone: Zone configuration mapping with defaults

    Returns:
        List of MxRecord objects with name, priority, and TTL.
    """
    ctx = push_context(context, K.MX)

    if data is None:
        return []

    return [convert_to_record(ctx, entry, MxRecord, zone) for entry in to_array(data)]


def parse_srv(context: str, data: Mapping[str, Any], zone: Mapping[K, Any]) -> List[SrvRecord]:
    """
    Parse SRV (Service) records from TOML configuration.

    Expects a table where keys are service names (e.g., "_http._tcp") and values are targets:
    - Dict value: {target="server.example.com.", port=80, prio=5, weight=10, ttl=3600}

    Service names must start with underscore and contain protocol (e.g., "_http._tcp").
    Missing values (prio, weight, ttl, port) are filled from zone defaults.

    Args:
        context: Error context string for error messages
        data: Mapping of service names to SRV record configurations
        zone: Zone configuration mapping with defaults

    Returns:
        List of SrvRecord objects with name, target, priority, weight, port, and TTL.
    """
    srv_records: List[SrvRecord] = []
    zone_name = zone[K.NAME]

    for srv_name, entry in data.items():
        name = parse_srv_name(push_context(context, K.SRV), srv_name, zone_name)
        ctx = f"{push_context(context, K.SRV)}({name})"

        record = convert_to_record(ctx, entry, SrvRecord, zone, name=name)

        srv_records.append(record)

    return srv_records


def parse_cnames(context: str, data: Mapping[str, Any], zone: Mapping[K, Any]) -> List[CnameRecord]:
    """
    Parse CNAME (Canonical Name) records from TOML configuration.

    Expects a table where keys are CNAME aliases and values are targets:
    - String value: cnames.alias = "target.example.com."
    - Table value: cnames.alias = {target="target.example.com.", ttl=3600}

    Missing values (ttl) are filled from zone defaults.

    Args:
        context: Error context string for error messages
        data: Mapping of CNAME aliases to target configurations
        zone: Zone configuration mapping with defaults

    Returns:
        List of CnameRecord objects with alias name, target, and TTL.
    """
    cname_records: List[CnameRecord] = []
    zone_name = zone[K.NAME]

    for cname, entry in data.items():
        name = parse_host_str(push_context(context, K.CNAME), cname, zone_name)
        ctx = f"{push_context(context, K.CNAME)}({name})"

        record = convert_to_record(ctx, entry, CnameRecord, zone, name=name)
        cname_records.append(record)

    return cname_records


def parse_zone(data: Mapping[str, Any], defaults: Mapping[K, Any]) -> Tuple[Mapping[K, Any], List[PtrRecord]]:
    """
    Parse a forward DNS zone configuration from TOML data.

    Creates a complete zone configuration including SOA, NS, MX, A/AAAA, SRV,
    and CNAME records. Also generates PTR records for reverse zones.

    Args:
        data: Zone configuration from TOML (may contain hosts, mx, srv, cname sections)
        defaults: Default values for missing fields

    Returns:
        Tuple of (zone configuration dict, list of PTR records).

    Raises:
        ValueError: If zone configuration is invalid or required fields are missing.
    """
    zone: Dict[K, Any] = merge_and_filter(data, defaults, ZONE_SECTION_KEYS)
    zone[K.NAME] = parse_zone_name(zone)
    validate_host("zone", zone, K.NAME)
    name = zone[K.NAME]

    context = f"zone({name})"
    validate_config(context, zone)
    validate_email(context, zone)
    zone[K.NAMESERVER] = parse_nameserver(context, get_key(K.NAMESERVER, data, defaults), zone)
    zone[K.MX] = parse_mx(context, get_key(K.MX, data, defaults), zone)
    zone[K.A], ptr = parse_hosts(context, get_table(data, K.HOSTS, {}), zone)
    zone[K.SRV] = parse_srv(context, get_table(data, K.SRV, {}), zone)
    zone[K.CNAME] = parse_cnames(context, get_table(data, K.CNAME, {}), zone)

    return zone, ptr


def parse_reverse(
    network: IPv4Network | IPv6Network, ptr: List[PtrRecord], data: Mapping[str, Any], defaults: Mapping[K, Any]
) -> Mapping[K, Any]:
    """
    Parse a reverse DNS zone configuration for PTR records.

    Creates reverse zone for in-addr.arpa (IPv4) or ip6.arpa (IPv6).
    Automatically calculates zone name from network prefix.

    Args:
        network: IP network (IPv4Network or IPv6Network)
        ptr: List of PTR records belonging to this network
        data: Reverse zone configuration from TOML
        defaults: Default values for missing fields

    Returns:
        Reverse zone configuration dict.

    Raises:
        ValueError: If zone configuration is invalid.
    """
    if network.version == 4:
        split = (32 - network.prefixlen) >> 3
    else:
        split = (128 - network.prefixlen) >> 2

    name = ".".join(network.network_address.reverse_pointer.split(".")[split:]) + "."

    zone: Dict[K, Any] = merge_and_filter(data, defaults, REVERSE_SECTION_KEYS)
    zone[K.NAME] = name
    validate_host("zone", zone, K.NAME)

    context = f"reverse({name})"
    zone[K.NETWORK] = network
    zone[K.SPLIT] = split
    validate_config(context, zone)
    validate_email(context, zone)
    zone[K.NAMESERVER] = parse_nameserver(context, zone.get(K.NAMESERVER), zone)
    zone[K.PTR] = ptr

    return zone


def check_for_duplicate_ips(ptr_records: List[PtrRecord]):
    """
    Check for duplicate IP addresses in PTR records.

    Args:
        ptr_records: List of PTR records to check

    Raises:
        ValueError: If duplicate IP addresses are found.
    """
    ptr_dict: Dict[IPv4Address | IPv6Address, PtrRecord] = {}

    for ptr_record in ptr_records:
        ip = ptr_record.ip
        if ip in ptr_dict:
            existing = ptr_dict[ip]
            raise ValueError(f"Duplicate PTR record for IP {ptr_record.ip} ({ptr_record.name} {existing.name})")
        ptr_dict[ip] = ptr_record


def validate_config(context: str, source: Mapping[K, Any]):
    """
    Validate zone configuration parameters.

    Validates all SOA and zone-level configuration fields including
    TTL values, serial number, timing parameters, and priority values.

    Args:
        context: Error context string for error messages
        source: Mapping containing zone configuration

    Raises:
        ValueError: If any configuration value is invalid or out of range.
    """
    validate_int(context, source, K.MX_PRIO, LIMITS.MX_PRIO)
    validate_int(context, source, K.NRC_TTL, LIMITS.NRC_TTL)
    validate_int(context, source, K.REFRESH, LIMITS.REFRESH)
    # RETRY must be less than REFRESH (RFC 1035)
    validate_int(context, source, K.RETRY, (0, source[K.REFRESH]))
    validate_int(context, source, K.SERIAL, LIMITS.SERIAL)
    validate_int(context, source, K.SRV_PRIO, LIMITS.SRV_PRIO)
    validate_int(context, source, K.SRV_WEIGHT, LIMITS.SRV_WEIGHT)
    validate_int(context, source, K.TTL, LIMITS.TTL)
    validate_bool(context, source, K.WITH_PTR)


def parse_defaults(source: Mapping[str, Any], prog_defaults: Mapping[K, Any]) -> Dict[K, Any]:
    """
    Parse and validate default values from TOML configuration.

    Merges TOML [defaults] section with program defaults, validates all
    configuration parameters, and parses nameserver/MX defaults if present.

    Args:
        source: TOML data containing optional [defaults] section
        prog_defaults: Program-level default values

    Returns:
        Merged and validated default configuration.

    Raises:
        ValueError: If any default value is invalid or out of range.
    """
    context = "defaults"

    toml_defaults: Dict[str, Any] = source.get("defaults", {})
    target: Dict[K, Any] = merge_and_filter(toml_defaults, prog_defaults, DEFAULT_SECTION_KEYS)
    validate_config(context, target)

    if K.EMAIL in target:
        validate_email(context, target)
    if K.NAMESERVER in target:
        target[K.NAMESERVER] = parse_nameserver(context, target[K.NAMESERVER], target)
    if K.MX in target:
        target[K.MX] = parse_mx(context, target[K.MX], target)

    return target


def parse(data: Dict[str, Any], prog_defaults: Mapping[K, Any]) -> List[Mapping[K, Any]]:
    """
    Parse complete TOML DNS configuration into forward and reverse zones.

    Main entry point for parsing TOML data. Creates both forward zones
    (from [[zone]] sections) and reverse zones (from [reverse] section).
    Validates all data, checks for duplicate PTR records, and ensures
    reverse zone networks don't overlap.

    Args:
        data: Parsed TOML data containing defaults, zones, and reverse zones
        prog_defaults: Program-level default values

    Returns:
        List of zone configurations (both forward and reverse zones).

    Raises:
        ValueError: If configuration is invalid, zones overlap, or duplicates exist.
        TypeError: If zone data has wrong type.
    """
    defaults = parse_defaults(data, prog_defaults)

    ptr_records: List[PtrRecord] = []
    zones: List[Mapping[K, Any]] = []

    for zone_data in to_array(data.get("zone", [])):
        if not is_dict_str_any(zone_data):
            raise TypeError(f"Zone should be a table or an array of tables, got {type(zone_data).__name__}")

        zone, ptr = parse_zone(zone_data, defaults)
        zones.append(zone)
        ptr_records.extend(ptr)

    check_for_duplicate_ips(ptr_records)

    reverse_zones = get_table(data, "reverse", {})

    networks: List[IPv4Network | IPv6Network] = []
    for network, config in reverse_zones.items():
        try:
            nw = ip_network(network)
        except ValueError:
            raise ValueError(f"Reverse Zone is not a network, got {network}")
        for net in networks:
            if net.overlaps(nw):
                raise ValueError(f"Reverse Zone Networks overlap: {net} and {nw}")
        ptrs = [ptr for ptr in ptr_records if ptr.ip in nw]
        r = parse_reverse(nw, ptrs, config, defaults)
        networks.append(nw)
        zones.append(r)

    return zones


def unbound(zones: List[Mapping[K, Any]]) -> str:
    """
    Generate Unbound DNS server configuration from zone data.

    Converts zone configurations to Unbound's local-zone and local-data format.
    Supports SOA, NS, MX, A, AAAA, SRV, CNAME, and PTR records.

    Args:
        zones: List of zone configurations (forward and reverse zones)

    Returns:
        Complete Unbound configuration as string.
    """
    buf = StringIO()
    buf.write("server:\n")
    for zone in zones:
        zone_name = zone[K.NAME]
        zone_ttl = zone[K.TTL]
        name_width = UNBOUND_COLUMN_WIDTH
        buf.write(f"local-zone: {zone_name} static\n")
        buf.write(
            f'local-data: "{zone_name:{name_width-len(str(zone_ttl))}} {zone_ttl} IN SOA  {zone[K.NAMESERVER][0].name} {zone[K.EMAIL]} {zone[K.SERIAL]} {zone[K.REFRESH]} {zone[K.RETRY]} {zone[K.EXPIRE]} {zone[K.NRC_TTL]}"\n'
        )

        for ns in zone[K.NAMESERVER]:
            ttl = "" if zone_ttl == ns.ttl else str(ns.ttl)
            buf.write(f'local-data: "{zone_name:{name_width-len(ttl)}} {ttl} IN NS   {ns.name}"\n')

        for mx in zone.get(K.MX, []):
            ttl = "" if zone_ttl == mx.ttl else str(mx.ttl)
            buf.write(f'local-data: "{zone_name:{name_width-len(ttl)}} {ttl} IN MX   {mx.prio} {mx.name}"\n')

        for host in zone.get(K.A, []):
            ttl = "" if zone_ttl == host.ttl else str(host.ttl)
            width = name_width - len(ttl)
            if host.ip.version == 4:
                buf.write(f'local-data: "{host.name:{width}} {ttl} IN A    {host.ip}"\n')
            else:
                buf.write(f'local-data: "{host.name:{width}} {ttl} IN AAAA {host.ip}"\n')

        for srv in zone.get(K.SRV, []):
            ttl = "" if zone_ttl == srv.ttl else str(srv.ttl)
            buf.write(
                f'local-data: "{srv.name:{name_width-len(ttl)}} {ttl} IN SRV  {srv.prio} {srv.weight} {srv.port} {srv.target}"\n'
            )

        for cname in zone.get(K.CNAME, []):
            ttl = "" if zone_ttl == cname.ttl else str(cname.ttl)
            buf.write(f'local-data: "{cname.name:{name_width-len(ttl)}} {ttl} CNAME   {cname.target}"\n')

        for ptr in zone.get(K.PTR, []):
            ttl = "" if zone_ttl == ptr.ttl else str(ptr.ttl)
            buf.write(f'local-data-ptr: "{str(ptr.ip):{name_width-len(ttl)}} {ttl} {ptr.name}"\n')

        buf.write("\n")

    return buf.getvalue()


def nsd_write(buf: StringIO, value: str, space: int, ttl: int, zone_ttl: int, record_type: str, data: str) -> None:
    """
    Write a single DNS record to NSD zone file with proper formatting.

    Handles column alignment, TTL omission when matching zone default,
    and dynamic padding for record type field.

    Args:
        buf: StringIO buffer to write to
        value: Record name/label
        space: Column width for name field
        ttl: Record TTL
        zone_ttl: Zone default TTL
        record_type: DNS record type (A, AAAA, MX, etc.)
        data: Record-specific data (IP, target, etc.)
    """
    str_ttl = str(ttl) if ttl != zone_ttl else ""
    if ttl == zone_ttl:
        value_ttl = f"{value:{space-1}}"
    else:
        value_max = space - len(str_ttl) - 2
        value_ttl = f"{value:{value_max}} {str_ttl}"

    # Calculate padding for record type field (max 7 chars)
    # Reduces padding if name+TTL field exceeds column width
    type_len = max(0, 7 - (max(0, len(value_ttl) - space - 1)))

    buf.write(f"{value_ttl} {record_type:{type_len}} {data}\n")


def nsd(directory: str, zones: List[Mapping[K, Any]]):
    """
    Generate NSD DNS server configuration and zone files.

    Creates NSD configuration file and master zone files in standard format.
    Generates zones.conf and individual zone files with SOA, NS, MX, A/AAAA,
    SRV, CNAME, and PTR records.

    Args:
        directory: Output directory for NSD configuration
        zones: List of zone configurations (forward and reverse zones)
    """
    master_dir = f"{directory}/master"

    os.makedirs(directory, exist_ok=True)
    os.makedirs(master_dir, exist_ok=True)

    conf = StringIO()
    files: Dict[str, str] = {}

    for zone in zones:
        suffix = f".{zone[K.NAME]}"
        space = NSD_INDENT_SPACES
        conf.write("zone:\n")
        conf.write(f"    name: {zone[K.NAME]}\n")
        conf.write(f"    zonefile: master/{zone[K.NAME]}zone\n")
        conf.write("\n")

        zone_file = StringIO()

        zone_file.write(f"$ORIGIN {zone[K.NAME]}\n")
        zone_file.write(f"$TTL {zone[K.TTL]}\n")
        zone_file.write("\n")
        zone_file.write(f"@                            IN SOA     {zone[K.NAMESERVER][0].name} {zone[K.EMAIL]} (\n")
        zone_file.write(f"{' '*space}           {zone[K.SERIAL]:<12}; serial number\n")
        zone_file.write(f"{' '*space}           {zone[K.REFRESH]:<12}; refresh\n")
        zone_file.write(f"{' '*space}           {zone[K.RETRY]:<12}; retry\n")
        zone_file.write(f"{' '*space}           {zone[K.EXPIRE]:<12}; expire\n")
        zone_file.write(f"{' '*space}           {zone[K.NRC_TTL]:<12}; min ttl\n")
        zone_file.write(f"{' '*space}        )\n")

        for ns in zone[K.NAMESERVER]:
            zone_file.write(f"{' '*space}NS      {ns.name}\n")

        for mx in zone.get(K.MX, []):
            zone_file.write(f"{' '*space}MX {mx.prio:>4} {mx.name}\n")

        grouped: Dict[str, List[ARecord]] = defaultdict(list)
        for record in zone.get(K.A, []):
            grouped[record.name].append(record)

        for hostname in grouped:
            first = True
            name = "@" if hostname == zone[K.NAME] else hostname.removesuffix(suffix)
            hosts = grouped[hostname]
            hosts4 = [h for h in hosts if h.ip.version == 4]
            hosts6 = [h for h in hosts if h.ip.version == 6]

            for host in hosts4:
                if not first:
                    name = ""
                first = False
                nsd_write(zone_file, name, space, host.ttl, zone[K.TTL], "A", str(host.ip))
            for host in hosts6:
                if not first:
                    name = ""
                first = False
                nsd_write(zone_file, name, space, host.ttl, zone[K.TTL], "AAAA", str(host.ip))

        for srv in zone.get(K.SRV, []):
            service = srv.name.removesuffix(suffix)
            nsd_write(zone_file, service, space, srv.ttl, zone[K.TTL], "SRV", f"{srv.prio} {srv.weight} {srv.port} {srv.target}")

        for cname in zone.get(K.CNAME, []):
            src = "@" if cname.name == zone[K.NAME] else cname.name.removesuffix(suffix)
            nsd_write(zone_file, src, space, cname.ttl, zone[K.TTL], "CNAME", cname.target)

        for ptr in sorted(zone.get(K.PTR, []), key=lambda ptr: ptr.ip):
            ip_entry = ".".join(ptr.ip.reverse_pointer.split(".")[: zone[K.SPLIT]])
            nsd_write(zone_file, ip_entry, space, ptr.ttl, zone[K.TTL], "PTR", ptr.name)

        files[f"{master_dir}/{zone[K.NAME]}zone"] = zone_file.getvalue()

    Path(f"{directory}/zones.conf").write_text(conf.getvalue(), encoding="UTF-8")
    for file_name, data in files.items():
        Path(file_name).write_text(data, encoding="UTF-8")


def main() -> None:
    parser = init_argparse()
    args = parser.parse_args()
    old_serial = load_serial(args.serial)
    serial = calc_serial(old_serial)
    content = args.input.read()
    input_data = tomllib.loads(content)

    if len(input_data) == 0:
        return

    defaults: Mapping[K, Any] = {**PROGRAM_DEFAULTS, K.SERIAL: serial}

    zones = parse(input_data, defaults)

    if args.format == "unbound":
        output = unbound(zones)
        writer_cm = open(args.out, "w") if args.out else nullcontext(sys.stdout)
        with writer_cm as out:
            out.write(output)
    elif args.format == "nsd":
        out_dir = "./nsd" if args.out is None else args.out
        nsd(out_dir, zones)

    write_serial(args.serial, serial)


if __name__ == "__main__":
    main()
