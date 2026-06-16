"""
Schema 加载与引用解析。
支持 $ref 语法，可以引用同一文档或外部文件中的定义。

支持的 $ref 格式:
  #/definitions/point_struct        - 引用当前文档内的定义
  common_types.json                  - 引用另一个 JSON/YAML 文件的全部内容
  common_types.json#/file_type_enum  - 引用另一个文件中的某个定义

引用文件路径相对于被引用的 schema 文件所在目录。
"""

import json
import os
import copy


def _parse_ref(ref):
    if "#" in ref:
        file_part, frag_part = ref.split("#", 1)
    else:
        file_part, frag_part = ref, ""
    frag_path = frag_part.strip("/").split("/") if frag_part else []
    return file_part, frag_path


def _walk_path(obj, path, ref_str):
    current = obj
    for part in path:
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"cannot resolve $ref '{ref_str}': path segment '{part}' not found")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                raise ValueError(f"cannot resolve $ref '{ref_str}': invalid array index '{part}'")
        else:
            raise ValueError(f"cannot resolve $ref '{ref_str}': cannot descend into {type(current).__name__}")
    return current


def _load_file(path):
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    if ext in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML is required for YAML schema files. Install with: pip install pyyaml")
        return yaml.safe_load(raw)
    else:
        return json.loads(raw)


def resolve_refs(schema, base_dir, _resolving=None, _cache=None):
    """递归解析 schema 中的所有 $ref 引用，返回深拷贝后的 schema。"""
    if _resolving is None:
        _resolving = set()
    if _cache is None:
        _cache = {}

    schema = copy.deepcopy(schema)

    def _resolve(obj, current_base_dir, current_doc):
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref = obj["$ref"]
                extra_keys = {k: v for k, v in obj.items() if k != "$ref"}

                file_part, frag_path = _parse_ref(ref)

                if not file_part:
                    target_doc = current_doc
                    target_base = current_base_dir
                else:
                    if not os.path.isabs(file_part):
                        file_part = os.path.normpath(os.path.join(current_base_dir, file_part))
                    abs_path = os.path.abspath(file_part)
                    if abs_path in _resolving:
                        raise ValueError(f"circular reference detected: $ref '{ref}'")
                    if abs_path in _cache:
                        target_doc = _cache[abs_path]
                        target_base = os.path.dirname(abs_path)
                    else:
                        _resolving.add(abs_path)
                        try:
                            loaded = _load_file(abs_path)
                            target_base = os.path.dirname(abs_path)
                            target_doc = _resolve(loaded, target_base, loaded)
                            _cache[abs_path] = target_doc
                        finally:
                            _resolving.discard(abs_path)

                if frag_path:
                    resolved = _walk_path(target_doc, frag_path, ref)
                else:
                    resolved = target_doc

                if isinstance(resolved, dict):
                    merged = dict(resolved)
                    merged.update(extra_keys)
                    return _resolve(merged, target_base, current_doc if not file_part else target_doc)
                if extra_keys:
                    raise ValueError(f"cannot merge extra keys into non-dict $ref target: {ref}")
                return resolved

            result = {}
            for k, v in obj.items():
                result[k] = _resolve(v, current_base_dir, current_doc)
            return result

        if isinstance(obj, list):
            return [_resolve(item, current_base_dir, current_doc) for item in obj]

        return obj

    return _resolve(schema, base_dir, schema)


def load_schema(path):
    abs_path = os.path.abspath(path)
    base_dir = os.path.dirname(abs_path)
    schema = _load_file(abs_path)
    return resolve_refs(schema, base_dir)
