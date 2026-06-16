import struct
from enum import Enum
from .errors import ParseError, InsufficientDataError, ValidationError
from .expression import eval_expression, is_expression_string


def _resolve_ref_or_expr(ref, context):
    if isinstance(ref, str) and is_expression_string(ref):
        return eval_expression(ref, context)
    return _resolve_ref(ref, context)


class Endian(Enum):
    LITTLE = "<"
    BIG = ">"
    NATIVE = "="
    NETWORK = ">"


ByteOrder = Endian


class Field:
    def __init__(self, name=None, *, endian=None, offset=None, align=None, validator=None, default=None):
        self.name = name
        self.endian = endian
        self.offset = offset
        self.align = align
        self.validator = validator
        self.default = default
        self._size = None

    def size(self, context=None):
        if self._size is None:
            raise ValueError(f"Field '{self.name}' has no fixed size")
        return self._size

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        raise NotImplementedError

    def parse_fields(self, data, offset, context, endian=Endian.NATIVE, *, path=None, field_info=None):
        value, new_offset = self.parse(data, offset, context, endian)
        result = {}
        if self.name is not None:
            result[self.name] = value
            if field_info is not None:
                _record_field_info(
                    field_info, path, self.name, value, data, offset, new_offset
                )
        return result, new_offset

    def _resolve_endian(self, endian):
        return self.endian.value if self.endian else endian.value

    def _validate(self, value, context, offset=None):
        if self.validator is not None:
            if callable(self.validator):
                if not self.validator(value):
                    raise ValidationError(
                        expected="validator pass",
                        actual=value,
                        offset=offset,
                        field_name=self.name,
                    )
            elif value != self.validator:
                raise ValidationError(
                    expected=self.validator,
                    actual=value,
                    offset=offset,
                    field_name=self.name,
                )
        return value


class _NumericField(Field):
    def __init__(self, name=None, *, fmt, size, endian=None, **kwargs):
        super().__init__(name, endian=endian, **kwargs)
        self._fmt_char = fmt
        self._size = size

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        fmt = self._resolve_endian(endian) + self._fmt_char
        needed = struct.calcsize(fmt)
        if offset + needed > len(data):
            raise InsufficientDataError(
                required=needed,
                available=len(data) - offset,
                offset=offset,
                field_name=self.name,
            )
        value = struct.unpack_from(fmt, data, offset)[0]
        self._validate(value, context, offset=offset)
        return value, offset + needed


class UInt8(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="B", size=1, **kwargs)


class UInt16(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="H", size=2, **kwargs)


class UInt32(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="I", size=4, **kwargs)


class UInt64(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="Q", size=8, **kwargs)


class Int8(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="b", size=1, **kwargs)


class Int16(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="h", size=2, **kwargs)


class Int32(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="i", size=4, **kwargs)


class Int64(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="q", size=8, **kwargs)


class Float32(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="f", size=4, **kwargs)


class Float64(_NumericField):
    def __init__(self, name=None, **kwargs):
        super().__init__(name, fmt="d", size=8, **kwargs)


class Bytes(Field):
    def __init__(self, name=None, *, length=None, **kwargs):
        super().__init__(name, **kwargs)
        self.length = length
        if isinstance(length, int):
            self._size = length

    def size(self, context=None):
        if isinstance(self.length, Field):
            raise ValueError("Bytes with Field length has no pre-determined size")
        if callable(self.length):
            return self.length(context)
        if isinstance(self.length, str):
            return _resolve_ref_or_expr(self.length, context)
        return self.length

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        if isinstance(self.length, Field):
            len_val, offset = self.length.parse(data, offset, context, endian)
            length = len_val
            if self.length.name:
                context[self.length.name] = len_val
        else:
            length = self.size(context)

        if offset + length > len(data):
            raise InsufficientDataError(
                required=length,
                available=len(data) - offset,
                offset=offset,
                field_name=self.name,
            )
        value = data[offset:offset + length]
        self._validate(value, context, offset=offset)
        return value, offset + length

    def parse_fields(self, data, offset, context, endian=Endian.NATIVE, *, path=None, field_info=None):
        if isinstance(self.length, Field) and self.length.name:
            len_start = offset
            len_val, offset = self.length.parse(data, offset, context, endian)
            context[self.length.name] = len_val
            length = len_val

            if offset + length > len(data):
                raise InsufficientDataError(
                    required=length,
                    available=len(data) - offset,
                    offset=offset,
                    field_name=self.name,
                )

            start_value = offset
            value = data[offset:offset + length]
            self._validate(value, context, offset=offset)
            new_offset = offset + length

            if field_info is not None:
                _record_field_info(field_info, path, self.length.name, len_val,
                                   data, len_start, start_value)

            result = {self.length.name: len_val}
            if self.name is not None:
                result[self.name] = value
                if field_info is not None:
                    _record_field_info(field_info, path, self.name, value, data, start_value, new_offset)
            return result, new_offset
        else:
            return super().parse_fields(data, offset, context, endian, path=path, field_info=field_info)


