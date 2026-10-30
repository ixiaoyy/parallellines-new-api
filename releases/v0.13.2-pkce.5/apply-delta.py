"""Reconstruct exact pkce.5 from exact pkce.4; never operate a service."""
import base64
import gzip
import hashlib
import json
import pathlib
import sys

BASE_SHA = 'fa663b7e3d98265411589e0a36ea77a0f150b90becabd2f88249e89431afac3c'
TARGET_SHA = '5a22fd5868f675a24968dc43e8ee40e077f82d14cfb5e0f73fd8564b848b66fe'
ARCHIVE_SHA = '532df1fe19905be4f4ff3cc7e0da91711d91002075de881493ab5c331e51340f'
BASE_SIZE = 70639778
TARGET_SIZE = 70639778


def reconstruct(base, delta):
    if len(base) != BASE_SIZE or hashlib.sha256(base).hexdigest() != BASE_SHA:
        raise ValueError('base_sha_or_size_mismatch')
    if (delta.get('format') != 'pl-bytecopy-xor-v1' or delta.get('base_sha256') != BASE_SHA or
            delta.get('target_sha256') != TARGET_SHA or delta.get('base_size') != BASE_SIZE or
            delta.get('target_size') != TARGET_SIZE):
        raise ValueError('delta_contract_mismatch')
    ops = delta.get('ops')
    if not isinstance(ops, list) or len(ops) > 200000:
        raise ValueError('invalid_operations')
    output = bytearray()
    for op in ops:
        if not isinstance(op, list) or not op:
            raise ValueError('invalid_operation')
        if op[0] == 'c' and len(op) == 3:
            offset, length = op[1:]
            if type(offset) is not int or type(length) is not int or offset < 0 or length <= 0 or offset + length > len(base):
                raise ValueError('copy_bounds')
            if len(output) + length > TARGET_SIZE:
                raise ValueError('output_limit')
            output.extend(base[offset:offset + length])
        elif (op[0] == 'i' and len(op) == 2) or (op[0] == 'x' and len(op) == 3):
            encoded = op[-1]
            if not isinstance(encoded, str) or len(encoded) > 4 * ((TARGET_SIZE - len(output) + 2) // 3):
                raise ValueError('literal_limit')
            data = bytearray(base64.b64decode(encoded, validate=True))
            if not data or len(output) + len(data) > TARGET_SIZE:
                raise ValueError('literal_size')
            if op[0] == 'x':
                offset = op[1]
                if type(offset) is not int or offset < 0 or offset + len(data) > len(base):
                    raise ValueError('xor_bounds')
                for n in range(len(data)):
                    data[n] ^= base[offset + n]
            output.extend(data)
        else:
            raise ValueError('unknown_operation')
    if len(output) != TARGET_SIZE or hashlib.sha256(output).hexdigest() != TARGET_SHA:
        raise ValueError('target_sha_or_size_mismatch')
    return output


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Usage: python apply-delta.py BASE DELTA_GZIP NEW_OUTPUT')
    base_path, delta_path, out_path = map(pathlib.Path, sys.argv[1:])
    if out_path.exists() or out_path.is_symlink():
        raise SystemExit('Output already exists; inspect before retry')
    if hashlib.sha256(delta_path.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise SystemExit('Delta archive hash mismatch')
    with gzip.open(delta_path, 'rb') as stream:
        raw = stream.read(128 * 1024 * 1024 + 1)
    if len(raw) > 128 * 1024 * 1024:
        raise SystemExit('Delta document too large')
    result = reconstruct(base_path.read_bytes(), json.loads(raw))
    with out_path.open('xb') as target:
        target.write(result)
    print(json.dumps({'target_sha256': TARGET_SHA, 'bytes': len(result), 'base_verified': True, 'target_verified': True}))
