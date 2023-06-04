#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from collections import abc, namedtuple, defaultdict
from ipaddress import ip_address, IPv4Address, IPv6Address
from typing import TextIO, Tuple, List, Dict
import yaml

REFRESH = 7200
RETRY = 3600
EXPIRE = 1209600
NRC_TTL = 3600
TTL = 10800

LOCAL_DATA = "local-data:     "
LOCAL_ZONE = "local-zone:     "
LOCAL_PTR = "local-data-ptr: "
INDENT = " " * 4


Zone = namedtuple(
    "ZONE",
    ("name", "email", "serial", "refresh", "retry", "expire", "nrc_ttl", "ttl", "a", "ptr", "ns", "mx", "srv"),
)
ARecord = namedtuple("ARecord", ("name", "ip", "ttl"))

PtrRecord = namedtuple("PtrRecord", ("name", "ip", "ttl"))

NsRecord = namedtuple("NsRecord", ("zone", "name", "ttl"))

MxRecord = namedtuple("MxRecord", ("zone", "name", "prio", "ttl"))

SrvRecord = namedtuple(
    "SrvRecord",
    ("name", "service", "prio", "weight", "port", "ttl"),
)


def to_array(obj):
    if isinstance(obj, abc.Sequence) and not isinstance(obj, str):
        return obj

    return [obj] if obj else ()


def to_ip(ip_addr):
    if not isinstance(ip_addr, str):
        return ip_addr
    try:
        return ip_address(ip_addr)
    except ValueError:
        return ip_addr


def host_string(host, zone):
    if host == ".":
        return f"{zone}."

    return host if host.endswith(".") else f"{host}.{zone}."