class String(Field):
    def __init__(self, name=None, *, length=None, encoding="utf-8",
                 null_terminated=False, **kwargs):
        super().__init__(name, **kwargs)
        self.length = length
        self.encoding = encoding
        self.null_terminated = null_terminated
        if isinstance(length, int) and not null_terminated:
            self._size = length

    def size(self, context=None):
        if isinstance(self.length, Field):
            raise ValueError(f"String '{self.name}' with Field length has no pre-determined size")
        if self._size is not None:
            return self._size
        if callable(self.length):
            return self.length(context)
        if isinstance(self.length, str):
            return _resolve_ref_or_expr(self.length, context)
        raise ValueError(f"String '{self.name}' has no determinable size")

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        if isinstance(self.length, Field):
            len_val, offset = self.length.parse(data, offset, context, endian)
            length = len_val
            if self.length.name:
                context[self.length.name] = len_val
        else:
            length = None

        if self.null_terminated:
            end = offset
            while end < len(data) and data[end] != 0:
                end += 1
            if end >= len(data):
                raise InsufficientDataError(
                    required=end - offset + 1,
                    available=len(data) - offset,
                    offset=offset,
                    field_name=self.name,
                )
            raw = data[offset:end]
            new_offset = end + 1
        else:
            if length is None:
                length = self.size(context)
            if offset + length > len(data):
                raise InsufficientDataError(
                    required=length,
                    available=len(data) - offset,
                    offset=offset,
                    field_name=self.name,
                )
            raw = data[offset:offset + length]
            new_offset = offset + length

        try:
            value = raw.decode(self.encoding)
        except UnicodeDecodeError as e:
            raise ParseError(
                f"failed to decode string: {e}",
                offset=offset,
                field_name=self.name,
            ) from e

        self._validate(value, context, offset=offset)
        return value, new_offset

    def parse_fields(self, data, offset, context, endian=Endian.NATIVE, *, path=None, field_info=None):
        if isinstance(self.length, Field) and self.length.name:
            len_start = offset
            len_val, offset = self.length.parse(data, offset, context, endian)
            context[self.length.name] = len_val
            length = len_val

            if self.null_terminated:
                end = offset
                while end < len(data) and data[end] != 0:
                    end += 1
                if end >= len(data):
                    raise InsufficientDataError(
                        required=end - offset + 1,
                        available=len(data) - offset,
                        offset=offset,
                        field_name=self.name,
                    )
                raw = data[offset:end]
                new_offset = end + 1
            else:
                if offset + length > len(data):
                    raise InsufficientDataError(
                        required=length,
                        available=len(data) - offset,
                        offset=offset,
                        field_name=self.name,
                    )
                raw = data[offset:offset + length]
                new_offset = offset + length

            try:
                value = raw.decode(self.encoding)
            except UnicodeDecodeError as e:
                raise ParseError(
                    f"failed to decode string: {e}",
                    offset=offset,
                    field_name=self.name,
                ) from e

            self._validate(value, context, offset=offset)

            start_value = offset
            if field_info is not None:
                _record_field_info(field_info, path, self.length.name, len_val,
                                   data, len_start, start_value)

            result = {self.length.name: len_val}
            if self.name is not None:
                result[self.name] = value
                if field_info is not None:
                    _record_field_info(field_info, path, self.name, value, data, start_value, new_offset)
            return result, new_offset
        else:
            return super().parse_fields(data, offset, context, endian, path=path, field_info=field_info)


