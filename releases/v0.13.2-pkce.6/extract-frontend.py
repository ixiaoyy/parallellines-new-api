"""从已授权的旧版 ELF 可执行文件恢复原有 Go embed 前端，按发布清单核对原字节。

仅生成构建输入，不执行旧二进制，不访问运行数据或修改前端代码。
"""
import hashlib
import json
from pathlib import Path
import struct
import sys


def extract(binary, manifest, destination):
    """输入 Linux amd64 Go 二进制、资产清单及输出目录；仅恢复清单中的原文件。"""
    data = binary.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01':
        raise RuntimeError('linux_amd64_elf_required')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    segments = [struct.unpack_from('<IIQQQQQQ', data, offset + i * size) for i in range(count)]
    segments = [p for p in segments if p[0] == 1]

    def address(position):
        for p in segments:
            if p[2] <= position < p[2] + p[5]:
                return p[3] + position - p[2]
        raise RuntimeError('embedded_name_outside_load_segment')

    def content(pointer, length):
        for p in segments:
            if p[3] <= pointer and pointer + length <= p[3] + p[5]:
                start = p[2] + pointer - p[3]
                return data[start:start + length]
        return b''

    all_entries = json.loads(manifest.read_text())['files']
    # 原版 go:embed web/dist 本来不嵌入点号或下划线开头的文件；不将其当成新增资产。
    entries = [entry for entry in all_entries
               if not any(part.startswith(('.', '_')) for part in Path(entry['file']).parts)]
    for entry in entries:
        name = ('web/dist/' + entry['file']).encode()
        matches = set()
        position = data.find(name)
        while position != -1:
            reference = struct.pack('<QQ', address(position), len(name))
            record = data.find(reference)
            while record != -1:
                pointer, length = struct.unpack_from('<QQ', data, record + 16)
                if length == entry['bytes']:
                    value = content(pointer, length)
                    if hashlib.sha256(value).hexdigest() == entry['sha256']:
                        matches.add(value)
                record = data.find(reference, record + 1)
            position = data.find(name, position + 1)
        if len(matches) != 1:
            raise RuntimeError('embedded_asset_missing_or_changed:' + entry['file'])
        path = destination / entry['file']
        if not path.resolve().is_relative_to(destination.resolve()):
            raise RuntimeError('invalid_asset_path')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(matches.pop())
    print(json.dumps({'frontend_files_restored': len(entries), 'frontend_modified': False,
                      'original_go_embed_excluded': len(all_entries) - len(entries)}))


if __name__ == '__main__':
    extract(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
