import json
import os
from .fields import (
    Field, UInt8, UInt16, UInt32, UInt64,
    Int8, Int16, Int32, Int64,
    Float32, Float64,
    String, Bytes, Padding,
    Array, Struct, Conditional,
    BitFlags, Enum,
    Endian,
)
from .engine import BinaryParser
from .errors import ParseError
from .expression import eval_expression, is_expression_string
from .schema_loader import load_schema, resolve_refs


_TYPE_MAP = {
    "uint8": UInt8, "u8": UInt8,
    "uint16": UInt16, "u16": UInt16,
    "uint32": UInt32, "u32": UInt32,
    "uint64": UInt64, "u64": UInt64,
    "int8": Int8, "i8": Int8,
    "int16": Int16, "i16": Int16,
    "int32": Int32, "i32": Int32,
    "int64": Int64, "i64": Int64,
    "float32": Float32, "f32": Float32,
    "float64": Float64, "f64": Float64,
    "string": String,
    "bytes": Bytes,
    "padding": Padding,
    "struct": Struct,
    "array": Array,
    "conditional": Conditional,
    "bitflags": BitFlags,
    "enum": Enum,
}

_ENDIAN_MAP = {
    "little": Endian.LITTLE,
    "big": Endian.BIG,
    "native": Endian.NATIVE,
    "network": Endian.NETWORK,
    "<": Endian.LITTLE,
    ">": Endian.BIG,
    "=": Endian.NATIVE,
}


def _parse_endian(value):
    if value is None:
        return None
    key = value.lower() if isinstance(value, str) else value
    if key in _ENDIAN_MAP:
        return _ENDIAN_MAP[key]
    raise ValueError(f"unknown endian: {value!r}")


def _build_condition(condition_spec):
    if condition_spec is None:
        return None

    if isinstance(condition_spec, str):
        expr = condition_spec
        def cond(ctx, _expr=expr):
            return bool(eval_expression(_expr, ctx))
        return cond

    if isinstance(condition_spec, dict):
        op = condition_spec.get("op", condition_spec.get("operator"))
        field_ref = condition_spec.get("field")
        value = condition_spec.get("value")

        if op == "bit_set":
            bit = condition_spec.get("bit", 0)
            def cond(ctx, _ref=field_ref, _bit=bit):
                from .fields import _resolve_ref
                val = _resolve_ref(_ref, ctx)
                return bool(val & (1 << _bit))
            return cond

        if op == "eq" or op == "==":
            def cond(ctx, _ref=field_ref, _val=value):
                from .fields import _resolve_ref
                return _resolve_ref(_ref, ctx) == _val
            return cond

        if op == "ne" or op == "!=":
            def cond(ctx, _ref=field_ref, _val=value):
                from .fields import _resolve_ref
                return _resolve_ref(_ref, ctx) != _val
            return cond

        if op == "gt" or op == ">":
            def cond(ctx, _ref=field_ref, _val=value):
                from .fields import _resolve_ref
                return _resolve_ref(_ref, ctx) > _val
            return cond

        if op == "lt" or op == "<":
            def cond(ctx, _ref=field_ref, _val=value):
                from .fields import _resolve_ref
                return _resolve_ref(_ref, ctx) < _val
            return cond

    raise ValueError(f"unsupported condition spec: {condition_spec!r}")


def _build_validator(validator_spec):
    if validator_spec is None:
        return None
    if isinstance(validator_spec, (bytes, bytearray)):
        return validator_spec
    if isinstance(validator_spec, int):
        return validator_spec
    if isinstance(validator_spec, str):
        if validator_spec.startswith("hex:"):
            return bytes.fromhex(validator_spec[4:])
        if validator_spec.startswith("0x"):
            return bytes.fromhex(validator_spec[2:])
        return validator_spec.encode("utf-8")
    raise ValueError(f"unsupported validator spec: {validator_spec!r}")


def _build_length_expr(length_spec):
    if length_spec is None:
        return None
    if isinstance(length_spec, int):
        return length_spec
    if isinstance(length_spec, str):
        if length_spec.startswith("$"):
            return length_spec[1:]
        return length_spec
    if isinstance(length_spec, dict):
        if length_spec.get("type"):
            type_name = length_spec["type"].lower()
            if type_name in _TYPE_MAP:
                cls = _TYPE_MAP[type_name]
                kwargs = {}
                if "name" in length_spec:
                    kwargs["name"] = length_spec["name"]
                return cls(**kwargs)
        if length_spec.get("field"):
            ref = length_spec["field"]
            if ref.startswith("$"):
                return ref[1:]
            return ref
        if length_spec.get("expr"):
            expr = length_spec["expr"]
            def _expr_length(ctx, _expr=expr):
                return int(eval_expression(_expr, ctx))
            return _expr_length
    raise ValueError(f"unsupported length spec: {length_spec!r}")


