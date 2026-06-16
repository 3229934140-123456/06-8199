from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional
from .fields import Field, Endian, _resolve_ref
from .errors import ParseError, InsufficientDataError


@dataclass
class FieldInfo:
    name: str
    path: List[str]
    start_offset: int
    end_offset: int
    size: int
    raw: bytes
    value: Any = None
    hidden: bool = False

    def to_dict(self):
        d = {
            "name": self.name,
            "path": ".".join(self.path),
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "size": self.size,
            "hex": self.raw.hex(),
            "value": _to_jsonable(self.value),
        }
        return d


@dataclass
class ParseResult:
    data: Dict[str, Any]
    consumed: int
    remaining: bytes
    fields_order: List[str] = field(default_factory=list)
    field_info: List[FieldInfo] = field(default_factory=list)

    def __getitem__(self, key):
        return self.data[key]

    def __contains__(self, key):
        return key in self.data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def to_dict(self):
        return _to_jsonable(self.data)


def _to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, bytearray):
        return obj.hex()
    if isinstance(obj, float):
        return obj
    return obj


class BinaryParser:
    def __init__(self, fields, *, endian=Endian.NATIVE, name=None):
        self.fields = fields
        self.endian = endian
        self.name = name

    def parse(self, data, offset=0, context=None, inspect=False):
        if isinstance(data, (bytes, bytearray)):
            byte_data = bytes(data)
        else:
            raise TypeError("data must be bytes or bytearray")

        ctx = context.copy() if context else {}
        field_info = [] if inspect else None
        result_data, new_offset = _parse_fields(
            self.fields, byte_data, offset, ctx, self.endian,
            path=[], field_info=field_info,
        )

        return ParseResult(
            data=result_data,
            consumed=new_offset - offset,
            remaining=byte_data[new_offset:],
            fields_order=list(result_data.keys()),
            field_info=field_info or [],
        )

    def parse_file(self, filepath, offset=0, context=None, inspect=False):
        with open(filepath, "rb") as f:
            data = f.read()
        return self.parse(data, offset=offset, context=context, inspect=inspect)

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


def _parse_fields(fields, data, offset, context, endian, path=None, field_info=None):
    if path is None:
        path = []
    result = {}
    current_offset = offset
    data_len = len(data)

    for field in fields:
        if not isinstance(field, Field):
            raise TypeError(f"expected Field, got {type(field).__name__}")

        if field.offset is not None:
            if field.offset < 0:
                field_offset = data_len + field.offset
            else:
                field_offset = offset + field.offset
            if field_offset < 0 or field_offset > data_len:
                raise InsufficientDataError(
                    required=1,
                    available=-1,
                    offset=max(0, min(field_offset, max(0, data_len - 1))),
                    field_name=field.name,
                    total_length=data_len,
                )
            current_offset = field_offset

        if field.align is not None:
            aligned = _align(current_offset, field.align)
            if aligned < 0 or aligned > data_len:
                raise InsufficientDataError(
                    required=1,
                    available=-1,
                    offset=max(0, min(aligned, max(0, data_len - 1))),
                    field_name=field.name,
                    total_length=data_len,
                )
            current_offset = aligned

        start_offset = current_offset
        try:
            fields_dict, current_offset = field.parse_fields(
                data, current_offset, context, endian
            )
        except InsufficientDataError as e:
            if e.total_length is None:
                raise InsufficientDataError(
                    required=e.required,
                    available=e.available,
                    offset=e.offset,
                    field_name=e.field_name,
                    field_path=e.field_path,
                    total_length=data_len,
                )
            raise
        except ParseError as e:
            if e.offset is None:
                e = e.with_context(offset=current_offset)
            raise

        end_offset = current_offset

        for k, v in fields_dict.items():
            result[k] = v
            context[k] = v

            if field_info is not None:
                raw_start = start_offset
                raw_end = end_offset
                raw_start = max(0, min(raw_start, data_len))
                raw_end = max(raw_start, min(raw_end, data_len))
                raw = data[raw_start:raw_end]

                field_path = list(path)
                if k != field.name or field.name is None:
                    field_path.append(k)
                else:
                    field_path.append(field.name)

                field_info.append(FieldInfo(
                    name=k,
                    path=field_path,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    size=end_offset - start_offset,
                    raw=raw,
                    value=v,
                ))

    return result, current_offset


def _align(offset, alignment):
    if alignment <= 0:
        return offset
    remainder = offset % alignment
    if remainder == 0:
        return offset
    return offset + (alignment - remainder)
