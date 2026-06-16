"""
示例: 自定义二进制存档文件格式 (MyArchive)

文件结构:
- 文件头 (Header)
  - 魔数: 4字节 "MARC"
  - 版本: uint16
  - 标志位: uint16 (bit0=有扩展头, bit1=有校验和)
  - 文件数: uint32
  - 文件名表偏移: uint32 (相对于文件开始)
  - 数据区偏移: uint32
- [条件] 扩展头 (仅当标志位 bit0 置位时存在)
  - 创建时间: uint64 (unix 时间戳)
  - 作者名: 长度前缀字符串 (uint8 长度 + 字符)
- 文件条目数组 (数量 = 文件数字段)
  - 文件索引: uint32
  - 文件大小: uint32
  - 数据偏移: uint32
  - 标志: uint8
- 文件名表
  - 每个文件名: 以 null 结尾的字符串
- [条件] 校验和 (仅当标志位 bit1 置位时存在)
  - 校验和: uint32 (CRC32)
"""

from binary_parser import (
    BinaryParser,
    UInt8, UInt16, UInt32, UInt64,
    Int32,
    String, Bytes, Padding,
    Array, Struct, Conditional,
    Endian,
)


def build_archive_parser():
    header_fields = [
        Bytes("magic", length=4, validator=b"MARC"),
        UInt16("version"),
        UInt16("flags"),
        UInt32("file_count"),
        UInt32("name_table_offset"),
        UInt32("data_offset"),
    ]

    extended_header = Struct("extended_header", fields=[
        UInt64("created_at"),
        String("author", length=UInt8("name_len")),
    ])

    file_entry = Struct(fields=[
        UInt32("index"),
        UInt32("size"),
        UInt32("data_offset"),
        UInt8("flags"),
    ])

    full_parser_fields = [
        *header_fields,
        Conditional(
            "extended_header",
            condition=lambda ctx: (ctx["flags"] & 0x0001) != 0,
            field=extended_header,
        ),
        Array(
            "file_entries",
            element=file_entry,
            count="file_count",
        ),
        Conditional(
            "checksum",
            condition=lambda ctx: (ctx["flags"] & 0x0002) != 0,
            field=UInt32("checksum"),
        ),
    ]

    return BinaryParser(full_parser_fields, endian=Endian.LITTLE, name="MyArchive")


def build_simple_elf_parser():
    """
    简化版 ELF 文件头解析器 (64位, 小端)
    展示魔数验证、条件字段、枚举值等
    """
    elf_header = [
        Bytes("magic", length=4, validator=b"\x7fELF"),
        UInt8("ei_class"),
        UInt8("ei_data"),
        UInt8("ei_version"),
        UInt8("ei_osabi"),
        UInt8("ei_abiversion"),
        Padding(7),
        UInt16("e_type"),
        UInt16("e_machine"),
        UInt32("e_version"),

        Conditional(
            "e_entry_64",
            condition=lambda ctx: ctx["ei_class"] == 2,
            field=UInt64("e_entry"),
        ),
        Conditional(
            "e_entry_32",
            condition=lambda ctx: ctx["ei_class"] == 1,
            field=UInt32("e_entry"),
        ),

        Conditional(
            "e_phoff_64",
            condition=lambda ctx: ctx["ei_class"] == 2,
            field=UInt64("e_phoff"),
        ),
        Conditional(
            "e_phoff_32",
            condition=lambda ctx: ctx["ei_class"] == 1,
            field=UInt32("e_phoff"),
        ),

        Conditional(
            "e_shoff_64",
            condition=lambda ctx: ctx["ei_class"] == 2,
            field=UInt64("e_shoff"),
        ),
        Conditional(
            "e_shoff_32",
            condition=lambda ctx: ctx["ei_class"] == 1,
            field=UInt32("e_shoff"),
        ),

        UInt32("e_flags"),
        UInt16("e_ehsize"),
        UInt16("e_phentsize"),
        UInt16("e_phnum"),
        UInt16("e_shentsize"),
        UInt16("e_shnum"),
        UInt16("e_shstrndx"),
    ]

    return BinaryParser(elf_header, endian=Endian.LITTLE, name="ELF64 Header")


def build_packet_parser():
    """
    网络包解析示例: 展示变长数组和长度前缀
    """
    packet = [
        UInt16("packet_length"),
        UInt8("packet_type"),
        UInt16("sequence"),
        String("data", length=lambda ctx: ctx["packet_length"] - 5),
    ]
    return BinaryParser(packet, endian=Endian.BIG, name="NetworkPacket")


def build_nested_struct_parser():
    """
    嵌套结构体与对齐示例
    """
    point = Struct(fields=[
        Int32("x"),
        Int32("y"),
        Int32("z"),
    ])

    mesh_header = [
        UInt32("vertex_count"),
        UInt32("face_count"),
        Array("vertices", element=point, count="vertex_count", align=16),
    ]

    return BinaryParser(mesh_header, endian=Endian.LITTLE, name="MeshData")