def _resolve_count_spec(count_spec):
    if count_spec is None:
        return None
    if isinstance(count_spec, int):
        return count_spec
    if isinstance(count_spec, str):
        stripped = count_spec.lstrip("$")
        return stripped
    if isinstance(count_spec, dict):
        if count_spec.get("expr"):
            expr = count_spec["expr"]
            def _expr_count(ctx, _expr=expr):
                return int(eval_expression(_expr, ctx))
            return _expr_count
        if count_spec.get("field"):
            ref = count_spec["field"]
            if ref.startswith("$"):
                return ref[1:]
            return ref
    raise ValueError(f"unsupported count spec: {count_spec!r}")


def _build_field(spec):
    if not isinstance(spec, dict):
        raise ValueError(f"field spec must be a dict, got {type(spec).__name__}")

    type_name = spec.get("type", "").lower()
    if type_name not in _TYPE_MAP:
        raise ValueError(f"unknown field type: {spec.get('type')!r}")

    name = spec.get("name")
    endian = _parse_endian(spec.get("endian"))
    offset = spec.get("offset")
    align = spec.get("align")
    validator = _build_validator(spec.get("validator"))

    common_kw = {}
    if endian is not None:
        common_kw["endian"] = endian
    if offset is not None:
        common_kw["offset"] = offset
    if align is not None:
        common_kw["align"] = align
    if validator is not None:
        common_kw["validator"] = validator

    cls = _TYPE_MAP[type_name]

    if cls in (UInt8, Int8, UInt16, Int16, UInt32, Int32, UInt64, Int64, Float32, Float64):
        return cls(name, **common_kw)

    if cls is String:
        kw = dict(common_kw)
        length = _build_length_expr(spec.get("length"))
        if length is not None:
            kw["length"] = length
        if spec.get("null_terminated"):
            kw["null_terminated"] = True
        if "encoding" in spec:
            kw["encoding"] = spec["encoding"]
        return String(name, **kw)

    if cls is Bytes:
        kw = dict(common_kw)
        length = _build_length_expr(spec.get("length"))
        if length is not None:
            kw["length"] = length
        return Bytes(name, **kw)

    if cls is Padding:
        kw = dict(common_kw)
        length = _build_length_expr(spec.get("length"))
        if length is not None:
            kw["length"] = length
        if "pattern" in spec:
            p = spec["pattern"]
            if isinstance(p, str):
                kw["pattern"] = bytes.fromhex(p) if p.startswith("0x") or len(p) % 2 == 0 else p.encode()
            elif isinstance(p, int):
                kw["pattern"] = bytes([p])
        return Padding(**kw)

    if cls is Array:
        kw = dict(common_kw)
        element_spec = spec.get("element")
        if element_spec is None:
            raise ValueError(f"array '{name}' requires 'element'")
        element = _build_field(element_spec)
        kw["element"] = element
        count = _resolve_count_spec(spec.get("count"))
        if count is not None:
            kw["count"] = count
        return Array(name, **kw)

    if cls is Struct:
        kw = dict(common_kw)
        fields_spec = spec.get("fields", [])
        fields = [_build_field(f) for f in fields_spec]
        kw["fields"] = fields
        return Struct(name, **kw)

    if cls is Conditional:
        kw = dict(common_kw)
        cond_spec = spec.get("condition")
        if cond_spec is None:
            raise ValueError(f"conditional '{name}' requires 'condition'")
        kw["condition"] = _build_condition(cond_spec)
        field_spec = spec.get("field")
        if field_spec is None:
            raise ValueError(f"conditional '{name}' requires 'field'")
        kw["field"] = _build_field(field_spec)
        return Conditional(name, **kw)

    if cls is BitFlags:
        kw = dict(common_kw)
        bits = spec.get("bits", {})
        parsed_bits = {}
        for k, v in bits.items():
            parsed_bits[int(k)] = v
        kw["bits"] = parsed_bits
        base_type = spec.get("base_type", spec.get("size"))
        if base_type is not None:
            type_lower = base_type.lower()
            if type_lower in _TYPE_MAP:
                kw["type_"] = _TYPE_MAP[type_lower]
        return BitFlags(name, **kw)

    if cls is Enum:
        kw = dict(common_kw)
        mapping = spec.get("mapping", spec.get("values", {}))
        parsed_mapping = {}
        for k, v in mapping.items():
            parsed_mapping[int(k) if isinstance(k, str) and k.isdigit() else k] = v
        kw["mapping"] = parsed_mapping
        base_type = spec.get("base_type", spec.get("size"))
        if base_type is not None:
            type_lower = base_type.lower()
            if type_lower in _TYPE_MAP:
                kw["type_"] = _TYPE_MAP[type_lower]
        return Enum(name, **kw)

    return cls(name, **common_kw)


def build_parser_from_schema(schema):
    endian = Endian.NATIVE
    endian_spec = schema.get("endian", schema.get("byte_order"))
    if endian_spec is not None:
        endian = _parse_endian(endian_spec) or Endian.NATIVE

    name = schema.get("name", schema.get("format"))

    fields_spec = schema.get("fields", [])
    fields = [_build_field(f) for f in fields_spec]

    return BinaryParser(fields, endian=endian, name=name)


def build_parser_from_file(path):
    schema = load_schema(path)
    return build_parser_from_schema(schema)
