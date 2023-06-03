const LOCAL_DATA = 'local-data:     ';
const LOCAL_ZONE = 'local-zone:     ';
const LOCAL_PTR = 'local-data-ptr: ';
const INDENT = ' '.repeat(4);

function writeLine(writer, cmd, left, ttl, middle, right) {
	writer.write(INDENT);
	writer.write(String(cmd).padEnd(15, ' '));
	writer.write(' "');
	writer.write(String(left).padEnd(40, ' '));
	writer.write(' ');
	if (ttl) writer.write(String(ttl).padEnd(6, ' '));
	else writer.write(' '.repeat(6));
	writer.write(' ');
	writer.write(String(middle).trim().padEnd(7, ' '));
	writer.write(' ');
	writer.write(String(right));
	writer.write('"\n');
}

function localData(writer, left, ttl, middle, right) {
	writeLine(writer, LOCAL_DATA, left, ttl, middle, right);
}

function localPtr(writer, ip, ttl, name) {
	writeLine(writer, LOCAL_PTR, ip, ttl, '', name);
}

function soa(writer, data) {
	const { name, ns, email, serial, refresh, retry, expire, nrc_ttl, ttl } = data;

	const value = `${ns[0].name} ${email.replace(
		'@',
		'.'
	)}. ${serial} ${refresh} ${retry} ${expire} ${nrc_ttl}`;
	localData(writer, `${name}.`, ttl, 'IN SOA', value);
}

function entry(writer, data) {
	const { name, ip, ttl } = data;
	localData(writer, name, ttl, `IN ${ip.kind() === 'ipv4' ? 'A   ' : 'AAAA'}`, ip.toString());
}

function ptr_record(writer, data) {
	const { ip, name, ttl } = data;
	localPtr(writer, ip, ttl, name);
}

function ns_record(writer, data) {
	const { name, zone, ttl } = data;
	localData(writer, `${zone}.`, ttl, 'IN NS', name);
}

function mx_record(writer, data) {
	const { name, prio, zone, ttl } = data;
	localData(writer, `${zone}.`, ttl, 'IN MX', `${prio} ${name}`);
}

function srv_record(writer, data) {
	const { name, service, prio, weight, port, ttl } = data;
	localData(writer, service, ttl, 'IN SRV', `${prio} ${weight} ${port} ${name}`);
}

export default function unbound(writer, zones) {
	writer.write('server:\n');

	zones.forEach((zone) => {
		const { name, hosts, ptrs, ns, mx, srv } = zone;

		writer.write(`\n${INDENT}${LOCAL_ZONE} ${name} static\n`);
		soa(writer, zone);
		ns.forEach((host) => {
			ns_record(writer, host);
		});
		mx.forEach((host) => {
			mx_record(writer, host);
		});
		hosts.forEach((host) => {
			entry(writer, host);
		});
		ptrs.forEach((ptr) => {
			ptr_record(writer, ptr);
		});
		srv.forEach((service) => {
			srv_record(writer, service);
		});
	});
}
