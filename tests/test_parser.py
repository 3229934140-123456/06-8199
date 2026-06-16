"""
二进制解析引擎单元测试
运行方法: python -m pytest tests/test_parser.py -v
或: python tests/test_parser.py
"""

import struct
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binary_parser import (
    BinaryParser,
    UInt8, UInt16, UInt32, UInt64,
    Int8, Int16, Int32, Int64,
    Float32, Float64,
    String, Bytes, Padding,
    Array, Struct, Conditional,
    BitFlags, Enum,
    Endian, ParseError, InsufficientDataError, ValidationError,
    build_parser_from_schema, build_parser_from_file,
)


class TestNumericFields(unittest.TestCase):

    def test_uint8(self):
        parser = BinaryParser([UInt8("val")])
        data = b"\x42"
        result = parser.parse(data)
        self.assertEqual(result["val"], 0x42)
        self.assertEqual(result.consumed, 1)

    def test_uint16_little_endian(self):
        parser = BinaryParser([UInt16("val")], endian=Endian.LITTLE)
        data = b"\x34\x12"
        result = parser.parse(data)
        self.assertEqual(result["val"], 0x1234)

    def test_uint16_big_endian(self):
        parser = BinaryParser([UInt16("val")], endian=Endian.BIG)
        data = b"\x12\x34"
        result = parser.parse(data)
        self.assertEqual(result["val"], 0x1234)

    def test_uint32_little_endian(self):
        parser = BinaryParser([UInt32("val")], endian=Endian.LITTLE)
        data = b"\x78\x56\x34\x12"
        result = parser.parse(data)
        self.assertEqual(result["val"], 0x12345678)

    def test_uint64(self):
        parser = BinaryParser([UInt64("val")], endian=Endian.LITTLE)
        data = struct.pack("<Q", 0x0123456789ABCDEF)
        result = parser.parse(data)
        self.assertEqual(result["val"], 0x0123456789ABCDEF)

    def test_int8_negative(self):
        parser = BinaryParser([Int8("val")])
        data = b"\xFC"
        result = parser.parse(data)
        self.assertEqual(result["val"], -4)

    def test_int32_negative(self):
        parser = BinaryParser([Int32("val")], endian=Endian.LITTLE)
        data = struct.pack("<i", -12345)
        result = parser.parse(data)
        self.assertEqual(result["val"], -12345)

    def test_float32(self):
        parser = BinaryParser([Float32("val")], endian=Endian.LITTLE)
        data = struct.pack("<f", 3.14)
        result = parser.parse(data)
        self.assertAlmostEqual(result["val"], 3.14, places=5)

    def test_float64(self):
        parser = BinaryParser([Float64("val")], endian=Endian.LITTLE)
        data = struct.pack("<d", 2.718281828)
        result = parser.parse(data)
        self.assertAlmostEqual(result["val"], 2.718281828)

    def test_per_field_endian(self):
        parser = BinaryParser([
            UInt16("a", endian=Endian.LITTLE),
            UInt16("b", endian=Endian.BIG),
        ])
        data = b"\x34\x12\x12\x34"
        result = parser.parse(data)
        self.assertEqual(result["a"], 0x1234)
        self.assertEqual(result["b"], 0x1234)


class TestStringAndBytes(unittest.TestCase):

    def test_bytes_fixed(self):
        parser = BinaryParser([Bytes("data", length=4)])
        data = b"\x01\x02\x03\x04"
        result = parser.parse(data)
        self.assertEqual(result["data"], b"\x01\x02\x03\x04")

    def test_string_fixed_length(self):
        parser = BinaryParser([String("name", length=8)])
        data = b"Hello\x00\x00\x00"
        result = parser.parse(data)
        self.assertEqual(result["name"], "Hello\x00\x00\x00")

    def test_string_null_terminated(self):
        parser = BinaryParser([String("name", null_terminated=True)])
        data = b"World\x00extra"
        result = parser.parse(data)
        self.assertEqual(result["name"], "World")
        self.assertEqual(result.consumed, 6)

    def test_string_encoding(self):
        parser = BinaryParser([String("name", length=6, encoding="ascii")])
        data = b"abc123"
        result = parser.parse(data)
        self.assertEqual(result["name"], "abc123")

    def test_bytes_dynamic_length(self):
        parser = BinaryParser([
            UInt8("len"),
            Bytes("data", length="len"),
        ])
        data = b"\x05ABCDE"
        result = parser.parse(data)
        self.assertEqual(result["len"], 5)
        self.assertEqual(result["data"], b"ABCDE")

    def test_padding(self):
        parser = BinaryParser([
            UInt8("a"),
            Padding(3),
            UInt8("b"),
        ])
        data = b"\x01\x00\x00\x00\x02"
        result = parser.parse(data)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 2)
        self.assertEqual(result.consumed, 5)


