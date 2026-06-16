"""
一条命令的完整 demo: 生成测试二进制文件 + 从 JSON schema 解析 + inspect 模式

使用方法:
    python examples/run_json_demo.py

这个脚本演示了:
1. 声明式 JSON/YAML schema 描述二进制格式
2. 公共类型文件 ($ref) 拆分复用 (枚举、结构体、位标志)
3. 表达式求值 (vertex_count + 1, flags.value & 2)
4. inspect 模式输出详细字段表
"""

import struct
import sys
import os
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binary_parser import build_parser_from_file


SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "archive_with_refs_schema.json",
)


def build_test_binary():
    buf = bytearray()

    buf += b"MARC"
    buf += struct.pack("<H", 1)

    flags = 0b0000_0000_0000_0011  # compressed + encrypted
    buf += struct.pack("<H", flags)

    vertex_count = 2
    buf += struct.pack("<I", vertex_count)

    name_table = b"file1.txt\x00file2.dat\x00"
    name_table_size = len(name_table) + 1  # expression uses size - 1
    buf += struct.pack("<I", name_table_size)

    # vertices: count = vertex_count + 1 = 3 (expression demo)
    vertices = [
        (0, 0, 0),
        (1, 0, 0),
        (0, 1, 0),
    ]
    for x, y, z in vertices:
        buf += struct.pack("<iii", x, y, z)

    # name table (will consume name_table_size - 1 bytes via expression)
    buf += name_table + b"\x00"

    # file entries
    entries = [
        (0, 1024, 0),
        (1, 2048, 1),
    ]
    for idx, size, ftype in entries:
        buf += struct.pack("<IIB", idx, size, ftype)
        while (len(buf) - 0) % 4 != 0:
            buf += b"\x00"

    # checksum: conditional on (flags.value & 2) being true
    buf += struct.pack("<I", 0xCAFEBABE)

    return bytes(buf)


def main():
    print("=" * 72)
    print("  Binary Parser JSON Schema Demo (with $ref + expressions + inspect)")
    print("=" * 72)

    binary_data = build_test_binary()
    print(f"\nGenerated test binary: {len(binary_data)} bytes")
    print(f"Schema file: {SCHEMA_PATH}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp.write(binary_data)
        tmp_path = tmp.name

    try:
        print("\n" + "-" * 72)
        print("  Loading schema (with $ref cross-file references)...")
        print("-" * 72)
        parser = build_parser_from_file(SCHEMA_PATH)
        print("OK")

        print("\n" + "-" * 72)
        print("  Parsing binary data (with expressions like 'vertex_count + 1')...")
        print("-" * 72)
        result = parser.parse(binary_data, inspect=True)
        print(f"OK - consumed {result.consumed} bytes")

        print("\n" + "-" * 72)
        print("  Inspect Table (each field's offset, hex, and interpreted value)")
        print("-" * 72)
        from binparse import format_inspect_table
        print(format_inspect_table(result))

        print("\n" + "-" * 72)
        print("  Parsed JSON Output")
        print("-" * 72)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

        print("\n" + "-" * 72)
        print("  Example Expression Evaluations")
        print("-" * 72)
        print(f"    Array count expression 'vertex_count + 1': "
              f"{result['vertex_count']} + 1 = {len(result['vertices'])}")
        print(f"    String length expression 'name_table_size - 1': "
              f"{result['name_table_size']} - 1 = {len(result['name_table'])}")
        print(f"    Condition expression 'flags.value & 2': "
              f"{result['flags']['value']} & 2 = {result['flags']['value'] & 2} "
              f"(checksum {'present' if result.get('checksum') is not None else 'absent'})")

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    print("\n" + "=" * 72)
    print("  Demo complete.")
    print("=" * 72)


if __name__ == "__main__":
    main()
