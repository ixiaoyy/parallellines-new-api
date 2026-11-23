import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
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

test('v0.13.2-pkce.15 release recipe lock hashes match and introduces zero frontend UI patches', () => {
	const sha = (rel) => crypto.createHash('sha256').update(fs.readFileSync(path.join(REPO_ROOT, rel))).digest('hex');
	const lock = JSON.parse(
		fs.readFileSync(path.join(REPO_ROOT, 'releases', 'v0.13.2-pkce.15', 'upstream.lock.json'), 'utf8')
	);
	assert.equal(lock.application_version, 'v0.13.2-pkce.15');
	assert.equal(lock.base_application_version, 'v0.13.2-pkce.14');
	for (const key of ['base_release_lock', 'base_source_manifest', 'source_manifest', 'frontend_manifest']) {
		assert.equal(sha(lock[key]), lock[`${key}_sha256`], `hash mismatch for ${key}`);
	}
	assert.equal(lock.patches.length, 1);
	const patch = lock.patches[0];
	assert.equal(sha(patch.file), patch.sha256);
	const patchText = fs.readFileSync(path.join(REPO_ROOT, patch.file), 'utf8');
	assert.equal(patchText.includes('diff --git a/web/'), false);
	assert.match(patchText, /TAVERN_PAID_ROLES_FILE/);
	assert.match(patchText, /loadTavernRoleBearers/);
});
