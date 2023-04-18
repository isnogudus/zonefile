# zonefile
Zonefile creates a unbound local zone configuration from yaml

### Motivation
I find it hard to configure traditional DNS zone files, because the information of a single host is split up in different files. This is the consequence of A/AAAA and PTR records belonging to different zones. Even with unbound local zones, which I like very much, you have to create four entries for a single host with IP4 and IP6 addresses. But the configuration of dnsmasq showed me, how it could be solved in a better way. So I created this project to configure my DNS entries from a single YAML-file.

This utility creates a unbound local-zone configuraten from the yaml data. Perhaps a nsd configuration will follow.

## Installation
This is a simple nodejs project, so npm i will install all dependencies.

## Configuration
A typical configuration file will look like this:
  home.arpa:
  soa:
    nameserver: ns1.home.arpa
    email: admin@some.email.address
  nameserver:
    ns1: [192.168.1.1,fd00::1]
  mx:
    mail: [10, 192.168.1.2, fd00::2]
  addresses:
    extern: 172.16.0.1
    extern2: fdff::1
    extern3: [172.16.0.2 fdff::2]
  hosts:
    mickey: [litlle, mouse, 192.168.1.10,fd00::10]
    mini: [192.168.1.11,fd00::11]

And the output will be:
  server:
  
    local-zone:      home.arpa static
    local-data:      "home.arpa.                               10800  IN SOA  ns1.home.arpa admin.some.email.address. 2023031800 7200 3600 1209600 3600"
    local-data:      "home.arpa.                                      IN NS   ns1.home.arpa."
    local-data:      "home.arpa.                                      IN MX   10 mail.home.arpa."
    local-data:      "extern.home.arpa.                               IN A    172.16.0.1"
    local-data:      "extern2.home.arpa.                              IN AAAA fdff::1"
    local-data:      "mickey.home.arpa.                               IN A    192.168.1.10"
    local-data:      "litlle.home.arpa.                               IN A    192.168.1.10"
    local-data:      "mouse.home.arpa.                                IN A    192.168.1.10"
    local-data:      "mickey.home.arpa.                               IN AAAA fd00::10"
    local-data:      "litlle.home.arpa.                               IN AAAA fd00::10"
    local-data:      "mouse.home.arpa.                                IN AAAA fd00::10"
    local-data:      "mini.home.arpa.                                 IN A    192.168.1.11"
    local-data:      "mini.home.arpa.                                 IN AAAA fd00::11"
    local-data:      "ns1.home.arpa.                                  IN A    192.168.1.1"
    local-data:      "ns1.home.arpa.                                  IN AAAA fd00::1"
    local-data:      "mail.home.arpa.                                 IN A    192.168.1.2"
    local-data:      "mail.home.arpa.                                 IN AAAA fd00::2"
    local-data-ptr:  "192.168.1.10                                            mickey.home.arpa."
    local-data-ptr:  "fd00::10                                                mickey.home.arpa."
    local-data-ptr:  "192.168.1.11                                            mini.home.arpa."
    local-data-ptr:  "fd00::11                                                mini.home.arpa."
    local-data-ptr:  "192.168.1.1                                             ns1.home.arpa."
    local-data-ptr:  "fd00::1                                                 ns1.home.arpa."
    local-data-ptr:  "192.168.1.2                                             mail.home.arpa."
    local-data-ptr:  "fd00::2                                                 mail.home.arpa."