class TestArray(unittest.TestCase):

    def test_fixed_count_array(self):
        parser = BinaryParser([
            Array("nums", element=UInt8(), count=4),
        ])
        data = b"\x01\x02\x03\x04"
        result = parser.parse(data)
        self.assertEqual(result["nums"], [1, 2, 3, 4])

    def test_dynamic_count_array(self):
        parser = BinaryParser([
            UInt8("count"),
            Array("items", element=UInt16(), count="count"),
        ], endian=Endian.LITTLE)
        data = b"\x03\x01\x00\x02\x00\x03\x00"
        result = parser.parse(data)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["items"], [1, 2, 3])

    def test_array_of_structs(self):
        point = Struct(fields=[
            Int32("x"),
            Int32("y"),
        ])
        parser = BinaryParser([
            UInt8("count"),
            Array("points", element=point, count="count"),
        ], endian=Endian.LITTLE)

        data = bytearray()
        data += b"\x02"
        data += struct.pack("<ii", 1, 2)
        data += struct.pack("<ii", 3, 4)

        result = parser.parse(bytes(data))
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["points"]), 2)
        self.assertEqual(result["points"][0]["x"], 1)
        self.assertEqual(result["points"][0]["y"], 2)
        self.assertEqual(result["points"][1]["x"], 3)
        self.assertEqual(result["points"][1]["y"], 4)


class TestConditional(unittest.TestCase):

    def test_conditional_present(self):
        parser = BinaryParser([
            UInt8("flag"),
            Conditional(
                "extra",
                condition=lambda ctx: ctx["flag"] == 1,
                field=UInt16("extra"),
            ),
        ], endian=Endian.LITTLE)

        data = b"\x01\x34\x12"
        result = parser.parse(data)
        self.assertEqual(result["flag"], 1)
        self.assertEqual(result["extra"], 0x1234)

    def test_conditional_absent(self):
        parser = BinaryParser([
            UInt8("flag"),
            Conditional(
                "extra",
                condition=lambda ctx: ctx["flag"] == 1,
                field=UInt16("extra"),
            ),
            UInt8("after"),
        ], endian=Endian.LITTLE)

        data = b"\x00\x99"
        result = parser.parse(data)
        self.assertEqual(result["flag"], 0)
        self.assertIsNone(result["extra"])
        self.assertEqual(result["after"], 0x99)

    def test_conditional_with_bit_flag(self):
        parser = BinaryParser([
            UInt16("flags"),
            Conditional(
                "checksum",
                condition=lambda ctx: (ctx["flags"] & 0x0002) != 0,
                field=UInt32("checksum"),
            ),
        ], endian=Endian.LITTLE)

        data = b"\x02\x00\x78\x56\x34\x12"
        result = parser.parse(data)
        self.assertEqual(result["flags"], 2)
        self.assertEqual(result["checksum"], 0x12345678)


class TestOffsetAndAlign(unittest.TestCase):

    def test_explicit_offset(self):
        parser = BinaryParser([
            UInt8("first"),
            UInt8("second", offset=10),
        ])

        data = b"\x01" + b"\x00" * 9 + b"\x02"
        result = parser.parse(data)
        self.assertEqual(result["first"], 1)
        self.assertEqual(result["second"], 2)

    def test_align(self):
        parser = BinaryParser([
            UInt8("a"),
            UInt32("b", align=4),
        ], endian=Endian.LITTLE)

        data = b"\x01\x00\x00\x00\x78\x56\x34\x12"
        result = parser.parse(data)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 0x12345678)
        self.assertEqual(result.consumed, 8)


class TestValidation(unittest.TestCase):

    def test_magic_validation(self):
        parser = BinaryParser([
            Bytes("magic", length=4, validator=b"ABCD"),
        ])

        with self.assertRaises(ValidationError):
            parser.parse(b"WXYZ")

    def test_value_validator(self):
        parser = BinaryParser([
            UInt8("val", validator=42),
        ])

        result = parser.parse(b"\x2a")
        self.assertEqual(result["val"], 42)

        with self.assertRaises(ValidationError):
            parser.parse(b"\x00")

    def test_callable_validator(self):
        parser = BinaryParser([
            UInt8("val", validator=lambda v: v < 100),
        ])

        result = parser.parse(b"\x32")
        self.assertEqual(result["val"], 50)

        with self.assertRaises(ValidationError):
            parser.parse(b"\x80")


