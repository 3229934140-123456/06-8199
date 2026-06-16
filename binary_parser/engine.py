from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional
from .fields import Field, Endian, _resolve_ref
from .errors import ParseError, InsufficientDataError


@dataclass
class ParseResult:
    data: Dict[str, Any]
    consumed: int
    remaining: bytes
    fields_order: List[str] = field(default_factory=list)

    def __getitem__(self, key):
        return self.data[key]

    def __contains__(self, key):
        return key in self.data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def to_dict(self):
        return self.data.copy()


class BinaryParser:
    def __init__(self, fields, *, endian=Endian.NATIVE, name=None):
        self.fields = fields
        self.endian = endian
        self.name = name

    def parse(self, data, offset=0, context=None):
        if isinstance(data, (bytes, bytearray)):
            byte_data = bytes(data)
        else:
            raise TypeError("data must be bytes or bytearray")

        ctx = context.copy() if context else {}
        result_data, new_offset = _parse_fields(
            self.fields, byte_data, offset, ctx, self.endian
        )

        return ParseResult(
            data=result_data,
            consumed=new_offset - offset,
            remaining=byte_data[new_offset:],
            fields_order=list(result_data.keys()),
        )

    def parse_file(self, filepath, offset=0, context=None):
        with open(filepath, "rb") as f:
            data = f.read()
        return self.parse(data, offset=offset, context=context)

    def size(self, context=None):
        total = 0
        ctx = context.copy() if context else {}
        for f in self.fields:
            if isinstance(f, Field):
                if f.offset is not None:
                    total = f.offset
                if f.align is not None:
                    total = _align(total, f.align)
                try:
                    total += f.size(ctx)
                except ValueError:
                    pass
        return total


def _parse_fields(fields, data, offset, context, endian):
    result = {}
    current_offset = offset

    for field in fields:
        if not isinstance(field, Field):
            raise TypeError(f"expected Field, got {type(field).__name__}")

        if field.offset is not None:
            if field.offset < 0:
                field_offset = len(data) + field.offset
            else:
                field_offset = offset + field.offset
            current_offset = field_offset

        if field.align is not None:
            aligned = _align(current_offset, field.align)
            if aligned > len(data):
                raise InsufficientDataError(
                    required=aligned - current_offset,
                    available=len(data) - current_offset,
                    offset=current_offset,
                    field_name=field.name,
                )
            current_offset = aligned

        try:
            fields_dict, current_offset = field.parse_fields(
                data, current_offset, context, endian
            )
        except ParseError as e:
            if e.offset is None:
                e = e.with_context(offset=current_offset)
            raise

        for k, v in fields_dict.items():
            result[k] = v
            context[k] = v

    return result, current_offset


def _align(offset, alignment):
    if alignment <= 0:
        return offset
    remainder = offset % alignment
    if remainder == 0:
        return offset
    return offset + (alignment - remainder)
