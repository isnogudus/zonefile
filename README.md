# zonefile

A Python tool for generating DNS zone files from TOML configuration files. Supports both **Unbound** and **NSD** output formats.

## Features

- **TOML-based configuration** for clear and maintainable DNS zone definitions
- **Dual format support**: Generates zone files for Unbound and NSD
- **Forward and reverse zones**: Automatic PTR record generation
- **Automatic serial management**: Date-based serial numbers (YYYYMMDDNN)
- **Comprehensive validation**: RFC-compliant validation of DNS names, IP addresses, TTLs
- **Record types**: A, AAAA, CNAME, MX, NS, SRV, PTR
- **IPv4 and IPv6**: Full support for both IP versions
- **Type-safe**: Fully typed with Python type hints
- **Well-tested**: Comprehensive unit test suite with 47 tests

## Installation

```bash
# Python 3.11+ required
git clone <repository-url>
cd zonefile

# No external dependencies needed
# Uses only Python standard library
```

### Requirements

- Python 3.11 or higher
- No external dependencies

## Quick Start

### 1. Create TOML Configuration

```toml
[defaults]
email = "admin@example.com"
nameserver = "ns1.example.com."
ttl = 3600

[[zone]]
name = "example.com"

[zone.hosts]
www = "192.168.1.10"
mail = ["192.168.1.20", "2001:db8::20"]
"@" = {ip = "192.168.1.1", alias = ["ftp", "web"]}

[zone.cname]
blog = "www"

[[zone]]
name = "example.org"

[zone.hosts]
www = "10.0.1.1"
```

### 2. Generate Zone Files

**For Unbound:**
```bash
./zonefile.py -i zones.toml -o unbound.conf -f unbound
```

**For NSD:**
```bash
./zonefile.py -i zones.toml -o ./nsd -f nsd
```

## Usage

```
zonefile [-h] [-i INPUT] [-o ZONEFILE] [-s SERIAL_FILE] [-f {unbound,nsd}]

Options:
  -i INPUT          Input TOML file (default: stdin)
  -o ZONEFILE       Output file or directory
                    Default: stdout for unbound, ./nsd/ for nsd
  -s SERIAL_FILE    File for serial number storage (default: .serial)
  -f FORMAT         Output format: unbound or nsd (default: unbound)
  -h, --help        Show help message
```

### Examples

```bash
# Read from stdin, write to stdout
cat zones.toml | ./zonefile.py

# Convert TOML to Unbound config
./zonefile.py -i my-zones.toml -o /etc/unbound/local.conf

# Generate NSD zone files
./zonefile.py -i my-zones.toml -o /etc/nsd -f nsd

# Use custom serial file
./zonefile.py -i zones.toml -s ~/.dns-serial
```

## TOML Configuration Format

### Defaults Section

Global default values for all zones:

```toml
[defaults]
email = "admin@example.com"     # SOA RNAME (@ converted to .)
nameserver = "ns1.example.com." # Primary nameserver (FQDN with trailing dot)
ttl = 3600                      # Default TTL in seconds
refresh = 7200                  # SOA Refresh
retry = 3600                    # SOA Retry (must be ≤ refresh)
expire = 1209600                # SOA Expire (14 days)
nrc-ttl = 3600                  # Negative Response Caching TTL
srv-prio = 5                    # Default priority for SRV records
srv-weight = 10                 # Default weight for SRV records
mx-prio = 10                    # Default priority for MX records
with-ptr = true                 # Enable automatic PTR record generation
```

All fields except `email` and `nameserver` are optional with sensible defaults.

### Zone Definitions

#### Basic Configuration

```toml
[[zone]]
name = "example.com"
email = "hostmaster@example.com"  # Optional, overrides default
nameserver = ["ns1", "ns2"]       # Optional, can be string or array
ttl = 7200                        # Optional, overrides default
with-ptr = false                  # Optional, disables PTR generation
```

#### Hosts

```toml
[zone.hosts]
# Simple IP assignment
www = "192.168.1.10"

# Multiple IPs (creates A and AAAA records)
mail = ["192.168.1.20", "2001:db8::20"]

# Extended configuration with aliases
webserver = {
    ip = ["192.168.1.30", "2001:db8::30"],
    alias = ["web", "www2"],        # Additional hostnames for same IPs
    ttl = 300,                      # Custom TTL value
    with-ptr = false                # No PTR records for this host
}

# Zone apex (@) with aliases
"@" = {ip = "192.168.1.1", alias = ["ftp", "www"]}

# Wildcards (only leftmost label allowed)
"*" = "192.168.1.100"
```

**Generated records for `webserver`:**
- `webserver.example.com. 300 IN A 192.168.1.30`
- `webserver.example.com. 300 IN AAAA 2001:db8::30`
- `web.example.com. 300 IN A 192.168.1.30`
- `web.example.com. 300 IN AAAA 2001:db8::30`
- `www2.example.com. 300 IN A 192.168.1.30`
- `www2.example.com. 300 IN AAAA 2001:db8::30`

#### CNAME Records

