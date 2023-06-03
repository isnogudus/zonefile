import ipaddr from 'ipaddr.js';

import { toArray } from './util.js';

function hostString(host, zone) {
	if (host === '.') return `${zone}.`;
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

function createSRV(zone, hostname, service, port, prio, weight, ttl) {
	let [name, protocol, ...rest] = service.split('.');
	if (!name.startsWith('_')) name = `_${name}`;
	if (!protocol.startsWith('_')) protocol = `_${protocol}`;
	return {
		name: hostString(hostname, zone),
		service: hostString([name, protocol, ...rest].join('.'), zone),
		prio,
		weight,
		port,
		ttl
	};
}

export default function parseZone(zoneData, SERIAL) {
	return Object.keys(zoneData).map((name) => {
		const data = zoneData[name];
		const {
			email,
			serial = SERIAL,
			refresh = 7200,
			retry = 3600,
			expire = 1209600,
			nrc_ttl = 3600,
			ttl = 10800,
			addresses,
			nameserver
		} = zoneData[name];
		let hosts = [];
		let ptrs = [];
		let ns = [];
		let mx = [];
		let srv = [];

		for (const host in addresses) {
			const info = toArray(addresses[host]);
			const ttl = isNaN(info.at(-1)) ? undefined : info.pop();
			const ips = info.filter((i) => ipaddr.isValid(i));
			const aliases = info.filter((a) => !ips.includes(a));
			ips.forEach((ip) => {
				hosts.push(createA(name, host, ip, ttl));
				aliases.forEach((alias) => {
					hosts.push(createA(name, alias, ip, ttl));
				});
			});
		}
		for (const host in data.hosts) {
			const info = toArray(data.hosts[host]);
			const ttl = isNaN(info.at(-1)) ? undefined : info.pop();
			const ips = info.filter((i) => ipaddr.isValid(i));
			const aliases = info.filter((a) => !ips.includes(a));
			ips.forEach((ip) => {
				hosts.push(createA(name, host, ip, ttl));
				ptrs.push(createPtr(name, host, ip, ttl));
				aliases.forEach((alias) => {
					hosts.push(createA(name, alias, ip, ttl));
				});
			});
		}
		if (typeof nameserver === 'string' || nameserver instanceof String) {
			ns.push(createNameserver(name, nameserver));
		} else if (Array.isArray(nameserver)) {
			nameserver.forEach((host) => {
				ns.push(createNameserver(name, host));
			});
		} else {
			for (const host in nameserver) {
				const info = toArray(nameserver[host]);
				const ttl = isNaN(info.at(-1)) ? undefined : info.pop();
				const ips = info.filter((i) => ipaddr.isValid(i));
				ns.push(createNameserver(name, host, ttl));

				if (ips.length > 0) {
					if (hosts.find((h) => h.name === ns.name)) continue;

					ips.forEach((ip) => {
						const aRecord = createA(name, host, ip, ttl);
						hosts.push(aRecord);
						const ipString = ipaddr.parse(ip).toString();
						if (!ptrs.find((ptr) => ptr.ip.toString() === ipString))
							ptrs.push(createPtr(name, host, ip, ttl));
					});
				}
			}
		}
		for (const host in data.mx) {
			const info = toArray(data.mx[host]);
			const prio = info.shift();
			if (isNaN(prio))
				throw new Error(`First Argument to MX is prio (Number): ${zone} ${host} ${prio}`);
			const ttl = isNaN(info.at(-1)) ? undefined : info.pop();
			const ips = info.filter((i) => ipaddr.isValid(i));
			const record = createMX(name, host, prio, ttl);
			mx.push(record);

			if (ips.length > 0) {
				if (hosts.find((h) => h.name === record.name)) continue;

				ips.forEach((ip) => {
					const aRecord = createA(name, host, ip, ttl);
					hosts.push(aRecord);
					const ipString = ipaddr.parse(ip).toString();
					if (!ptrs.find((ptr) => ptr.ip.toString() === ipString))
						ptrs.push(createPtr(name, host, ip, ttl));
				});
			}
		}
		for (const service in data.srv) {
			const info = data.srv[service];
			const ttl = isNaN(info.at(-1)) ? undefined : info.pop();
			let prio = 5;
			let weight = 0;
			let port = -1;
			if (!isNaN(info.at(0)) && !isNaN(info.at(1)) && !isNaN(info.at(2))) {
				prio = info.shift();
				weight = info.shift();
				port = info.shift();
			} else if (!isNaN(info.at(0)) && isNaN(info.at(1))) {
				port = info.shift();
			} else
				throw new Error(
					`Couldn't identify SRV record. It's [port, name] or [prio, weight, port, name]. Given: ${srv[service]}`
				);
			const host = info[0];
			srv.push(createSRV(name, host, service, port, prio, weight, ttl));
		}

		const zone = {
			name,
			nameserver,
			email: email.replace('@', '.'),
			serial,
			refresh,
			retry,
			expire,
			nrc_ttl,
			ttl,
			hosts,
			ptrs,
			ns,
			mx,
			srv
		};

		return zone;
	});
}
