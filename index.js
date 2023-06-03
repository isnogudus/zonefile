#! /usr/bin/env node

import { existsSync, readFileSync } from 'fs';
import yaml from 'yaml';
import { Command, Option } from 'commander';
import { writeFile } from 'fs/promises';
import { createReadStream, createWriteStream } from 'fs';

import { streamAsPromise } from './util.js';
import parse from './parse.js';
import unbound from './unbound.js';

let program = new Command();
program.name('zonefile').description('Program to generate zonefiles from yaml').version('0.1.0');
program.option('-i, --input <VALUE>', 'Input YAML data (default stdin).');
program.option('-o, --output <VALUE>', 'Output zone data (default stdout).');
program.option('-s, --serial <VALUE>', 'File containing serial number.', '.serial');
program.addOption(
	new Option('-f, --format <VALUE>', 'Output format.')
		.default('unbound')
		.choices(['unbound', 'nsd'])
);

program.parse();

const options = program.opts();

const zoneStream = options.input ? createReadStream(options.input) : process.stdin;
const writer = options.output ? createWriteStream(options.output) : process.stdout;
const serial_file = options.serial ?? '.serial';

const now = new Date();
const SERIAL = Math.max(
	now.getFullYear() * 1000000 + (now.getMonth() + 1) * 10000 + now.getDate() * 100,
	existsSync(serial_file) ? Number(readFileSync(serial_file)) + 1 : 0
);

await writeFile(serial_file, `${SERIAL}\n`);

const zoneData = yaml.parse(await streamAsPromise(zoneStream));

const zones = parse(zoneData, SERIAL);

switch (options.format) {
	case 'unbound':
		unbound(writer, zones);
		break;
}