```toml
[zone.cname]
# Simple CNAME
blog = "www"

# CNAME with FQDN (external target)
cdn = "cdn.provider.com."

# With custom TTL
alias = {target = "www", ttl = 600}
```

#### MX Records

```toml
# String syntax (simple MX with default priority)
mx = "mail.example.com"

# Dict syntax
mx = {name = "mail", prio = 10}

# List with default priority from [defaults]
mx = ["mail1.example.com.", "mail2.example.com."]

# Dict list with custom priorities
mx = [
    {name = "mail1", prio = 10},
    {name = "mail2", prio = 20, ttl = 7200}
]
```

#### SRV Records

```toml
[zone.srv]
# _service._proto format (underscores required)
"_http._tcp" = {port = 80, target = "www"}
"_https._tcp" = {port = 443, target = "www", prio = 10, weight = 20}
"_ldap._tcp" = {port = 389, target = "ldap.example.com."}

# MQTT services
"_mqtt._tcp" = {port = 1883, target = "mqtt"}
"_mqtts._tcp" = {port = 8883, target = "mqtt"}

# CalDAV/CardDAV
"_caldavs._tcp" = {port = 443, target = "@"}  # @ = Zone apex
"_carddavs._tcp" = {port = 443, target = "@"}
```

**Fields:**
- `port`: Required (1-65535)
- `target`: Required (hostname or FQDN)
- `prio`: Optional (default from `srv-prio`)
- `weight`: Optional (default from `srv-weight`)
- `ttl`: Optional (default from zone TTL)

### Reverse Zones

Automatic generation of PTR records for IP networks:

```toml
[reverse]
# IPv4 (creates in-addr.arpa zones)
"10.0.1.0/24" = {}
"192.168.0.0/16" = {nameserver = "ns.example.com.", ttl = 7200}

# IPv6 (creates ip6.arpa zones)
"2001:db8::/32" = {email = "ipv6-admin@example.com"}
"fd00:1234:5678:1::/64" = {}
```

**Behavior:**
- PTR records are auto-generated for all hosts with `with-ptr = true` (default)
- Zone name is automatically calculated from network address
- Overlapping networks are rejected (validation error)
- Only one PTR record per IP address allowed (duplicates cause error)

## Output Formats

### Unbound

Generates configuration file with `local-zone` and `local-data` directives:

```
server:
local-zone: example.com. static
local-data: "example.com.                10800 IN SOA  ns1.example.com. admin.example.com. 2025011800 7200 3600 1209600 3600"
local-data: "example.com.                10800 IN NS   ns1.example.com."
local-data: "example.com.                10800 IN MX   10 mail.example.com."
local-data: "www.example.com.            10800 IN A    192.168.1.10"
local-data: "mail.example.com.           10800 IN A    192.168.1.20"
local-data: "mail.example.com.           10800 IN AAAA 2001:db8::20"
local-data-ptr: "192.168.1.20            10800 mail.example.com."
local-data-ptr: "2001:db8::20            10800 mail.example.com."
```

**Integration with Unbound:**
```bash
# In /etc/unbound/unbound.conf
include: /etc/unbound/local.conf

# Generate zonefile and reload Unbound
./zonefile.py -i zones.toml -o /etc/unbound/local.conf
unbound-control reload
```

### NSD

Creates directory structure with zone files:

```
nsd/
├── zones.conf          # Zone definitions for inclusion in nsd.conf
└── master/
    ├── example.com.zone
    ├── 1.0.10.in-addr.arpa.zone
    └── 8.b.d.0.1.0.0.2.ip6.arpa.zone
```

**zones.conf:**
```
zone:
    name: example.com.
    zonefile: master/example.com.zone

zone:
    name: 1.0.10.in-addr.arpa.
    zonefile: master/1.0.10.in-addr.arpa.zone
```

**example.com.zone** (RFC 1035 standard format):
```
$ORIGIN example.com.
$TTL 10800

@                            IN SOA     ns1.example.com. admin.example.com. (
                                           2025011800  ; serial number
                                           7200        ; refresh
                                           3600        ; retry
                                           1209600     ; expire
                                           3600        ; min ttl
                                        )
                                NS      ns1.example.com.
                                MX   10 mail.example.com.
www                             A       192.168.1.10
mail                            A       192.168.1.20
                                AAAA    2001:db8::20
```

**Integration with NSD:**
```bash
# In /etc/nsd/nsd.conf
include: /etc/nsd/zones.conf

# Generate zonefiles and reload NSD
./zonefile.py -i zones.toml -o /etc/nsd -f nsd
nsd-control reload
```

## Serial Number Management

Serial numbers are automatically generated in format `YYYYMMDDNN` (RFC 1912):

- `YYYY`: Year (4 digits)
- `MM`: Month (01-12)
- `DD`: Day (01-31)
- `NN`: Change counter (00-99) for multiple updates per day

**Example:** `2025011803` = January 18, 2025, 3rd change of the day

### Automatic Incrementing

The last serial number is stored in `.serial` (or specified via `-s`):

