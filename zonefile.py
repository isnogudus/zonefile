#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from collections import abc, namedtuple, defaultdict
from ipaddress import ip_address, ip_network, IPv4Address, IPv6Address, IPv4Network, IPv6Network
from typing import TextIO, Tuple, List, Dict
from functools import reduce
from itertools import zip_longest
import yaml
import os

LOCAL_DATA = "local-data:"
LOCAL_ZONE = "local-zone:"
LOCAL_PTR = "local-data-ptr:"
INDENT = 4

DEFAULTS = {}


Zone = namedtuple(
    "ZONE",
    ("name", "email", "serial", "refresh", "retry", "expire", "nrc_ttl", "ttl", "a", "ptr", "ns", "mx", "srv"),
)

ReverseZone = namedtuple("ReverseZone", ("name", "email", "serial", "refresh", "retry", "expire", "nrc_ttl", "ttl", "network"))

ARecord = namedtuple("ARecord", ("name", "ip", "ttl"))

PtrRecord = namedtuple("PtrRecord", ("name", "ip", "ttl"))

NsRecord = namedtuple("NsRecord", ("zone", "name", "ttl"))

MxRecord = namedtuple("MxRecord", ("zone", "name", "prio", "ttl"))

SrvRecord = namedtuple(
    "SrvRecord",
    ("name", "service", "prio", "weight", "port", "ttl"),
)


#
def w(format: tuple[int], values: tuple) -> str:
    result = ""
    index = 0
    for length, value in zip_longest(format, values):
        value = "" if value is None else str(value)

        if result and result[-1] != " ":
            result += " "

        if length is not None:
            index += length

        result = (result + value).ljust(index)
    return result


def is_array(obj):
    return isinstance(obj, abc.Sequence) and not isinstance(obj, str)


def to_array(obj):
    if is_array(obj):
        return obj

    return [obj] if obj else []


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
        default=None,
        dest="out",
        help="Output zone data file or directory (default stdout for unbound and ./nsd/ for nsd).",
    )
    # parser.add_argument(
    #     "-o",
    #     metavar="ZONEFILE",
    #     default=sys.stdout,
    #     dest="out",
    #     type=argparse.FileType("w"),
    #     help="Output zone data (default stdout).",
    # )
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


def ljust(value, length: int) -> str:
    return (str(value).rstrip() + " ").ljust(length, " ")


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
            if not name.startswith("*"):
                ptr.append(PtrRecord(name, ip, ttl))
            for alias in aliases:
                a[alias].append(ARecord(host_string(alias, zone_name), ip, ttl))

    nameserver = zone_data.get("nameserver", DEFAULTS["nameserver"])
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

    email = zone_data.get("email", DEFAULTS["email"]).replace("@", ".")
    if not email.endswith("."):
        email += "."

    return Zone(
        name=zone_name,
        email=email,
        serial=zone_data.get("serial", serial),
        refresh=zone_data.get("refresh", DEFAULTS["refresh"]),
        retry=zone_data.get("retry", DEFAULTS["retry"]),
        expire=zone_data.get("expire", DEFAULTS["expire"]),
        nrc_ttl=zone_data.get("nrc-ttl", DEFAULTS["ntc-ttl"]),
        ttl=zone_data.get("ttl", DEFAULTS["ttl"]),
        a=a,
        ptr=ptr,
        ns=ns,
        mx=mx,
        srv=srv,
    )


def parse_reverse(zone_name, zone_data, serial):
    if zone_data is None:
        zone_data = {}
    network = ip_network(zone_name, strict=False)

    email = zone_data.get("email", DEFAULTS["email"]).replace("@", ".")
    if not email.endswith("."):
        email += "."

    return ReverseZone(
        name=zone_name,
        email=email,
        serial=zone_data.get("serial", serial),
        refresh=zone_data.get("refresh", DEFAULTS["refresh"]),
        retry=zone_data.get("retry", DEFAULTS["retry"]),
        expire=zone_data.get("expire", DEFAULTS["expire"]),
        nrc_ttl=zone_data.get("nrc-ttl", DEFAULTS["ntc-ttl"]),
        ttl=zone_data.get("ttl", DEFAULTS["ttl"]),
        network=network,
    )


