class ParseError(Exception):
    def __init__(self, message, offset=None, field_name=None, field_path=None):
        self.offset = offset
        self.field_name = field_name
        self.field_path = field_path or []
        super().__init__(self._build_message(message))

    def _build_message(self, message):
        parts = []
        if self.field_path:
            parts.append(f"field '{'.'.join(self.field_path)}'")
        elif self.field_name:
            parts.append(f"field '{self.field_name}'")
        if self.offset is not None:
            parts.append(f"at offset 0x{self.offset:08x} ({self.offset})")
        parts.append(message)
        return ": ".join(parts)

    def with_context(self, offset=None, field_name=None, field_path=None):
        new_offset = offset if offset is not None else self.offset
        new_name = field_name if field_name is not None else self.field_name
        new_path = field_path if field_path is not None else self.field_path
        return ParseError(
            str(self),
            offset=new_offset,
            field_name=new_name,
            field_path=new_path,
        )


class InsufficientDataError(ParseError):
    def __init__(self, required, available, offset=None, field_name=None, field_path=None, total_length=None):
        self.required = required
        self.available = available
        self.total_length = total_length
        if available < 0:
            message = (
                f"offset 0x{offset:08x} ({offset}) is beyond end of input "
                f"(input is {total_length} bytes)"
            )
        else:
            message = f"insufficient data: need {required} bytes, only {available} available"
        super().__init__(message, offset=offset, field_name=field_name, field_path=field_path)


class ValidationError(ParseError):
    def __init__(self, expected, actual, offset=None, field_name=None, field_path=None):
        self.expected = expected
        self.actual = actual
        message = f"validation failed: expected {expected!r}, got {actual!r}"
        super().__init__(message, offset=offset, field_name=field_name, field_path=field_path)
