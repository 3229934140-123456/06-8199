from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional, Tuple
from .fields import Field, Endian, _resolve_ref
from .errors import ParseError, InsufficientDataError
import csv
import io
import json


@dataclass
class DiffEntry:
    path: str
    old_value: Any = None
    new_value: Any = None
    old_start: Optional[int] = None
    new_start: Optional[int] = None
    old_size: Optional[int] = None
    new_size: Optional[int] = None
    old_hex: str = ""
    new_hex: str = ""
    diff_type: str = "value"  # value / size / missing / added

    def to_dict(self):
        return {
            "path": self.path,
            "diff_type": self.diff_type,
            "old": {
                "value": _to_jsonable(self.old_value),
                "start_offset": self.old_start,
                "size": self.old_size,
                "hex": self.old_hex,
            },
            "new": {
                "value": _to_jsonable(self.new_value),
                "start_offset": self.new_start,
                "size": self.new_size,
                "hex": self.new_hex,
            },
        }


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
        field_info_raw = [] if inspect else None
        result_data, new_offset = _parse_fields(
            self.fields, byte_data, offset, ctx, self.endian,
            path=[], field_info=field_info_raw,
        )

        field_info_objs = []
        if field_info_raw is not None:
            for d in field_info_raw:
                field_info_objs.append(FieldInfo(
                    name=d["name"],
                    path=d["path"],
                    start_offset=d["start_offset"],
                    end_offset=d["end_offset"],
                    size=d["size"],
                    raw=d["raw"],
                    value=d["value"],
                ))

        return ParseResult(
            data=result_data,
            consumed=new_offset - offset,
            remaining=byte_data[new_offset:],
            fields_order=list(result_data.keys()),
            field_info=field_info_objs,
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

        try:
            fields_dict, current_offset = field.parse_fields(
                data, current_offset, context, endian,
                path=path, field_info=field_info,
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


def filter_field_info(field_info_list, prefix=None):
    """按路径前缀过滤 field_info，prefix 可以是 'file_entries' 或 'header.version' 等。"""
    if not prefix:
        return list(field_info_list)
    parts = prefix.strip(".").split(".")
    return [
        fi for fi in field_info_list
        if fi.path[: len(parts)] == parts
    ]


def export_field_info_json(field_info_list, filepath=None):
    """导出 field_info 为 JSON 字符串或写入文件。"""
    data = [fi.to_dict() for fi in field_info_list]
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if filepath:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text)
    return text


def export_field_info_csv(field_info_list, filepath=None):
    """导出 field_info 为 CSV 字符串或写入文件。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "path", "name", "start_offset", "end_offset", "size",
        "hex", "value",
    ])
    for fi in field_info_list:
        value_repr = _value_to_csv(_to_jsonable(fi.value))
        writer.writerow([
            ".".join(fi.path),
            fi.name,
            fi.start_offset,
            fi.end_offset,
            fi.size,
            fi.raw.hex(),
            value_repr,
        ])
    text = buf.getvalue()
    if filepath:
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    return text


def _value_to_csv(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def compare_results(old_result: ParseResult, new_result: ParseResult) -> List[DiffEntry]:
    """按路径对比两份 ParseResult 的 field_info，返回差异列表。

    对比维度：值、原始十六进制、大小。
    """
    old_map = {".".join(fi.path): fi for fi in old_result.field_info}
    new_map = {".".join(fi.path): fi for fi in new_result.field_info}
    diffs = []

    all_paths = set(old_map.keys()) | set(new_map.keys())
    for p in sorted(all_paths):
        old_fi = old_map.get(p)
        new_fi = new_map.get(p)

        if old_fi is None:
            diffs.append(DiffEntry(
                path=p,
                new_value=new_fi.value,
                new_start=new_fi.start_offset,
                new_size=new_fi.size,
                new_hex=new_fi.raw.hex(),
                diff_type="added",
            ))
            continue
        if new_fi is None:
            diffs.append(DiffEntry(
                path=p,
                old_value=old_fi.value,
                old_start=old_fi.start_offset,
                old_size=old_fi.size,
                old_hex=old_fi.raw.hex(),
                diff_type="missing",
            ))
            continue

        old_val_json = json.dumps(_to_jsonable(old_fi.value), sort_keys=True, ensure_ascii=False)
        new_val_json = json.dumps(_to_jsonable(new_fi.value), sort_keys=True, ensure_ascii=False)
        old_hex = old_fi.raw.hex()
        new_hex = new_fi.raw.hex()

        if old_fi.size != new_fi.size:
            diff_type = "size"
        elif old_hex != new_hex or old_val_json != new_val_json:
            diff_type = "value"
        else:
            continue

        diffs.append(DiffEntry(
            path=p,
            old_value=old_fi.value,
            new_value=new_fi.value,
            old_start=old_fi.start_offset,
            new_start=new_fi.start_offset,
            old_size=old_fi.size,
            new_size=new_fi.size,
            old_hex=old_hex,
            new_hex=new_hex,
            diff_type=diff_type,
        ))
    return diffs