def parse(data, serial):
    defaults = data.get("defaults", {})

    DEFAULTS["email"] = defaults.get("email")
    DEFAULTS["nameserver"] = to_array(defaults.get("nameserver"))
    DEFAULTS["refresh"] = defaults.get("refresh", 7200)
    DEFAULTS["retry"] = defaults.get("retry", 3600)
    DEFAULTS["expire"] = defaults.get("expire", 1209600)
    DEFAULTS["ntc-ttl"] = defaults.get("nrc-ttl", 3600)
    DEFAULTS["ttl"] = defaults.get("ttl", 10800)

    reverse_zones = data.get("reverse-zones", {})
    if is_array(reverse_zones):

        def to_dict(d, k):
            d[k] = None
            return d

        reverse_zones = reduce(to_dict, reverse_zones, {})

    reverse = tuple(map(lambda rzone: parse_reverse(rzone[0], rzone[1], serial), reverse_zones.items()))
    zones = tuple(map(lambda zone: parse_zone(zone[0], zone[1], serial), data["zones"].items()))
    return (zones, reverse)


def unbound(writer: TextIO, zones: Tuple[Zone]):
    def write_line(writer, cmd, left, ttl, middle, right):
        data = w((40, 6, 8), (left, ttl, middle, right))
        writer.write(
            w(
                (INDENT, 16),
                (
                    "",
                    cmd,
                    f'"{data}"',
                ),
            )
        )
        writer.write("\n")

    writer.write("server:\n")
    for zone in zones:
        zone_name = zone.name if zone.name.endswith(".") else f"{zone.name}."

        writer.write(w((INDENT, 16), ("", LOCAL_ZONE, zone_name, "static")))
        writer.write("\n")
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
                write_line(writer, LOCAL_DATA, host.name, host.ttl, f"IN {'A    ' if host.ip.version == 4 else 'AAAA'}", host.ip)

        for srv in zone.srv:
            write_line(writer, LOCAL_DATA, srv.service, srv.ttl, "IN SRV", f"{srv.prio} {srv.weight} {srv.port} {srv.name}")

        for ptr in zone.ptr:
            write_line(writer, LOCAL_PTR, ptr.ip, ptr.ttl, "", ptr.name)


