"""
示例: 二进制解析引擎使用演示

运行方法: python examples/demo.py
"""

import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binary_parser import (
    BinaryParser, ParseError,
    UInt8, UInt16, UInt32, UInt64, Int32,
    Float32, Float64,
    String, Bytes, Padding,
    Array, Struct, Conditional,
    Endian,
)
from examples.archive_format import (
    build_archive_parser,
    build_simple_elf_parser,
    build_packet_parser,
    build_nested_struct_parser,
)


def make_test_archive():
    """构造一个测试用的二进制存档文件"""
    buf = bytearray()

    flags = 0x0003

    buf += b"MARC"
    buf += struct.pack("<H", 1)
    buf += struct.pack("<H", flags)
    buf += struct.pack("<I", 3)
    buf += struct.pack("<I", 0)
    buf += struct.pack("<I", 0)

    buf += struct.pack("<Q", 1700000000)
    author = b"Alice"
    buf += struct.pack("B", len(author))
    buf += author

    file_entries = [
        (0, 1024, 0x1000, 0),
        (1, 2048, 0x2000, 1),
        (2, 512,  0x3000, 0),
    ]
    for idx, size, data_off, fl in file_entries:
        buf += struct.pack("<IIIB", idx, size, data_off, fl)

    checksum = 0xDEADBEEF
    buf += struct.pack("<I", checksum)

    return bytes(buf)


def make_test_elf_header():
    """构造一个测试用的 ELF64 文件头"""
    buf = bytearray()
    buf += b"\x7fELF"
    buf += struct.pack("B", 2)
    buf += struct.pack("B", 1)
    buf += struct.pack("B", 1)
    buf += struct.pack("B", 0)
    buf += struct.pack("B", 0)
    buf += b"\x00" * 7
    buf += struct.pack("<H", 2)
    buf += struct.pack("<H", 0x3E)
    buf += struct.pack("<I", 1)
    buf += struct.pack("<Q", 0x401000)
    buf += struct.pack("<Q", 64)
    buf += struct.pack("<Q", 0x1000)
    buf += struct.pack("<I", 0)
    buf += struct.pack("<H", 64)
    buf += struct.pack("<H", 56)
    buf += struct.pack("<H", 9)
    buf += struct.pack("<H", 64)
    buf += struct.pack("<H", 30)
    buf += struct.pack("<H", 27)
    return bytes(buf)


def make_test_packet():
    """构造一个测试网络包"""
    data = b"Hello, Packet!"
    length = 5 + len(data)
    buf = struct.pack(">H B H", length, 0x01, 42)
    buf += data
    return buf


def make_test_mesh():
    """构造一个测试网格数据"""
    buf = bytearray()
    buf += struct.pack("<I", 4)
    buf += struct.pack("<I", 2)
    while len(buf) % 16 != 0:
        buf += b"\x00"

    vertices = [
        (0, 0, 0),
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, 1),
    ]
    for x, y, z in vertices:
        buf += struct.pack("<iii", x, y, z)

    return bytes(buf)


def demo_archive():
    print("=" * 60)
    print("示例 1: 自定义二进制存档格式解析")
    print("=" * 60)

    parser = build_archive_parser()
    data = make_test_archive()

    print(f"输入数据大小: {len(data)} 字节")
    print(f"魔数: {data[:4]}")

    try:
        result = parser.parse(data)
        print("\n解析结果:")
        for key in result.fields_order:
            value = result[key]
            if key == "magic":
                print(f"  {key}: {value!r}")
            elif key == "flags":
                print(f"  {key}: 0x{value:04x} (bit0={bool(value&1)}, bit1={bool(value&2)})")
            elif key == "extended_header":
                print(f"  {key}:")
                print(f"    created_at: {value['created_at']}")
                print(f"    author: {value['author']}")
            elif key == "file_entries":
                print(f"  {key}: (共 {len(value)} 个)")
                for i, entry in enumerate(value):
                    print(f"    [{i}]: index={entry['index']}, size={entry['size']}, "
                          f"offset=0x{entry['data_offset']:x}, flags={entry['flags']}")
            else:
                print(f"  {key}: {value}")

        print(f"\n消耗字节数: {result.consumed}")
        print(f"剩余字节数: {len(result.remaining)}")

    except ParseError as e:
        print(f"解析错误: {e}")


def demo_elf():
    print("\n" + "=" * 60)
    print("示例 2: ELF 文件头解析 (条件字段)")
    print("=" * 60)

    parser = build_simple_elf_parser()
    data = make_test_elf_header()

    print(f"输入数据大小: {len(data)} 字节")
    print(f"魔数: {data[:4]}")

    try:
        result = parser.parse(data)
        print("\n解析结果:")
        ei_class = result["ei_class"]
        print(f"  ei_class: {ei_class} ({'64位' if ei_class == 2 else '32位'})")
        print(f"  ei_data: {result['ei_data']} ({'小端' if result['ei_data'] == 1 else '大端'})")
        print(f"  e_type: {result['e_type']}")
        print(f"  e_machine: 0x{result['e_machine']:x}")

        if "e_entry_64" in result.data and result.data["e_entry_64"] is not None:
            print(f"  e_entry: 0x{result.data['e_entry_64']:016x} (64位)")
        elif "e_entry_32" in result.data and result.data["e_entry_32"] is not None:
            print(f"  e_entry: 0x{result.data['e_entry_32']:08x} (32位)")

        print(f"  e_phnum: {result['e_phnum']}")
        print(f"  e_shnum: {result['e_shnum']}")

    except ParseError as e:
        print(f"解析错误: {e}")