class Padding(Field):
    def __init__(self, length=1, *, pattern=b"\x00", **kwargs):
        super().__init__(None, **kwargs)
        self.length = length
        self.pattern = pattern
        if isinstance(length, int):
            self._size = length

    def size(self, context=None):
        if callable(self.length):
            return self.length(context)
        if isinstance(self.length, str):
            return _resolve_ref_or_expr(self.length, context)
        return self.length

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        length = self.size(context)
        if offset + length > len(data):
            raise InsufficientDataError(
                required=length,
                available=len(data) - offset,
                offset=offset,
            )
        if self.pattern is not None and len(self.pattern) == 1:
            expected = self.pattern * length
            actual = data[offset:offset + length]
            if expected != actual:
                raise ValidationError(
                    expected=expected,
                    actual=actual,
                    offset=offset,
                )
        return None, offset + length


class Array(Field):
    def __init__(self, name=None, *, element, count=None, **kwargs):
        super().__init__(name, **kwargs)
        self.element = element
        self.count = count
        if isinstance(count, int) and isinstance(element, _NumericField):
            self._size = count * element._size

    def size(self, context=None):
        if self._size is not None:
            return self._size
        count = self._resolve_count(context)
        if hasattr(self.element, "_size") and self.element._size is not None:
            return count * self.element._size
        raise ValueError(f"Array '{self.name}' has no determinable size")

    def _resolve_count(self, context):
        if callable(self.count):
            return self.count(context)
        if isinstance(self.count, str):
            return int(_resolve_ref_or_expr(self.count, context))
        if isinstance(self.count, int):
            return self.count
        raise ValueError(f"Array '{self.name}' has no count")

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        count = self._resolve_count(context)
        results = []
        ctx = context.copy() if context else {}
        if self.name:
            ctx[self.name] = results

        for i in range(count):
            try:
                value, offset = self.element.parse(data, offset, ctx, endian)
                results.append(value)
            except ParseError as e:
                raise e.with_context(
                    field_path=[self.name, f"[{i}]"] if self.name else [f"[{i}]"]
                )

        self._validate(results, context)
        return results, offset

    def parse_fields(self, data, offset, context, endian=Endian.NATIVE, *, path=None, field_info=None):
        count = self._resolve_count(context)
        results = []
        ctx = context.copy() if context else {}
        if self.name:
            ctx[self.name] = results

        start_offset = offset
        for i in range(count):
            elem_start = offset
            inner_path = list(path) if path else []
            if self.name:
                inner_path.append(self.name)
            inner_path.append(str(i))
            try:
                if hasattr(self.element, "parse_fields"):
                    elem_result, offset = self.element.parse_fields(
                        data, offset, ctx, endian, path=inner_path, field_info=field_info
                    )
                    if len(elem_result) == 1:
                        value = next(iter(elem_result.values()))
                    elif len(elem_result) > 1:
                        value = elem_result
                    else:
                        value, _ = self.element.parse(data, elem_start, ctx, endian)
                    results.append(value)
                else:
                    value, offset = self.element.parse(data, offset, ctx, endian)
                    results.append(value)
            except ParseError as e:
                raise e.with_context(
                    field_path=[self.name, f"[{i}]"] if self.name else [f"[{i}]"]
                )

        end_offset = offset
        self._validate(results, context)

        result = {}
        if self.name is not None:
            result[self.name] = results
            if field_info is not None:
                _record_field_info(field_info, path, self.name, results, data, start_offset, end_offset)
        return result, end_offset


class Struct(Field):
    def __init__(self, name=None, *, fields, **kwargs):
        super().__init__(name, **kwargs)
        self.fields = fields

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        from .engine import _parse_fields
        result, offset = _parse_fields(self.fields, data, offset, context, endian)
        self._validate(result, context)
        return result, offset

    def parse_fields(self, data, offset, context, endian=Endian.NATIVE, *, path=None, field_info=None):
        from .engine import _parse_fields
        struct_start = offset
        inner_path = list(path) if path else []
        if self.name is not None:
            inner_path.append(self.name)
        inner_dict, new_offset = _parse_fields(
            self.fields, data, offset, context, endian,
            path=inner_path, field_info=field_info,
        )
        struct_end = new_offset
        self._validate(inner_dict, context)

        if self.name is not None:
            if field_info is not None:
                _record_field_info(field_info, path, self.name, inner_dict,
                                   data, struct_start, struct_end)
            return {self.name: inner_dict}, new_offset
        else:
            # 匿名 struct（数组元素等）：直接返回内部字段的 flat dict
            return inner_dict, new_offset