class TestErrorReporting(unittest.TestCase):

    def test_insufficient_data_at_start(self):
        parser = BinaryParser([UInt32("val")], endian=Endian.LITTLE)

        with self.assertRaises(InsufficientDataError) as cm:
            parser.parse(b"\x01\x02")

        self.assertIsNotNone(cm.exception.offset)
        self.assertEqual(cm.exception.offset, 0)
        self.assertEqual(cm.exception.required, 4)
        self.assertEqual(cm.exception.available, 2)

    def test_insufficient_data_in_middle(self):
        parser = BinaryParser([
            UInt8("a"),
            UInt16("b"),
        ], endian=Endian.LITTLE)

        with self.assertRaises(InsufficientDataError) as cm:
            parser.parse(b"\x01\x02")

        self.assertEqual(cm.exception.offset, 1)
        self.assertEqual(cm.exception.field_name, "b")

    def test_field_name_in_error(self):
        parser = BinaryParser([
            UInt32("header_size"),
        ], endian=Endian.LITTLE)

        try:
            parser.parse(b"\x00")
        except ParseError as e:
            self.assertEqual(e.field_name, "header_size")
            self.assertIn("header_size", str(e))

    def test_array_index_in_error(self):
        parser = BinaryParser([
            UInt8("count"),
            Array("items", element=UInt16(), count="count"),
        ], endian=Endian.LITTLE)

        try:
            parser.parse(b"\x05\x01\x00\x02\x00")
            self.fail("should have raised")
        except ParseError as e:
            self.assertIn("items", str(e))


class TestStruct(unittest.TestCase):

    def test_named_struct(self):
        header = Struct("header", fields=[
            UInt16("width"),
            UInt16("height"),
        ])
        parser = BinaryParser([header], endian=Endian.LITTLE)

        data = struct.pack("<HH", 640, 480)
        result = parser.parse(data)
        self.assertEqual(result["header"]["width"], 640)
        self.assertEqual(result["header"]["height"], 480)

    def test_struct_with_reference(self):
        pass


class TestComplexScenarios(unittest.TestCase):

    def test_file_header_like_format(self):
        """模拟一个典型的文件头解析"""
        parser = BinaryParser([
            Bytes("magic", length=4, validator=b"TEST"),
            UInt16("version"),
            UInt32("file_size"),
            UInt16("flags"),
            UInt8("entry_count"),
            Padding(length=5),
        ], endian=Endian.LITTLE)

        data = struct.pack(
            "<4sHIHB5x",
            b"TEST", 1, 1024, 0x0001, 10
        )

        result = parser.parse(data)
        self.assertEqual(result["magic"], b"TEST")
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["file_size"], 1024)
        self.assertEqual(result["flags"], 1)
        self.assertEqual(result["entry_count"], 10)
        self.assertEqual(result.consumed, 18)

    def test_string_length_prefix(self):
        """长度前缀字符串"""
        parser = BinaryParser([
            String("name", length=UInt8("name_len")),
        ])

        data = b"\x05Hello"
        result = parser.parse(data)
        self.assertEqual(result["name_len"], 5)
        self.assertEqual(result["name"], "Hello")

    def test_length_dependent_array_in_struct(self):
        element = Struct(fields=[
            UInt16("id"),
            UInt8("type"),
        ])
        parser = BinaryParser([
            UInt8("num_items"),
            Array("items", element=element, count="num_items"),
        ], endian=Endian.LITTLE)

        data = bytearray()
        data += b"\x03"
        data += struct.pack("<HB", 100, 1)
        data += struct.pack("<HB", 200, 2)
        data += struct.pack("<HB", 300, 3)

        result = parser.parse(bytes(data))
        self.assertEqual(result["num_items"], 3)
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["items"][0]["id"], 100)
        self.assertEqual(result["items"][2]["type"], 3)


class TestContextReferences(unittest.TestCase):

    def test_nested_field_reference(self):
        """测试点分隔的字段引用"""
        parser = BinaryParser([
            Struct("header", fields=[
                UInt8("count"),
            ]),
            Array("data", element=UInt8(), count="header.count"),
        ])

        data = b"\x03\x0a\x0b\x0c"
        result = parser.parse(data)
        self.assertEqual(result["header"]["count"], 3)
        self.assertEqual(result["data"], [10, 11, 12])


