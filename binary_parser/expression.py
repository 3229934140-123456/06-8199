"""
安全的表达式求值器，用于 schema 中引用上下文字段并做简单算术/位运算。

支持的运算符（按优先级）:
    单目: - ~
    乘除: * / // %
    加减: + -
    位移: << >>
    位与: &
    位异或: ^
    位或:  |
    比较: == != < > <= >=
    逻辑: and or not

标识符用于访问上下文字段，支持点号访问嵌套字段:
    header.count     -> context["header"]["count"]
    flags.value      -> context["flags"]["value"]
"""

import ast
import operator
from .errors import ParseError


_SAFE_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
}

_SAFE_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Invert: operator.invert,
    ast.Not: operator.not_,
}


class _ExpressionEvaluator(ast.NodeVisitor):
    def __init__(self, context, expression_source):
        self.context = context
        self.expression_source = expression_source

    def _resolve_name(self, name):
        parts = name.split(".")
        value = self.context
        for part in parts:
            if isinstance(value, dict):
                if part not in value:
                    raise ParseError(
                        f"in expression {self.expression_source!r}: "
                        f"reference '{name}' not found in context (missing '{part}')"
                    )
                value = value[part]
            else:
                if not hasattr(value, part):
                    raise ParseError(
                        f"in expression {self.expression_source!r}: "
                        f"reference '{name}' not found in context "
                        f"({type(value).__name__} has no attribute '{part}')"
                    )
                value = getattr(value, part)
        return value

    def visit(self, node):
        method = "visit_" + node.__class__.__name__
        visitor = getattr(self, method, None)
        if visitor is None:
            raise ParseError(
                f"in expression {self.expression_source!r}: "
                f"unsupported node {node.__class__.__name__}"
            )
        return visitor(node)

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float, bool, str, type(None))):
            return node.value
        raise ParseError(
            f"in expression {self.expression_source!r}: "
            f"unsupported literal type {type(node.value).__name__}"
        )

    def visit_Name(self, node):
        return self._resolve_name(node.id)

    def visit_Attribute(self, node):
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            raise ParseError(
                f"in expression {self.expression_source!r}: "
                f"attribute chain must start with a name"
            )
        parts.reverse()
        full_name = current.id + "." + ".".join(parts)
        return self._resolve_name(full_name)

    def visit_BinOp(self, node):
        op_type = type(node.op)
        if op_type not in _SAFE_BINOPS:
            raise ParseError(
                f"in expression {self.expression_source!r}: "
                f"unsupported binary operator {op_type.__name__}"
            )
        left = self.visit(node.left)
        right = self.visit(node.right)
        return _SAFE_BINOPS[op_type](left, right)

    def visit_UnaryOp(self, node):
        op_type = type(node.op)
        if op_type not in _SAFE_UNARYOPS:
            raise ParseError(
                f"in expression {self.expression_source!r}: "
                f"unsupported unary operator {op_type.__name__}"
            )
        operand = self.visit(node.operand)
        return _SAFE_UNARYOPS[op_type](operand)

    def visit_BoolOp(self, node):
        op_type = type(node.op)
        if op_type not in _SAFE_BINOPS:
            raise ParseError(
                f"in expression {self.expression_source!r}: "
                f"unsupported boolean operator {op_type.__name__}"
            )
        func = _SAFE_BINOPS[op_type]
        result = self.visit(node.values[0])
        for v in node.values[1:]:
            result = func(result, self.visit(v))
        return result

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            op_type = type(op)
            if op_type not in _SAFE_BINOPS:
                raise ParseError(
                    f"in expression {self.expression_source!r}: "
                    f"unsupported comparison {op_type.__name__}"
                )
            right = self.visit(comparator)
            if not _SAFE_BINOPS[op_type](left, right):
                return False
            left = right
        return True


def eval_expression(expr, context):
    if isinstance(expr, (int, float, bool)):
        return expr
    if not isinstance(expr, str):
        raise ParseError(f"expression must be a string or number, got {type(expr).__name__}")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ParseError(f"invalid expression {expr!r}: {e}") from e
    evaluator = _ExpressionEvaluator(context, expr)
    return evaluator.visit(tree)


def is_expression_string(value):
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    if any(op in stripped for op in "+-*/%&|^<>!=~()"):
        return True
    if " " in stripped and any(kw in stripped for kw in ("and", "or", "not")):
        return True
    return False