class BitFlags(_NumericField):
    def __init__(self, name=None, *, bits, type_=None, endian=None, **kwargs):
        if type_ is not None:
            self._type_hint = type_
        elif "fmt" in kwargs:
            self._type_hint = None
        else:
            self._type_hint = UInt8
        if "fmt" not in kwargs:
            if type_ is UInt16:
                kwargs["fmt"] = "H"
                kwargs["size"] = 2
            elif type_ is UInt32:
                kwargs["fmt"] = "I"
                kwargs["size"] = 4
            elif type_ is UInt64:
                kwargs["fmt"] = "Q"
                kwargs["size"] = 8
            else:
                kwargs["fmt"] = "B"
                kwargs["size"] = 1
        super().__init__(name, endian=endian, **kwargs)
        self.bits = bits

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        raw_value, new_offset = super().parse(data, offset, context, endian)
        flags = {}
        for bit_pos, flag_name in self.bits.items():
            flags[flag_name] = bool(raw_value & (1 << bit_pos))
        return {
            "value": raw_value,
            "flags": flags,
        }, new_offset


class Enum(Field):
    def __init__(self, name=None, *, mapping, type_=None, endian=None, **kwargs):
        super().__init__(name, endian=endian, **kwargs)
        self.mapping = mapping
        if type_ is not None:
            self._inner = type_(name)
        else:
            self._inner = UInt8(name)
        self._size = self._inner._size

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        raw_value, new_offset = self._inner.parse(data, offset, context, endian)
        name = self.mapping.get(raw_value)
        return {
            "value": raw_value,
            "name": name,
        }, new_offset


class Conditional(Field):
    def __init__(self, name=None, *, condition, field, **kwargs):
        super().__init__(name, **kwargs)
        self.condition = condition
        self.field = field

    def _eval_condition(self, context):
        if callable(self.condition):
            return self.condition(context)
        if isinstance(self.condition, str):
            return bool(_resolve_ref_or_expr(self.condition, context))
        return bool(self.condition)

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        if self._eval_condition(context):
            value, offset = self.field.parse(data, offset, context, endian)
            return value, offset
        else:
            return None, offset

    def parse_fields(self, data, offset, context, endian=Endian.NATIVE, *, path=None, field_info=None):
        cond_start = offset
        present = self._eval_condition(context)
        if present:
            inner_path = list(path) if path else []
            if self.name is not None:
                inner_path.append(self.name)
            if hasattr(self.field, "parse_fields"):
                inner_result, new_offset = self.field.parse_fields(
                    data, offset, context, endian, path=inner_path, field_info=field_info
                )
                if len(inner_result) == 1:
                    value = next(iter(inner_result.values()))
                elif len(inner_result) > 1:
                    value = inner_result
                else:
                    value, _ = self.field.parse(data, offset, context, endian)
            else:
                value, new_offset = self.field.parse(data, offset, context, endian)
        else:
            value = None
            new_offset = offset
        cond_end = new_offset

        result = {}
        if self.name is not None:
            result[self.name] = value
            if field_info is not None:
                _record_field_info(field_info, path, self.name, value, data, cond_start, cond_end)
        else:
            # 匿名 conditional（虽然少见，但如果 field 有名字也可能返回 inner_result）
            if present and hasattr(self.field, "parse_fields"):
                return inner_result, new_offset
        return result, new_offset


def _resolve_ref(ref, context):
    parts = ref.split(".")
    value = context
    for part in parts:
        if isinstance(value, dict):
            if part not in value:
                raise ParseError(f"reference '{ref}' not found in context")
            value = value[part]
        else:
            if not hasattr(value, part):
                raise ParseError(f"reference '{ref}' not found in context")
            value = getattr(value, part)
    return value


def _record_field_info(field_info_list, parent_path, name, value, data, start_offset, end_offset):
    """往 field_info list 追加一条记录，记录为 dict，后续由 engine 转 FieldInfo。"""
    if field_info_list is None:
        return
    field_path = list(parent_path) if parent_path else []
    field_path.append(name)

    data_len = len(data)
    raw_start = max(0, min(start_offset, data_len))
    raw_end = max(raw_start, min(end_offset, data_len))
    raw = data[raw_start:raw_end]

    field_info_list.append({
        "name": name,
        "path": field_path,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "size": end_offset - start_offset,
        "raw": raw,
        "value": value,
    })