class TestBitFlags(unittest.TestCase):

    def test_basic_bitflags(self):
        parser = BinaryParser([
            BitFlags("flags", type_=UInt8, bits={0: "read", 1: "write", 2: "execute"}),
        ])
        data = b"\x05"
        result = parser.parse(data)
        self.assertEqual(result["flags"]["value"], 5)
        self.assertTrue(result["flags"]["flags"]["read"])
        self.assertFalse(result["flags"]["flags"]["write"])
        self.assertTrue(result["flags"]["flags"]["execute"])

    def test_bitflags_uint16(self):
        parser = BinaryParser([
            BitFlags("ctrl", type_=UInt16, bits={0: "enabled", 3: "compressed", 7: "encrypted"}),
        ], endian=Endian.LITTLE)
        data = struct.pack("<H", 0x0089)
        result = parser.parse(data)
        self.assertEqual(result["ctrl"]["value"], 0x0089)
        self.assertTrue(result["ctrl"]["flags"]["enabled"])
        self.assertTrue(result["ctrl"]["flags"]["compressed"])
        self.assertTrue(result["ctrl"]["flags"]["encrypted"])

    def test_bitflags_all_clear(self):
        parser = BinaryParser([
            BitFlags("status", type_=UInt8, bits={0: "a", 1: "b"}),
        ])
        result = parser.parse(b"\x00")
        self.assertEqual(result["status"]["value"], 0)
        self.assertFalse(result["status"]["flags"]["a"])
        self.assertFalse(result["status"]["flags"]["b"])


class TestEnum(unittest.TestCase):

    def test_basic_enum(self):
        parser = BinaryParser([
            Enum("type", type_=UInt8, mapping={0: "none", 1: "file", 2: "dir"}),
        ])
        result = parser.parse(b"\x01")
        self.assertEqual(result["type"]["value"], 1)
        self.assertEqual(result["type"]["name"], "file")

    def test_enum_unknown_value(self):
        parser = BinaryParser([
            Enum("type", type_=UInt8, mapping={0: "none", 1: "file"}),
        ])
        result = parser.parse(b"\x99")
        self.assertEqual(result["type"]["value"], 0x99)
        self.assertIsNone(result["type"]["name"])

    def test_enum_uint16(self):
        parser = BinaryParser([
            Enum("machine", type_=UInt16, mapping={0x03: "EM_386", 0x3E: "EM_X86_64"}),
        ], endian=Endian.LITTLE)
        data = struct.pack("<H", 0x3E)
        result = parser.parse(data)
        self.assertEqual(result["machine"]["value"], 0x3E)
        self.assertEqual(result["machine"]["name"], "EM_X86_64")


class TestErrorImprovements(unittest.TestCase):

    def test_offset_beyond_file_size(self):
        parser = BinaryParser([
            UInt8("a", offset=100),
        ])
        data = b"\x01\x02\x03"
        try:
            parser.parse(data)
            self.fail("should have raised")
        except InsufficientDataError as e:
            self.assertIn("3 bytes", str(e))
            self.assertIn("beyond end of input", str(e))

    def test_negative_available_no_more(self):
        parser = BinaryParser([
            UInt8("a"),
            UInt32("b", offset=50),
        ])
        data = b"\x01\x02"
        try:
            parser.parse(data)
            self.fail("should have raised")
        except InsufficientDataError as e:
            self.assertNotIn("-1 available", str(e))


