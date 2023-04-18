# zonefile
Zonefile creates a unbound local zone configuration from yaml

### Motivation
I find it hard to configure traditional DNS zone files, because the information of a single host is split up in different files. This is the consequence of A/AAAA and PTR records belonging to different zones. Even with unbound local zones, which I like very much, you have to create four entries for a single host with IP4 and IP6 addresses. But the configuration of dnsmasq showed me, how it could be solved in a better way. So I created this project to configure my DNS entries from a single YAML-file.

This utility creates a unbound local-zone configuration from the yaml data. Perhaps a nsd configuration will follow.

## Installation
This is a simple nodejs project, so npm i will install all dependencies.

## Configuration
A typical configuration file, test1.yaml in this case, will look like this:

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
        mickey: [little, mouse, 192.168.1.10,fd00::10]
        mini: [192.168.1.11,fd00::11]

And the output of

    zonefile -i test1.yaml
will be

    server:
  
        local-zone:      home.arpa static
        local-data:      "home.arpa.                               10800  IN SOA  ns1.home.arpa admin.some.email.address. 2023031800 7200 3600 1209600 3600"
        local-data:      "home.arpa.                                      IN NS   ns1.home.arpa."
        local-data:      "home.arpa.                                      IN MX   10 mail.home.arpa."
        local-data:      "extern.home.arpa.                               IN A    172.16.0.1"
        local-data:      "extern2.home.arpa.                              IN AAAA fdff::1"
        local-data:      "mickey.home.arpa.                               IN A    192.168.1.10"
        local-data:      "little.home.arpa.                               IN A    192.168.1.10"
        local-data:      "mouse.home.arpa.                                IN A    192.168.1.10"
        local-data:      "mickey.home.arpa.                               IN AAAA fd00::10"
        local-data:      "little.home.arpa.                               IN AAAA fd00::10"
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

### Configuration structure
The used yaml file has to belong to the following structure: The first level introduces dns domains. You could define multiple domains in just on file. The next level are the different types of dns entries. They are
 - soa

   The soa entry defines a soa record. Zonefile will use sane defaults for most entries, so you only have to provide nameserver and email.
   - **nameserver**: The primary nameserver of the domain 
   - **email**: The email address of the domain admin. @-chars will be converted to dots
   - **serial**: The serial number of the zone. It will be automatically computed if omitted.
   - **refresh**: Master slave refresh interval in seconds. 
   - **retry**: Master slave retry time in seconds.
   - **expire**: Zone file expiry for slaves time in seconds.
   - **nrc_ttl**: Negative record ttl, this is the time to wait before query a negative response again.  
   - **ttl**: The Time-To-Life for this entry

 - nameserver
   
   This defines a nameserver entry. It can be an array of dns names or an object with host entries. If you provide an ip address for such an entry, it will generate an A/AAAA record for every provided ip and the corresponding ptr records.
 - mx
   
   It defines the mx entries for the domain. It is an object with the mx names and at least the mx priority as first argument. If you provide ip addresses with this entry, zonefile will generate A/AAAA records and corresponding ptr records.
 - addresses
   
   The entries in this section will generate A/AAAA records, but no PTR record.
 - hosts
   
   These entries will generate A/AAAA and PTR records for all given ip addresses. You can also provide additional names, which will generate additional A/AAAA records for the given ip addresses.

For all configuration entries except soa: If the last parameter is a number, it will be used as ttl for the generated entries.

## Usage
This utility has the following command line parameter:

    Usage: zonefile [options]

    Program to generate zonefiles from yaml

    Options:
      -V, --version         output the version number
      -i, --input <VALUE>   Input YAML data (default stdin).
      -o, --output <VALUE>  Output zone data (default stdout).
      -s, --serial <VALUE>  File containing serial number. (default: ".serial")
      -h, --help            display help for command

The input parameter specifies the yaml file to process. If it is omitted, then it will read from stdin. The output parameter specifies the file to write the result to. If it is omitted, it will default to stdout. The serial parameter specifies the serial number file for all generated soa entries. This allows the utility to change the serial number for every run.

## SOA serial number
One annoying and from me mostly forgotten action is to change the serial number of changed zonefiles. The zonefile utility computes the serial number in the following way: It has 4 digits for the current year, than 2 digits for the current month, 2 digits for the current day of the month and 2 digits for the version of the day. A typical serial number is 2023041803. Unfortunately the serial number can not be so long, that we could use a readable timestamp. So the utility needs to remember, which was the last used serial number. Therefore it is saved in the serial file, which defaults to .serial. You can change this file to use an other serial number, but it will use the max from the computed serial number an the one in the serial file.