def demo_packet():
    print("\n" + "=" * 60)
    print("示例 3: 变长网络包解析 (长度依赖)")
    print("=" * 60)

    parser = build_packet_parser()
    data = make_test_packet()

    print(f"输入数据大小: {len(data)} 字节")

    try:
        result = parser.parse(data)
        print("\n解析结果:")
        print(f"  packet_length: {result['packet_length']}")
        print(f"  packet_type: 0x{result['packet_type']:02x}")
        print(f"  sequence: {result['sequence']}")
        print(f"  data: {result['data']!r}")

    except ParseError as e:
        print(f"解析错误: {e}")


def demo_mesh():
    print("\n" + "=" * 60)
    print("示例 4: 嵌套结构体与对齐")
    print("=" * 60)

    parser = build_nested_struct_parser()
    data = make_test_mesh()

    print(f"输入数据大小: {len(data)} 字节")

    try:
        result = parser.parse(data)
        print("\n解析结果:")
        print(f"  vertex_count: {result['vertex_count']}")
        print(f"  face_count: {result['face_count']}")
        print(f"  vertices:")
        for i, v in enumerate(result["vertices"]):
            print(f"    [{i}]: ({v['x']}, {v['y']}, {v['z']})")

        print(f"\n消耗字节数: {result.consumed}")

    except ParseError as e:
        print(f"解析错误: {e}")


def demo_error():
    print("\n" + "=" * 60)
    print("示例 5: 错误报告 (数据不足)")
    print("=" * 60)

    parser = BinaryParser([
        UInt32("a"),
        UInt32("b"),
        UInt32("c"),
    ], endian=Endian.LITTLE)

    data = b"\x01\x02\x03"

    try:
        parser.parse(data)
    except ParseError as e:
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        print(f"  offset: 0x{e.offset:08x} ({e.offset})")
        print(f"  field: {e.field_name}")

    print("\n--- 验证失败示例 ---")
    parser2 = BinaryParser([
        Bytes("magic", length=4, validator=b"ABCD"),
    ])

    try:
        parser2.parse(b"WXYZ1234")
    except ParseError as e:
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")


def demo_declarative_definition():
    print("\n" + "=" * 60)
    print("示例 6: 声明式 DSL 完整演示")
    print("=" * 60)

    format_def = [
        Bytes("signature", length=4, validator=b"FORM"),
        UInt32("total_size"),
        UInt16("version", endian=Endian.BIG),
        UInt8("type_code"),
        Padding(length=3),
        String("name", length=16),
        UInt32("item_count"),
        Array(
            "items",
            element=Struct(fields=[
                UInt32("id"),
                Float64("value"),
            ]),
            count="item_count",
        ),
        Conditional(
            "footer",
            condition=lambda ctx: ctx["type_code"] == 0x01,
            field=Struct(fields=[
                UInt32("crc32"),
                String("comment", null_terminated=True),
            ]),
        ),
    ]

    parser = BinaryParser(format_def, endian=Endian.LITTLE, name="CustomFormat")

    data = bytearray()
    data += b"FORM"
    data += struct.pack("<I", 0)
    data += struct.pack(">H", 0x0100)
    data += struct.pack("B", 0x01)
    data += b"\x00\x00\x00"
    data += b"TestObject\x00\x00\x00\x00\x00\x00"
    data += struct.pack("<I", 2)
    data += struct.pack("<Id", 1, 3.14)
    data += struct.pack("<Id", 2, 2.718)
    data += struct.pack("<I", 0x12345678)
    data += b"This is a comment\x00"

    struct.pack_into("<I", data, 4, len(data))

    try:
        result = parser.parse(bytes(data))
        print("解析成功!")
        print(f"  signature: {result['signature']}")
        print(f"  total_size: {result['total_size']}")
        print(f"  version: 0x{result['version']:04x}")
        print(f"  type_code: 0x{result['type_code']:02x}")
        print(f"  name: '{result['name']}'")
        print(f"  item_count: {result['item_count']}")
        for i, item in enumerate(result["items"]):
            print(f"  items[{i}]: id={item['id']}, value={item['value']}")
        if result.get("footer"):
            print(f"  footer.crc32: 0x{result['footer']['crc32']:08x}")
            print(f"  footer.comment: '{result['footer']['comment']}'")
    except ParseError as e:
        print(f"解析错误: {e}")


if __name__ == "__main__":
    demo_archive()
    demo_elf()
    demo_packet()
    demo_mesh()
    demo_error()
    demo_declarative_definition()
    print("\n" + "=" * 60)
    print("所有示例运行完毕!")
    print("=" * 60)