class TestSchemaLoader(unittest.TestCase):

    def test_basic_schema(self):
        schema = {
            "name": "TestFormat",
            "endian": "little",
            "fields": [
                {"name": "magic", "type": "bytes", "length": 4, "validator": "hex:41424344"},
                {"name": "version", "type": "uint16"},
                {"name": "count", "type": "uint32"},
            ],
        }
        parser = build_parser_from_schema(schema)
        data = b"ABCD" + struct.pack("<HI", 1, 42)
        result = parser.parse(data)
        self.assertEqual(result["magic"], b"ABCD")
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["count"], 42)

    def test_schema_with_array(self):
        schema = {
            "endian": "little",
            "fields": [
                {"name": "count", "type": "uint8"},
                {
                    "name": "items",
                    "type": "array",
                    "count": "count",
                    "element": {"type": "uint16"},
                },
            ],
        }
        parser = build_parser_from_schema(schema)
        data = b"\x03" + struct.pack("<HHH", 10, 20, 30)
        result = parser.parse(data)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["items"], [10, 20, 30])

    def test_schema_with_conditional(self):
        schema = {
            "endian": "little",
            "fields": [
                {"name": "flags", "type": "uint8"},
                {
                    "name": "extra",
                    "type": "conditional",
                    "condition": {"op": "eq", "field": "flags", "value": 1},
                    "field": {"name": "extra_val", "type": "uint16"},
                },
            ],
        }
        parser = build_parser_from_schema(schema)

        data_present = b"\x01" + struct.pack("<H", 0x1234)
        result = parser.parse(data_present)
        self.assertEqual(result["flags"], 1)
        self.assertIsNotNone(result["extra"])

        data_absent = b"\x00"
        result = parser.parse(data_absent)
        self.assertEqual(result["flags"], 0)
        self.assertIsNone(result["extra"])

    def test_schema_with_bitflags(self):
        schema = {
            "endian": "little",
            "fields": [
                {
                    "name": "perms",
                    "type": "bitflags",
                    "base_type": "uint8",
                    "bits": {"0": "read", "1": "write", "2": "exec"},
                },
            ],
        }
        parser = build_parser_from_schema(schema)
        result = parser.parse(b"\x05")
        self.assertEqual(result["perms"]["value"], 5)
        self.assertTrue(result["perms"]["flags"]["read"])
        self.assertTrue(result["perms"]["flags"]["exec"])
        self.assertFalse(result["perms"]["flags"]["write"])

    def test_schema_with_enum(self):
        schema = {
            "endian": "little",
            "fields": [
                {
                    "name": "file_type",
                    "type": "enum",
                    "base_type": "uint8",
                    "mapping": {"0": "regular", "1": "directory"},
                },
            ],
        }
        parser = build_parser_from_schema(schema)
        result = parser.parse(b"\x01")
        self.assertEqual(result["file_type"]["value"], 1)
        self.assertEqual(result["file_type"]["name"], "directory")

    def test_schema_with_struct(self):
        schema = {
            "endian": "little",
            "fields": [
                {
                    "name": "header",
                    "type": "struct",
                    "fields": [
                        {"name": "width", "type": "uint16"},
                        {"name": "height", "type": "uint16"},
                    ],
                },
            ],
        }
        parser = build_parser_from_schema(schema)
        data = struct.pack("<HH", 640, 480)
        result = parser.parse(data)
        self.assertEqual(result["header"]["width"], 640)
        self.assertEqual(result["header"]["height"], 480)

    def test_schema_with_string_null_terminated(self):
        schema = {
            "endian": "little",
            "fields": [
                {"name": "name", "type": "string", "null_terminated": True},
            ],
        }
        parser = build_parser_from_schema(schema)
        result = parser.parse(b"Hello\x00extra")
        self.assertEqual(result["name"], "Hello")

    def test_schema_with_string_fixed_length(self):
        schema = {
            "endian": "little",
            "fields": [
                {"name": "name", "type": "string", "length": 5},
            ],
        }
        parser = build_parser_from_schema(schema)
        result = parser.parse(b"Hello")
        self.assertEqual(result["name"], "Hello")

    def test_schema_with_padding(self):
        schema = {
            "endian": "little",
            "fields": [
                {"name": "a", "type": "uint8"},
                {"type": "padding", "length": 3},
                {"name": "b", "type": "uint8"},
            ],
        }
        parser = build_parser_from_schema(schema)
        result = parser.parse(b"\x01\x00\x00\x00\x02")
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 2)

    def test_schema_with_bit_set_condition(self):
        schema = {
            "endian": "little",
            "fields": [
                {"name": "flags", "type": "uint16"},
                {
                    "name": "checksum",
                    "type": "conditional",
                    "condition": {"op": "bit_set", "field": "flags", "bit": 0},
                    "field": {"name": "checksum", "type": "uint32"},
                },
            ],
        }
        parser = build_parser_from_schema(schema)
        data = b"\x01\x00" + struct.pack("<I", 0xDEAD)
        result = parser.parse(data)
        self.assertEqual(result["flags"], 1)
        self.assertEqual(result["checksum"], 0xDEAD)

    def test_schema_file_loading(self):
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "examples", "archive_schema.json",
        )
        if not os.path.exists(schema_path):
            self.skipTest("archive_schema.json not found")

        parser = build_parser_from_file(schema_path)
        self.assertIsNotNone(parser)


class TestToDict(unittest.TestCase):

    def test_to_dict_bytes_to_hex(self):
        parser = BinaryParser([
            Bytes("magic", length=4),
            UInt16("val"),
        ], endian=Endian.LITTLE)
        result = parser.parse(b"ABCD\x34\x12")
        d = result.to_dict()
        self.assertEqual(d["magic"], "41424344")
        self.assertEqual(d["val"], 0x1234)


if __name__ == "__main__":
    unittest.main(verbosity=2)
