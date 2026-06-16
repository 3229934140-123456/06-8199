import struct
from enum import Enum
from .errors import ParseError, InsufficientDataError, ValidationError


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

    def parse_fields(self, data, offset, context, endian=Endian.NATIVE):
        value, new_offset = self.parse(data, offset, context, endian)
        result = {}
        if self.name is not None:
            result[self.name] = value
        return result, new_offset

    def _resolve_endian(self, endian):
        return self.endian.value if self.endian else endian.value

    def _validate(self, value, context):
        if self.validator is not None:
            if callable(self.validator):
                if not self.validator(value):
                    raise ValidationError(
                        expected="validator pass",
                        actual=value,
                        field_name=self.name,
                    )
            elif value != self.validator:
                raise ValidationError(
                    expected=self.validator,
                    actual=value,
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
        self._validate(value, context)
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
            return _resolve_ref(self.length, context)
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
        self._validate(value, context)
        return value, offset + length

    def parse_fields(self, data, offset, context, endian=Endian.NATIVE):
        if isinstance(self.length, Field) and self.length.name:
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
            value = data[offset:offset + length]
            self._validate(value, context)

            result = {self.length.name: len_val}
            if self.name is not None:
                result[self.name] = value
            return result, offset + length
        else:
            return super().parse_fields(data, offset, context, endian)


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
            return _resolve_ref(self.length, context)
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

        self._validate(value, context)
        return value, new_offset

    def parse_fields(self, data, offset, context, endian=Endian.NATIVE):
        if isinstance(self.length, Field) and self.length.name:
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

            self._validate(value, context)

            result = {self.length.name: len_val}
            if self.name is not None:
                result[self.name] = value
            return result, new_offset
        else:
            return super().parse_fields(data, offset, context, endian)


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
            return _resolve_ref(self.length, context)
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
            return _resolve_ref(self.count, context)
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


class Struct(Field):
    def __init__(self, name=None, *, fields, **kwargs):
        super().__init__(name, **kwargs)
        self.fields = fields

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        from .engine import _parse_fields
        result, offset = _parse_fields(self.fields, data, offset, context, endian)
        self._validate(result, context)
        return result, offset


class Conditional(Field):
    def __init__(self, name=None, *, condition, field, **kwargs):
        super().__init__(name, **kwargs)
        self.condition = condition
        self.field = field

    def _eval_condition(self, context):
        if callable(self.condition):
            return self.condition(context)
        if isinstance(self.condition, str):
            return bool(_resolve_ref(self.condition, context))
        return bool(self.condition)

    def parse(self, data, offset, context, endian=Endian.NATIVE):
        if self._eval_condition(context):
            value, offset = self.field.parse(data, offset, context, endian)
            return value, offset
        else:
            return None, offset


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
