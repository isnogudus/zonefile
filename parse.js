import ipaddr from 'ipaddr.js';

import { toArray } from './util.js';

function hostString(host, zone) {
	return host.endsWith('.') ? host : `${host}.${zone}.`;
}

function createMX(zone, hostname, prio, ttl) {
	return { zone, name: hostString(hostname, zone), prio, ttl };
}

function createNameserver(zone, hostname, ttl) {
	return { zone, name: hostString(hostname, zone), ttl };
}

function createA(zone, hostname, ip, ttl) {
	return { name: hostString(hostname, zone), ip: ipaddr.parse(ip), ttl };
}

function createPtr(zone, hostname, ip, ttl) {
	return { name: hostString(hostname, zone), ip: ipaddr.parse(ip), ttl };
}

function createZone(name, soa, SERIAL) {
	const {
		nameserver,
		email,
		serial = SERIAL,
		refresh = 7200,
		retry = 3600,
		expire = 1209600,
		nrc_ttl = 3600,
		ttl = 10800
	} = soa;

	return {
		name,
		nameserver,
		email: email.replace('@', '.'),
		serial,
		refresh,
		retry,
		expire,
		nrc_ttl,
		ttl,
		hosts: [],
		ptrs: [],
		ns: [],
		mx: []
	};
}

export default function parseZone(zoneData, SERIAL) {
	return Object.keys(zoneData).map((name) => {
		const { soa, hosts, addresses, nameserver, mx } = zoneData[name];
		const zone = createZone(name, soa, SERIAL);

		for (const host in addresses) {
			const info = toArray(addresses[host]);
			const ttl = isNaN(info.at(-1)) ? undefined : info.pop();
			const ips = info.filter((i) => ipaddr.isValid(i));
			const aliases = info.filter((a) => !ips.includes(a));
			ips.forEach((ip) => {
				zone.hosts.push(createA(name, host, ip, ttl));
				aliases.forEach((alias) => {
					zone.hosts.push(createA(name, alias, ip, ttl));
				});
			});
		}
		for (const host in hosts) {
			const info = toArray(hosts[host]);
			const ttl = isNaN(info.at(-1)) ? undefined : info.pop();
			const ips = info.filter((i) => ipaddr.isValid(i));
			const aliases = info.filter((a) => !ips.includes(a));
			ips.forEach((ip) => {
				zone.hosts.push(createA(name, host, ip, ttl));
				zone.ptrs.push(createPtr(name, host, ip, ttl));
				aliases.forEach((alias) => {
					zone.hosts.push(createA(name, alias, ip, ttl));
				});
			});
		}
		if (Array.isArray(nameserver)) {
			nameserver.forEach((host) => {
				zone.ns.push(createNameserver(name, host));
			});
		} else {
			for (const host in nameserver) {
				const info = toArray(nameserver[host]);
				const ttl = isNaN(info.at(-1)) ? undefined : info.pop();
				const ips = info.filter((i) => ipaddr.isValid(i));
				const ns = createNameserver(name, host, ttl);
				zone.ns.push(ns);

				if (ips.length > 0) {
					if (zone.hosts.find((h) => h.name === ns.name)) continue;

					ips.forEach((ip) => {
						const aRecord = createA(name, host, ip, ttl);
						zone.hosts.push(aRecord);
						const ipString = ipaddr.parse(ip).toString();
						if (!zone.ptrs.find((ptr) => ptr.ip.toString() === ipString))
							zone.ptrs.push(createPtr(name, host, ip, ttl));
					});
				}
			}
		}
		for (const host in mx) {
			const info = toArray(mx[host]);
			const prio = info.shift();
			if (isNaN(prio))
				throw new Error(`First Argument to MX is prio (Number): ${zone} ${host} ${prio}`);
			const ttl = isNaN(info.at(-1)) ? undefined : info.pop();
			const ips = info.filter((i) => ipaddr.isValid(i));
			const record = createMX(name, host, ttl);
			zone.mx.push(mx);

			if (ips.length > 0) {
				if (zone.hosts.find((h) => h.name === record.name)) continue;

				ips.forEach((ip) => {
					const aRecord = createA(name, host, ip, ttl);
					zone.hosts.push(aRecord);
					const ipString = ipaddr.parse(ip).toString();
					if (!zone.ptrs.find((ptr) => ptr.ip.toString() === ipString))
						zone.ptrs.push(createPtr(name, host, ip, ttl));
				});
			}
		}
		return zone;
	});
}