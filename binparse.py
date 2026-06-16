import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binary_parser import (
    build_parser_from_file, ParseError, InsufficientDataError, ValidationError,
    filter_field_info, export_field_info_json, export_field_info_csv,
    compare_results,
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
        if e.required is not None and e.required > 0:
            parts.append(f"  Required: {e.required} bytes")

    if isinstance(e, ValidationError):
        parts.append(f"  Expected: {e.expected!r}")
        parts.append(f"  Actual:   {e.actual!r}")

    if e.offset is not None and data is not None:
        parts.append("")
        parts.append("  Context (hexdump around error offset):")
        parts.append(hexdump(data, e.offset))

    return "\n".join(parts)


def format_inspect_table(field_info_list, total_consumed=None):
    rows = []
    max_path_len = 4
    max_offset_len = 8
    max_size_len = 4
    max_hex_len = 8

    for info in field_info_list:
        path_str = ".".join(info.path)
        offset_str = f"0x{info.start_offset:04x}"
        end_str = f"0x{info.end_offset:04x}"
        size_str = str(info.size)
        hex_str = info.raw.hex() if len(info.raw) <= 16 else info.raw[:16].hex() + "..."

        if isinstance(info.value, bytes):
            val_repr = f"b'{info.value[:16].hex()}..." if len(info.value) > 16 else repr(info.value)
        elif isinstance(info.value, dict):
            val_repr = json.dumps(info.value, ensure_ascii=False, default=_json_default)
        elif isinstance(info.value, list):
            val_repr = f"[list({len(info.value)})]"
        else:
            val_repr = repr(info.value)

        if len(val_repr) > 60:
            val_repr = val_repr[:57] + "..."

        rows.append((path_str, offset_str, end_str, size_str, hex_str, val_repr))

        max_path_len = max(max_path_len, len(path_str))
        max_offset_len = max(max_offset_len, len(offset_str))
        max_size_len = max(max_size_len, len(size_str))
        max_hex_len = max(max_hex_len, len(hex_str))

    header = (
        f"{'Path':<{max_path_len}}  "
        f"{'Start':<{max_offset_len}}  "
        f"{'End':<{max_offset_len}}  "
        f"{'Size':<{max_size_len}}  "
        f"{'Hex':<{max_hex_len}}  "
        f"Value"
    )
    sep = "-" * len(header)

    lines = [sep, header, sep]
    for path_str, offset_str, end_str, size_str, hex_str, val_repr in rows:
        lines.append(
            f"{path_str:<{max_path_len}}  "
            f"{offset_str:<{max_offset_len}}  "
            f"{end_str:<{max_offset_len}}  "
            f"{size_str:<{max_size_len}}  "
            f"{hex_str:<{max_hex_len}}  "
            f"{val_repr}"
        )
    lines.append(sep)
    footer = f"Total fields: {len(field_info_list)}"
    if total_consumed is not None:
        footer += f"  Consumed: {total_consumed} bytes"
    lines.append(footer)
    return "\n".join(lines)


def format_compare_table(diffs):
    rows = []
    max_path_len = 4
    max_type_len = 4

    for d in diffs:
        type_str = d.diff_type
        path_str = d.path
        old_short = _short_value(d.old_value, d.old_hex)
        new_short = _short_value(d.new_value, d.new_hex)
        rows.append((path_str, type_str, old_short, new_short))
        max_path_len = max(max_path_len, len(path_str))
        max_type_len = max(max_type_len, len(type_str))

    header = (
        f"{'Path':<{max_path_len}}  "
        f"{'Type':<{max_type_len}}  "
        f"{'Old':<32s}  "
        f"{'New':<32s}"
    )
    sep = "-" * len(header)
    lines = [sep, header, sep]
    for path_str, type_str, old_s, new_s in rows:
        lines.append(
            f"{path_str:<{max_path_len}}  "
            f"{type_str:<{max_type_len}}  "
            f"{old_s:<32s}  "
            f"{new_s:<32s}"
        )
    lines.append(sep)
    lines.append(f"Total differences: {len(diffs)}")
    return "\n".join(lines)


def _short_value(value, hex_str):
    if value is None:
        return "(absent)"
    if isinstance(value, (list, dict)):
        return f"<{type(value).__name__} len={len(value)}>"
    v = repr(value)
    if len(v) > 28:
        v = v[:25] + "..."
    if hex_str and len(hex_str) <= 10:
        return f"{v} [{hex_str}]"
    return v


def _json_default(obj):
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, bytearray):
        return obj.hex()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def main():
    argparser = argparse.ArgumentParser(
        prog="binparse",
        description="Binary structure parser - parse/inspect/compare binary files using declarative format definitions",
    )
    argparser.add_argument(
        "schema",
        help="Path to format definition file (JSON or YAML)",
    )
    argparser.add_argument(
        "binary",
        help="Path to binary file to parse (primary input)",
    )
    argparser.add_argument(
        "--compare",
        metavar="BINARY2",
        help="Compare mode: parse a second binary file and show field-by-field diffs",
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
    argparser.add_argument(
        "--inspect",
        action="store_true",
        help="Inspect mode: also print a table with each field's offset, hex and value",
    )
    argparser.add_argument(
        "--filter",
        metavar="PATH_PREFIX",
        help="Only show fields whose path starts with this prefix (e.g. 'file_entries' or 'header.version')",
    )
    argparser.add_argument(
        "--export-json",
        metavar="OUTPUT.json",
        help="Export inspect results to a JSON file",
    )
    argparser.add_argument(
        "--export-csv",
        metavar="OUTPUT.csv",
        help="Export inspect results to a CSV file",
    )

    args = argparser.parse_args()

    need_inspect = any([args.inspect, args.filter, args.export_json, args.export_csv, args.compare])

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

    data2 = None
    if args.compare:
        try:
            with open(args.compare, "rb") as f:
                data2 = f.read()
        except Exception as e:
            print(f"\033[91mERROR\033[0m: Failed to read compare file: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        result = parser.parse(data, offset=args.offset, inspect=need_inspect)
    except InsufficientDataError as e:
        print(format_error(e, data), file=sys.stderr)
        sys.exit(1)
    except ValidationError as e:
        print(format_error(e, data), file=sys.stderr)
        sys.exit(1)
    except ParseError as e:
        print(format_error(e, data), file=sys.stderr)
        sys.exit(1)

    result2 = None
    if data2 is not None:
        try:
            result2 = parser.parse(data2, offset=args.offset, inspect=True)
        except InsufficientDataError as e:
            print(format_error(e, data2), file=sys.stderr)
            sys.exit(1)
        except ValidationError as e:
            print(format_error(e, data2), file=sys.stderr)
            sys.exit(1)
        except ParseError as e:
            print(format_error(e, data2), file=sys.stderr)
            sys.exit(1)

    field_info = result.field_info
    if args.filter:
        field_info = filter_field_info(field_info, args.filter)

    if args.inspect:
        print(format_inspect_table(field_info, result.consumed))
        print()

    if args.export_json:
        export_field_info_json(field_info, args.export_json)
        print(f"\033[92m[export]\033[0m JSON written to {args.export_json} ({len(field_info)} records)")
    if args.export_csv:
        export_field_info_csv(field_info, args.export_csv)
        print(f"\033[92m[export]\033[0m CSV  written to {args.export_csv} ({len(field_info)} records)")

    if args.compare and result2 is not None:
        diffs = compare_results(result, result2)
        print()
        print("=" * 60)
        print("  COMPARE RESULTS")
        print(f"  Old: {args.binary}")
        print(f"  New: {args.compare}")
        print("=" * 60)
        if not diffs:
            print("(no differences detected)")
        else:
            print(format_compare_table(diffs))
            print()
            print("Full diff details (JSON):")
            print(json.dumps([d.to_dict() for d in diffs], indent=2, default=_json_default, ensure_ascii=False))
        print()

    if not args.compare and not args.export_json and not args.export_csv:
        if args.raw:
            print(result.data)
        else:
            indent = None if args.compact else args.indent
            output = result.to_dict()
            print(json.dumps(output, indent=indent, default=_json_default, ensure_ascii=False))


if __name__ == "__main__":
    main()
