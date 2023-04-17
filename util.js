export function toArray(obj) {
	if (obj === undefined) return [];

	return Array.isArray(obj) ? obj : [obj];
}

export function streamAsPromise(stream) {
	return new Promise((resolve, reject) => {
		let data = '';
		stream.on('data', (chunk) => (data += chunk));
		stream.on('end', () => resolve(data));
		stream.on('error', (error) => reject(error));
	});
}
