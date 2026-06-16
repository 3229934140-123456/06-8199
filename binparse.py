import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binary_parser import (
    build_parser_from_file, ParseError, InsufficientDataError, ValidationError,
)


def hexdump(data, offset, context_bytes=16):
    start = max(0, offset - context_bytes)
    end = min(len(data), offset + context_bytes)
    chunk = data[start:end]

    lines = []
    for i in range(0, len(chunk), 16):
        line_offset = start + i
        line_data = chunk[i:i + 16]
        hex_part = " ".join(f"{b:02x}" for b in line_data)
        ascii_part = "".join(
            chr(b) if 32 <= b < 127 else "." for b in line_data
        )
        pointer = ""
        if line_offset <= offset < line_offset + len(line_data):
            col = (offset - line_offset) * 3
            pointer = " " * (len(hex_part) + 3 + col) + "^"
        lines.append(f"  0x{line_offset:08x}  {hex_part:<48s}  |{ascii_part}|")
        if pointer:
            lines.append(pointer)

    return "\n".join(lines)


def format_error(e, data):
    parts = []
    parts.append(f"\033[91mERROR\033[0m: {e}")

    if isinstance(e, InsufficientDataError):
        if e.total_length is not None:
            parts.append(f"  Input length: {e.total_length} bytes")
        if e.required is not None:
            parts.append(f"  Required: {e.required} bytes")

    if e.offset is not None and data is not None:
        parts.append("")
        parts.append("  Context (hexdump around error offset):")
        parts.append(hexdump(data, e.offset))

    return "\n".join(parts)


def custom_json_serializer(obj):
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, bytearray):
        return obj.hex()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def main():
    argparser = argparse.ArgumentParser(
        prog="binparse",
        description="Binary structure parser - parse binary files using declarative format definitions",
    )
    argparser.add_argument(
        "schema",
        help="Path to format definition file (JSON or YAML)",
    )
    argparser.add_argument(
        "binary",
        help="Path to binary file to parse",
    )
    argparser.add_argument(
        "-o", "--offset",
        type=int,
        default=0,
        help="Starting offset in the binary file (default: 0)",
    )
    argparser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent level (default: 2)",
    )
    argparser.add_argument(
        "--compact",
        action="store_true",
        help="Output compact JSON (no indentation)",
    )
    argparser.add_argument(
        "--raw",
        action="store_true",
        help="Output raw Python dict instead of JSON",
    )

    args = argparser.parse_args()

    try:
        parser = build_parser_from_file(args.schema)
    except Exception as e:
        print(f"\033[91mERROR\033[0m: Failed to load schema: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.binary, "rb") as f:
            data = f.read()
    except Exception as e:
        print(f"\033[91mERROR\033[0m: Failed to read binary file: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = parser.parse(data, offset=args.offset)
    except InsufficientDataError as e:
        print(format_error(e, data), file=sys.stderr)
        sys.exit(1)
    except ValidationError as e:
        print(format_error(e, data), file=sys.stderr)
        sys.exit(1)
    except ParseError as e:
        print(format_error(e, data), file=sys.stderr)
        sys.exit(1)

    if args.raw:
        print(result.data)
    else:
        indent = None if args.compact else args.indent
        output = result.to_dict()
        print(json.dumps(output, indent=indent, default=custom_json_serializer, ensure_ascii=False))


if __name__ == "__main__":
    main()
