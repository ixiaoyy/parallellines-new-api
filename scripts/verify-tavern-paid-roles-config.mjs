// 校验 New API 侧 TAVERN_PAID_ROLES_FILE 私有角色凭据配置（与 pkce.15 Go 契约一致）。
// 仅输出脱敏角色汇总，绝不打印任何 bearer_token 原文。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROLE_ID_RE = /^[a-z0-9][a-z0-9-]{0,31}$/;
export const PRINTABLE_ASCII_RE = /^[\x21-\x7e]{32,256}$/;

export function validatePaidRolesCredentialConfig(payload, { issuerBearer = '' } = {}) {
	if (!payload || typeof payload !== 'object' || !Array.isArray(payload.roles) || payload.roles.length === 0) {
		throw new Error('paid_roles_config_empty_or_invalid');
	}
	const seenIds = new Set();
	const seenTokens = new Set();
	const enabledRoles = [];
	const disabledRoles = [];

	for (const entry of payload.roles) {
		if (!entry || typeof entry !== 'object') throw new Error('paid_roles_entry_invalid');
		const allowedKeys = new Set(['role_id', 'bearer_token', 'enabled']);
		for (const key of Object.keys(entry)) {
			if (!allowedKeys.has(key)) {
				throw new Error(`paid_roles_unexpected_field:${key}`);
			}
		}
		const { role_id: roleId, bearer_token: token, enabled = true } = entry;
		if (typeof roleId !== 'string' || !ROLE_ID_RE.test(roleId)) {
			throw new Error(`paid_roles_invalid_id:${String(roleId)}`);
		}
		if (seenIds.has(roleId)) throw new Error(`paid_roles_duplicate_id:${roleId}`);
		if (typeof enabled !== 'boolean') throw new Error(`paid_roles_invalid_enabled:${roleId}`);
		seenIds.add(roleId);

		if (!enabled) {
			disabledRoles.push(roleId);
			continue;
		}
		if (typeof token !== 'string' || !PRINTABLE_ASCII_RE.test(token)) {
			throw new Error(`paid_roles_invalid_token:${roleId}`);
		}
		if (issuerBearer && token === issuerBearer) {
			throw new Error(`paid_roles_token_collides_with_issuer:${roleId}`);
		}
		if (seenTokens.has(token)) {
			throw new Error(`paid_roles_duplicate_token:${roleId}`);
		}
		seenTokens.add(token);
		enabledRoles.push(roleId);
	}

	return {
		ok: true,
		enabled_roles: enabledRoles.sort(),
		disabled_roles: disabledRoles.sort()
	};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const file = process.argv[2];
	if (!file) throw new Error('usage: node scripts/verify-tavern-paid-roles-config.mjs <private-roles.json>');
	const payload = JSON.parse(fs.readFileSync(path.resolve(file), 'utf8'));
	const summary = validatePaidRolesCredentialConfig(payload, {
		issuerBearer: process.env.TAVERN_FLUX_ISSUER_BEARER || ''
	});
	console.log(JSON.stringify(summary));
}