def init_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zonefile", usage="%(prog)s [OPTION] [FILE]...", description="Program to generate zonefiles from yaml"
    )
    parser.add_argument(
        "-i", metavar="INPUT", default=sys.stdin, dest="input", type=argparse.FileType("r"), help="Input YAML data (default stdin)."
    )
    parser.add_argument(
        "-o",
        metavar="ZONEFILE",
        default=sys.stdout,
        dest="out",
        type=argparse.FileType("w"),
        help="Output zone data (default stdout).",
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
    ser = 0
    try:
        with open(serial_file, "r", encoding="UTF-8") as file:
            txt = file.read()
            if txt:
                ser = int(txt)
    except FileNotFoundError:
        pass

    return ser


def write_serial(serial_file: str, serial: int) -> None:
    with open(serial_file, "w", encoding="UTF-8") as file:
        file.write(f"{serial}\n")


def calc_serial(serial: int) -> int:
    now = datetime.now()
    return max(now.year * 1000000 + now.month * 10000 + now.day * 100, serial + 1)


def parse_zone(zone_name, zone_data, serial):
    a: Dict[str, List[ARecord]] = defaultdict(list)
    ptr = []
    ns = []
    mx = []
    srv = []

    def extract_info(info):
        ttl = info.pop() if len(info) > 0 and isinstance(info[-1], int) else None
        convert = tuple(map(to_ip, info))
        ips = set(filter(lambda x: isinstance(x, (IPv4Address, IPv6Address)), convert))
        aliases = set(
            map(lambda name: host_string(name, zone_name), filter(lambda x: not isinstance(x, (IPv4Address, IPv6Address)), convert))
        )
        return ttl, ips, aliases

    addresses = zone_data.get("addresses", {})
    for host in addresses:
        name = host_string(host, zone_name)
        info = to_array(addresses[host])
        ttl, ips, aliases = extract_info(info)

        for ip in ips:
            a[name].append(ARecord(name, ip, ttl))
            for alias in aliases:
                a[alias].append(ARecord(host_string(alias, zone_name), ip, ttl))

    hosts = zone_data.get("hosts", {})
    for host in hosts:
        name = host_string(host, zone_name)
        info = to_array(hosts[host])
        ttl, ips, aliases = extract_info(info)

        for ip in ips:
            a[name].append(ARecord(name, ip, ttl))
            ptr.append(PtrRecord(name, ip, ttl))
            for alias in aliases:
                a[alias].append(ARecord(host_string(alias, zone_name), ip, ttl))

    nameserver = zone_data.get("nameserver", [])
    if isinstance(nameserver, str):
        ns.append(NsRecord(zone_name, host_string(nameserver, zone_name), None))
    elif isinstance(nameserver, abc.Sequence):
        for host in nameserver:
            ns.append(NsRecord(zone_name, host_string(host, zone_name), None))
    else:
        for host in nameserver:
            name = host_string(host, zone_name)
            info = to_array(nameserver[host])
            ttl, ips, aliases = extract_info(info)

            if len(aliases) > 0:
                raise ValueError("Aliases in nameserver declaration is not allowed")

            ns.append(NsRecord(zone_name, name, ttl))

            if len(ips) > 0:
                if name in a:
                    if len(set(map(lambda r: r.ip, a[name])) ^ ips) == 0:
                        continue

                    raise ValueError(f"IPs for nameserver {name} submitted while already an A-record exists.")

                for ip in ips:
                    a[name].append(ARecord(name, ip, ttl))
                    if not any(host.ip == ip for host in ptr):
                        ptr.append(PtrRecord(name, ip, ttl))

    for host, data in zone_data.get("mx", {}).items():
        name = host_string(host, zone_name)
        info = to_array(data)
        prio = info.pop(0)
        if not isinstance(prio, int):
            raise TypeError(f"First Argument to MX is prio (Number) not {type(prio)}: {zone_name} {host} {prio}")

        ttl, ips, aliases = extract_info(info)

        if len(aliases) > 0:
            raise ValueError("Aliases in mx declaration is not allowed")

        mx.append(MxRecord(zone_name, name, prio, ttl))

        if len(ips) > 0:
            if name in a:
                if len(set(map(lambda r: r.ip, a[name])) ^ ips) == 0:
                    continue

                raise ValueError(f"IPs for mx {name} submitted while already an A-record exists.")

            for ip in ips:
                a[name].append(ARecord(name, ip, ttl))
                if not any(host.ip == ip for host in ptr):
                    ptr.append(PtrRecord(name, ip, ttl))

    for service, info in zone_data.get("srv", {}).items():
        name, protocol, *domain = service.split(".")
        if not name.startswith("_"):
            name = f"_{name}"
        if not protocol.startswith("_"):
            protocol = f"_{protocol}"
        service_name = host_string(".".join([name, protocol, *domain]), zone_name)

        ttl = info.pop() if len(info) > 0 and isinstance(info[-1], int) else None
        prio = 5
        weight = 0
        port = -1
        if (
            len(info) == 4
            and isinstance(info[0], int)
            and isinstance(info[1], int)
            and isinstance(info[2], int)
            and isinstance(info[3], str)
        ):
            prio = info[0]
            weight = info[1]
            port = info[2]
        elif len(info) == 2 and isinstance(info[0], int) and isinstance(info[1], str):
            port = info[0]
        else:
            raise TypeError(f"Couldn't identify SRV record. It's [port, name] or [prio, weight, port, name]. Given: {info}")
        host = info[-1]
        srv.append(SrvRecord(host_string(host, zone_name), service_name, prio, weight, port, ttl))

    email = zone_data["email"].replace("@", ".")
    if not email.endswith("."):
        email += "."

    return Zone(
        name=zone_name,
        email=email,
        serial=zone_data.get("serial", serial),
        refresh=zone_data.get("refresh", REFRESH),
        retry=zone_data.get("retry", RETRY),
        expire=zone_data.get("expire", EXPIRE),
        nrc_ttl=zone_data.get("nrc_ttl", NRC_TTL),
        ttl=zone_data.get("ttl", TTL),
        a=a,
        ptr=ptr,
        ns=ns,
        mx=mx,
        srv=srv,
    )


def parse(zones, serial):
    return tuple(map(lambda zone: parse_zone(zone[0], zone[1], serial), zones.items()))


def unbound(writer: TextIO, zones: Tuple[Zone]):
    def write_line(writer, cmd, left, ttl, middle, right):
        writer.write(INDENT)
        writer.write(str(cmd).ljust(15))
        writer.write(' "')
        writer.write(str(left).ljust(40))
        writer.write(" ")
        if ttl:
            writer.write(str(ttl).ljust(6))
        else:
            writer.write(" " * 6)
        writer.write(" ")
        writer.write(str(middle).strip().ljust(7))
        writer.write(" ")
        writer.write(str(right))
        writer.write('"\n')

    writer.write("server:\n")
    for zone in zones:
        zone_name = zone.name if zone.name.endswith(".") else f"{zone.name}."

        writer.write(f"\n{INDENT}{LOCAL_ZONE} {zone_name} static\n")
        write_line(
            writer,
            LOCAL_DATA,
            f"{zone.name}.",
            zone.ttl,
            "IN SOA",
            f"{zone.ns[0].name} {zone.email} {zone.serial} {zone.refresh} {zone.retry} {zone.expire} {zone.nrc_ttl}",
        )

        for ns in zone.ns:
            write_line(writer, LOCAL_DATA, f"{ns.zone}.", ns.ttl, "IN NS", ns.name)

        for mx in zone.mx:
            write_line(writer, LOCAL_DATA, f"{mx.zone}.", mx.ttl, "IN MX", f"{mx.prio} {mx.name}")

        for hostname in zone.a:
            for host in zone.a[hostname]:
                write_line(
                    writer, LOCAL_DATA, host.name, host.ttl, f"IN {'A    ' if isinstance(host.ip, IPv4Address) else 'AAAA'}", host.ip
                )

        for srv in zone.srv:
            write_line(writer, LOCAL_DATA, srv.service, srv.ttl, "IN SRV", f"{srv.prio} {srv.weight} {srv.port} {srv.name}")

        for ptr in zone.ptr:
            write_line(writer, LOCAL_PTR, ptr.ip, ptr.ttl, "", ptr.name)


def process(input_data: str, writer, serial, output_format):
    zones = parse(input_data, serial)

    if output_format == "unbound":
        unbound(writer, zones)
    elif output_format == "nsd":
        pass
    else:
        raise ValueError(f"Unknown format {output_format}")


def main() -> None:
    parser = init_argparse()
    args = parser.parse_args()
    old_serial = load_serial(args.serial)
    new_serial = calc_serial(old_serial)
    input_data = yaml.safe_load(args.input)

    if input_data is None:
        return

    process(input_data, args.out, new_serial, args.format)

    write_serial(args.serial, new_serial)


if __name__ == "__main__":
    main()
