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

    # magic: 4 bytes
    magic = b"MARC"
    buf += magic

    # version: uint16
    version = 1
    buf += struct.pack("<H", version)

    # flags: uint16 bitflags (compressed=bit0, encrypted=bit1)
    flags_value = 0b0000_0000_0000_0011  # compressed + encrypted (value 3)
    buf += struct.pack("<H", flags_value)

    # vertex_count: uint32
    vertex_count = 2
    buf += struct.pack("<I", vertex_count)

    # name_table: string length expression = name_table_size - 1
    # so set name_table_size = actual_string_length + 1
    name_table_string = "file1.txt\x00file2.dat\x00"  # 20 chars
    name_table_size = len(name_table_string) + 1  # 21
    buf += struct.pack("<I", name_table_size)

    # vertices: array count = vertex_count + 1 = 3 (via expression)
    # each point = int32 x + int32 y + int32 z
    vertices = [
        (0, 0, 0),
        (1, 0, 0),
        (0, 1, 0),
    ]
    for x, y, z in vertices:
        buf += struct.pack("<iii", x, y, z)

    # name_table bytes (exactly name_table_size - 1 = 20 bytes, matches expression)
    buf += name_table_string.encode("utf-8")

    # file_entries: count=2, each = uint32 index + uint32 size + uint8(enum) type
    # NO padding per schema definition (each entry is 9 bytes)
    entries = [
        # (index, size, type_value)
        (100, 262144, 0),   # 0 = regular
        (200, 524288, 1),   # 1 = directory
    ]
    for idx, size, ftype in entries:
        buf += struct.pack("<IIB", idx, size, ftype)

    # checksum: conditional present because flags.value & 2 != 0
    checksum_value = 0xDEADBEEF
    buf += struct.pack("<I", checksum_value)

    return bytes(buf), {
        "magic_hex": magic.hex(),
        "version": version,
        "flags_value": flags_value,
        "vertex_count": vertex_count,
        "name_table_size": name_table_size,
        "vertices": vertices,
        "name_table": name_table_string,
        "entries": entries,
        "checksum": checksum_value,
    }


def _assert_equal(path, expected, actual):
    if expected != actual:
        raise AssertionError(
            f"Data mismatch at {path}: expected {expected!r}, got {actual!r}"
        )
    print(f"    [OK] {path} = {expected!r}")


def main():
    print("=" * 72)
    print("  Binary Parser JSON Schema Demo (with $ref + expressions + inspect)")
    print("=" * 72)

    binary_data, expected = build_test_binary()
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
        print("  Validating parsed values match constructed data...")
        print("-" * 72)
        _assert_equal("magic (bytes)", b"MARC", result["magic"])
        _assert_equal("magic (hex in to_dict)", expected["magic_hex"], result.to_dict()["magic"])
        _assert_equal("version", expected["version"], result["version"])
        _assert_equal("flags.value", expected["flags_value"], result["flags"]["value"])
        _assert_equal("flags.flags.compressed", True, result["flags"]["flags"]["compressed"])
        _assert_equal("flags.flags.encrypted",  True, result["flags"]["flags"]["encrypted"])
        _assert_equal("vertex_count", expected["vertex_count"], result["vertex_count"])
        _assert_equal("name_table_size", expected["name_table_size"], result["name_table_size"])
        _assert_equal("len(vertices) (= vertex_count+1 via expr)",
                      len(expected["vertices"]), len(result["vertices"]))
        for i, (exp, got) in enumerate(zip(expected["vertices"], result["vertices"])):
            _assert_equal(f"vertices[{i}].x", exp[0], got["x"])
            _assert_equal(f"vertices[{i}].y", exp[1], got["y"])
            _assert_equal(f"vertices[{i}].z", exp[2], got["z"])
        _assert_equal("name_table", expected["name_table"], result["name_table"])
        _assert_equal("len(file_entries)", len(expected["entries"]), len(result["file_entries"]))
        for i, ((exp_idx, exp_size, exp_type), got_e) in enumerate(
                zip(expected["entries"], result["file_entries"])):
            _assert_equal(f"file_entries[{i}].index", exp_idx, got_e["index"])
            _assert_equal(f"file_entries[{i}].size",  exp_size,  got_e["size"])
            _assert_equal(f"file_entries[{i}].entry_type.value", exp_type, got_e["entry_type"]["value"])
            expected_name = {0: "regular", 1: "directory", 2: "symlink"}.get(exp_type)
            _assert_equal(f"file_entries[{i}].entry_type.name",  expected_name, got_e["entry_type"]["name"])
        _assert_equal("checksum (= 0x{:X})".format(expected["checksum"]),
                      expected["checksum"], result["checksum"])
        print("    [OK] All values match constructed data.")

        print("\n" + "-" * 72)
        print("  Inspect Table (each field's offset, hex, and interpreted value)")
        print("-" * 72)
        from binparse import format_inspect_table
        print(format_inspect_table(result.field_info, result.consumed))

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
