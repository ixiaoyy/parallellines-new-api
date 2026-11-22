import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validatePaidRolesCredentialConfig } from './verify-tavern-paid-roles-config.mjs';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const EXAMPLE_FILE = path.join(REPO_ROOT, 'deploy', 'tavern-paid-roles.example.json');

test('validates deploy/tavern-paid-roles.example.json cleanly without leaking tokens', () => {
	const payload = JSON.parse(fs.readFileSync(EXAMPLE_FILE, 'utf8'));
	const summary = validatePaidRolesCredentialConfig(payload);
	assert.equal(summary.ok, true);
	assert.deepEqual(summary.enabled_roles, ['flux-the-cat', 'sakana']);
	assert.deepEqual(summary.disabled_roles, []);
	assert.equal(JSON.stringify(summary).includes('REPLACE_WITH'), false);
});

test('supports disabling a single role without affecting enabled roles', () => {
	const summary = validatePaidRolesCredentialConfig({
		roles: [
			{ role_id: 'flux-the-cat', bearer_token: 'f'.repeat(40), enabled: true },
			{ role_id: 'sakana', bearer_token: '', enabled: false },
			{ role_id: 'turtle-soup', bearer_token: 't'.repeat(40), enabled: true }
		]
	});
	assert.deepEqual(summary.enabled_roles, ['flux-the-cat', 'turtle-soup']);
	assert.deepEqual(summary.disabled_roles, ['sakana']);
});

test('rejects issuer token collision, duplicate tokens, and public catalog fields mixed into private credentials', () => {
	const issuer = 'i'.repeat(40);
	assert.throws(
		() =>
			validatePaidRolesCredentialConfig(
				{ roles: [{ role_id: 'flux-the-cat', bearer_token: issuer, enabled: true }] },
				{ issuerBearer: issuer }
			),
		/paid_roles_token_collides_with_issuer/
	);

	assert.throws(
		() =>
			validatePaidRolesCredentialConfig({
				roles: [
					{ role_id: 'flux-the-cat', bearer_token: 'a'.repeat(40), enabled: true },
					{ role_id: 'sakana', bearer_token: 'a'.repeat(40), enabled: true }
				]
			}),
		/paid_roles_duplicate_token/
	);

	assert.throws(
		() =>
			validatePaidRolesCredentialConfig({
				roles: [{ role_id: 'flux-the-cat', bearer_token: 'a'.repeat(40), enabled: true, profileDescription: 'nope' }]
			}),
		/paid_roles_unexpected_field:profileDescription/
	);
});