```bash
# First run on January 18, 2025
./zonefile.py -i zones.toml
# Generates serial: 2025011800

# Second run same day
./zonefile.py -i zones.toml
# Generates serial: 2025011801 (incremented)

# Run next day
./zonefile.py -i zones.toml
# Generates serial: 2025011900
```

## Validation

The tool performs comprehensive RFC-compliant validation:

### DNS Names
- **Length**: Max 253 characters (FQDN)
- **Labels**: Max 63 characters per label
- **Characters**: Alphanumeric, `-` and `_` (per RFC 952/1123)
- **Wildcards**: Only as leftmost label (`*.example.com`)
- **Format**: Labels cannot start/end with `-`

### IP Addresses
- IPv4: Validation via Python's `ipaddress.IPv4Address`
- IPv6: Full support including compressed notation (`::1`, `2001:db8::1`)
- Networks: CIDR notation validation (`10.0.0.0/8`, `2001:db8::/32`)

### TTL Values
- Range: 0 to 4,294,967,295 (2³² - 1, unsigned int32)
- Type: Integer only (no strings or floats)

### Ports (SRV Records)
- Range: 1-65535
- Port 0 is invalid

### Priorities
- **MX**: 0-32,767 (signed int16)
- **SRV**: 0-65,535 (unsigned int16)

### Weights (SRV)
- Range: 0-65,535 (unsigned int16)

### SOA Consistency
- `retry` ≤ `refresh` (RFC 1035)
- All time values must be positive integers

### Duplicate Detection
- **PTR Records**: One IP can only have one PTR record (error on duplicates)
- **Network Overlaps**: Reverse zones cannot overlap

### Error Messages

Validation errors produce clear, actionable messages:

```
ValueError: zone(example.com).hosts(www).ip: Invalid IP address: '192.168.1.999'
ValueError: zone(example.com).name: DNS label too long (max 63 chars): very-long-subdomain-name-that-exceeds-the-limit
ValueError: Duplicate PTR record for IP 192.168.1.10 (www.example.com. server.example.com.)
ValueError: Reverse Zone Networks overlap: 10.0.0.0/16 and 10.0.1.0/24
```

## Tests

Comprehensive unit test suite with 47 tests:

```bash
# Run all tests
python3 test_zonefile.py

# Run with verbose output
python3 test_zonefile.py -v

# Run specific test class
python3 -m unittest test_zonefile.TestParseHostStr
```

**Test categories:**
- Utility functions (is_array, to_array, type guards)
- Validation functions (validate_int, validate_host, validate_email)
- Parsers (parse_hosts, parse_mx, parse_srv, parse_cnames)
- Integration tests (complete TOML→Zone→Output pipeline)

## Architecture

### Key Design Principles

- **Type Safety**: Fully typed with Python type hints and TypeGuards
- **Immutability**: NamedTuples for all DNS records
- **DRY**: Generic `convert_to_record()` eliminates code duplication
- **Clear Errors**: Contextual error messages with full path (e.g., `zone(example.com).hosts(www).ip`)
- **Validation First**: All input validated before processing
- **No External Dependencies**: Uses only Python standard library

### Code Structure

```
zonefile.py
├── Data Models (NamedTuples)
│   ├── ARecord, PtrRecord, NsRecord, MxRecord, SrvRecord, CnameRecord
│   └── RecordMeta, RecordTable
├── Type Guards
│   ├── is_dict_str_any, is_dict_key_any, is_list_type
│   └── Type-safe runtime validation
├── Validation Functions
│   ├── validate_int, validate_bool, validate_host, validate_email
│   └── RFC-compliant DNS validation
├── Parsing Functions
│   ├── parse_hosts, parse_nameserver, parse_mx, parse_srv, parse_cnames
│   ├── parse_zone (forward zones)
│   └── parse_reverse (reverse zones)
├── Output Generators
│   ├── unbound() - Unbound format
│   └── nsd() - NSD format
└── Main Entry Point
    └── parse() - TOML to zone configuration
```

## Known Limitations

- **No DNSSEC support**: Signing must be done externally (e.g., via `ldns-signzone`)
- **No DNAME records**: Only CNAME supported
- **No CAA/TLSA/SSHFP records**: Only standard record types (A, AAAA, CNAME, MX, NS, SRV, PTR)
- **No TXT records**: Could be added in future
- **No zonefile imports**: No `$INCLUDE` or external references
- **No dynamic updates**: Static zonefile generation only

## Contributing

Contributions welcome! Please ensure:

1. **Tests**: New features require unit tests
2. **Type Hints**: Code must be fully typed (`pyright` clean)
3. **Validation**: Input validation is mandatory
4. **Documentation**: Update README and docstrings

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Related Projects

- [Unbound](https://nlnetlabs.nl/projects/unbound/about/) - Validating, recursive DNS resolver
- [NSD](https://nlnetlabs.nl/projects/nsd/about/) - Authoritative DNS nameserver
- [dns-zonefile](https://github.com/elgs/dns-zonefile) - JavaScript library for zonefile parsing