def nsd(writer: str, zones: Tuple[Zone], revers_zones: Tuple[ReverseZone]):
    directory = writer
    master_dir = f"{directory}/master"

    os.makedirs(directory, exist_ok=True)
    os.makedirs(master_dir, exist_ok=True)

    def wline(writer, value, ttl, type, data, show_in=False):
        if show_in:
            i = "IN"
        else:
            i = ""

        writer.write(w((24, 8, 8), (value, i, type, data)))
        writer.write("\n")

    with open(f"{directory}/zones.conf", "w") as zone_conf:
        ptr_zones = []

        for zone in zones:
            zone_name = zone.name[:-1] if zone.name.endswith(".") else zone.name
            zone_conf.write("zone:\n")
            zone_conf.write(f"    name: {zone_name}\n")
            zone_conf.write(f"    zonefile: master/{zone_name}.zone\n")
            with open(f"{master_dir}/{zone_name}.zone", "w") as zone_file:
                zone_file.write(f"$ORIGIN {zone_name}.\n")
                zone_file.write(f"$TTL {zone.ttl}\n")
                zone_file.write("\n")
                wline(zone_file, "@", "", "SOA", f"{zone.ns[0].name} {zone.email} (", show_in=True)
                wline(zone_file, "", "", "", f"  {ljust(zone.serial,12)}; serial number")
                wline(zone_file, "", "", "", f"  {ljust(zone.refresh,12)}; refresh")
                wline(zone_file, "", "", "", f"  {ljust(zone.retry,12)}; retry")
                wline(zone_file, "", "", "", f"  {ljust(zone.expire,12)}; expire")
                wline(zone_file, "", "", "", f"  {ljust(zone.nrc_ttl,12)}; min ttl")
                wline(zone_file, "", "", "", f")")

                for ns in zone.ns:
                    wline(zone_file, "", "", "NS", ns.name)

                for mx in zone.mx:
                    prio = "MX " + str(mx.prio).rjust(4, " ")
                    wline(zone_file, "", "", prio, mx.name)

                for hostname in zone.a:
                    first = True
                    name = hostname
                    if name == f"{zone_name}.":
                        name = "@"
                    elif hostname.endswith(f"{zone_name}."):
                        name = hostname[: -len(zone_name) - 2]
                    hosts = zone.a[hostname]
                    hosts4 = [h for h in hosts if h.ip.version == 4]
                    hosts6 = [h for h in hosts if h.ip.version == 6]

                    for host in hosts4:
                        ttl = host.ttl if host.ttl is not None else ""
                        if not first:
                            name = ""
                        first = False
                        wline(zone_file, name, ttl, "A", host.ip)
                    for host in hosts6:
                        ttl = host.ttl if host.ttl is not None else ""
                        if not first:
                            name = ""
                        first = False
                        wline(zone_file, name, ttl, "AAAA", host.ip)

                for srv in zone.srv:
                    ttl = srv.ttl if srv.ttl is not None else ""
                    service = srv.service[: -len(zone_name) - 2] if srv.service.endswith(f"{zone_name}.") else srv.service
                    wline(zone_file, service, ttl, "SRV", f"{srv.prio} {srv.weight} {srv.port} {srv.name}")

                ptr_zones = ptr_zones + zone.ptr

        for reverse_zone in revers_zones:
            ptrs = [ptr for ptr in ptr_zones if ptr.ip in reverse_zone.network]
            if len(ptrs) == 0:
                break
            network = reverse_zone.network

            if network.version == 4:
                split = 32 - network.prefixlen >> 3
            else:
                split = 128 - network.prefixlen >> 2

            zone_name = ".".join(network.network_address.reverse_pointer.split(".")[split:])

            zone_conf.write("zone:\n")
            zone_conf.write(f"    name: {zone_name}\n")
            zone_conf.write(f"    zonefile: master/{zone_name}.zone\n")
            with open(f"{master_dir}/{zone_name}.zone", "w") as zone_file:
                zone_file.write(f"$ORIGIN {zone_name}.\n")
                zone_file.write(f"$TTL {zone.ttl}\n")
                zone_file.write("\n")
                wline(zone_file, "@", "", "SOA", f"{zone.ns[0].name} {zone.email} (", show_in=True)
                wline(zone_file, "", "", "", f"  {ljust(zone.serial,12)}; serial number")
                wline(zone_file, "", "", "", f"  {ljust(zone.refresh,12)}; refresh")
                wline(zone_file, "", "", "", f"  {ljust(zone.retry,12)}; retry")
                wline(zone_file, "", "", "", f"  {ljust(zone.expire,12)}; expire")
                wline(zone_file, "", "", "", f"  {ljust(zone.nrc_ttl,12)}; min ttl")
                wline(zone_file, "", "", "", f")")

                for ptr in ptrs:
                    ip_entry = ".".join(ptr.ip.reverse_pointer.split(".")[:split])
                    ttl = ptr.ttl if ptr.ttl is not None else ""
                    wline(zone_file, ip_entry, ttl, "PTR", ptr.name)
                    # zone_file.write(f"{ip_entry}\t{ttl}\tPTR\t{ptr.name}\n")


def process(input_data: str, writer, serial, output_format):
    zones = parse(input_data, serial)

    if output_format == "unbound":
        unbound(writer, zones[0])
    elif output_format == "nsd":
        nsd(writer, zones[0], zones[1])
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

    if args.format == "unbound":
        if args.out is None:
            out = sys.stdout
        else:
            out = open(args.out, "w")
    elif args.format == "nsd":
        if args.out is None:
            out = "./nsd"
        else:
            out = args.out

    process(input_data, out, new_serial, args.format)

    write_serial(args.serial, new_serial)


if __name__ == "__main__":
    main()
