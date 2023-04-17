module.exports = {
	root: true,
	extends: ['eslint:recommended', 'prettier'],
	parserOptions: {
		sourceType: 'module',
		ecmaVersion: 2022
	},
	env: {
		browser: true,
		es2017: true,
		node: true
	},
	settings: {
		'svelte3/ignore-warnings': (warning) => warning.code.startsWith('a11y-')
	},
	rules: {
		'constructor-super': 'error',
		'linebreak-style': ['error', 'unix'],
		quotes: ['error', 'single', { avoidEscape: true }],
		semi: ['error', 'always'],
		'max-len': ['warn', { code: 132, ignoreComments: true }],
		'no-console': 'warn',
		'no-else-return': ['error', { allowElseIf: false }],
		'no-extra-boolean-cast': 'error',
		'no-extra-bind': 'error',
		'no-implicit-coercion': 'error',
		'no-multi-spaces': 'warn',
		'no-redeclare': 'error',
		'no-self-assign': 'error',
		'no-undef-init': 'error',
		'prefer-template': 'warn',
		'sort-imports': 'off',
		'jsx-a11y/no-autofocus': 'off',
		'jsx-a11y/click-events-have-key-events': 0,
		'a11y-click-events-have-key-events': 0
	}
};
