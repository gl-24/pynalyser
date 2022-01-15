import ast
from collections import defaultdict
from typing import (Any, Collection, Iterator, List, NamedTuple, Optional,
                    Tuple, Union)

from .classes import (ACR, Block, CodeBlock, FlowContainer, Module, Scope,
                      ScopeReference)

### Dumping


class Context(NamedTuple):
    annotate_fields: bool
    include_attributes: bool
    indent: Optional[str]


def dump(
        obj: Union[ACR, ast.AST], annotate_fields: bool = True,
        include_attributes: bool = False, *,
        indent: Optional[Union[str, int]] = None) -> str:
    if not isinstance(obj, (ACR, ast.AST, list, dict)):
        raise TypeError(  # XXX: should we force it?
            f"expected one of the AST / ACR / list / dict, "
            "got {type(obj).__name__}")
    if indent is not None and not isinstance(indent, str):
        indent = " " * indent
    return _format(
        obj, Context(annotate_fields, include_attributes, indent), lvl=0)[0]


def _format(obj: Any, ctx: Context, lvl: int) -> Tuple[str, bool]:
    if ctx.indent is not None:
        lvl += 1
        prefix = "\n" + ctx.indent * lvl
        sep = ",\n" + ctx.indent * lvl
    else:
        prefix = ""
        sep = ", "

    if isinstance(obj, list):
        args = []
        allsimple = True

        for item in obj:
            value, simple = _format(item, ctx, lvl)
            allsimple = allsimple and simple
            args.append(value)

        value, allsimple = _format_args_with_allsimple(
            prefix, sep, args, allsimple)

        value = f"[{value}]"
        if type(obj) is not list:
            value = f"{type(obj).__name__}({value})"
        return value, allsimple

    if isinstance(obj, dict):
        args = []
        allsimple = True

        for key, value in obj.items():
            # dict key should be "simple"
            value, simple = _format(value, ctx, lvl)
            allsimple = allsimple and simple
            args.append(f"{key!r}: {value}")

        value, allsimple = _format_args_with_allsimple(
            prefix, sep, args, allsimple)

        value = f"{{{value}}}"
        if isinstance(obj, defaultdict):
            value = f"{type(obj).__name__}({obj.default_factory}, {value})"
        elif type(obj) is not dict:
            value = f"{type(obj).__name__}({value})"

        return value, allsimple

    if isinstance(obj, (ACR, ast.AST)):
        value, allsimple = _format_args_with_allsimple(
            prefix, sep, *_format_ast_or_acr(obj, ctx, lvl))
        return f"{type(obj).__name__}({value})", allsimple

    return repr(obj), True


def _format_args_with_allsimple(prefix: str, sep: str, args: Collection[str],
                                allsimple: bool) -> Tuple[str, bool]:
    if allsimple and len(args) <= 3:
        return ", ".join(args), not args
    return prefix + sep.join(args), False


def _format_attr(inst: Any, name: str, ctx: Context,
                 lvl: int) -> Tuple[str, bool]:
    return _format(
        getattr(inst, name, "<Is not an attribute of the object>"), ctx, lvl)


def _format_ast_or_acr(obj: Union[ast.AST, ACR], ctx: Context,
                       lvl: int) -> Tuple[List[str], bool]:
    args = []
    allsimple = True

    for name in obj._fields:
        value, simple = _format_attr(obj, name, ctx, lvl)
        allsimple = allsimple and simple
        if ctx.annotate_fields:
            args.append(f"{name}={value}")
        else:
            args.append(value)

    if ctx.include_attributes and obj._attributes:
        for name in obj._attributes:
            value, simple = _format_attr(obj, name, ctx, lvl)
            allsimple = allsimple and simple
            args.append(f"{name}={value}")

    return args, allsimple


### Tree traversing


NODE = Union[ACR, ast.AST]


def do_nothing(*args, **kwargs):
    pass


class NodeVisitor(ast.NodeVisitor):
    scope: Scope
    block: Block
    strict: bool = False

    def start(self, module: Module) -> None:
        self.scope = self.block = module

        self.visit(module)

        del self.scope, self.block

    def visit(self, node: NODE) -> Any:
        method = 'visit_' + type(node).__name__
        visitor = getattr(self, method, None)

        if visitor is None:
            if self.strict:
                raise ValueError(
                    f"There are no '{method}' method. "
                    "You see this message because you're in strict mode. "
                    f"See {type(self).__name__}.strict")

            visitor = do_nothing

        # handle acr
        if isinstance(node, Scope):
            result = visitor(node)

            previous_scope = self.scope
            self.scope = node

            previous_block = self.block
            self.block = node

            self.generic_visit(node)

            self.scope = previous_scope
            self.block = previous_block
        elif isinstance(node, Block):
            result = visitor(node)

            previous_block = self.block
            self.block = node

            self.generic_visit(node)

            self.block = previous_block
        else:
            result = visitor(node)

            self.generic_visit(node)

        return result

    def generic_visit(self, node: NODE) -> Any:
        if isinstance(node, ScopeReference):
            self.visit(node.get_scope(self.scope))

        if isinstance(node, ast.AST):
            return super().generic_visit(node)

        assert isinstance(node, Block)
        for name in node._block_fields:
            container: FlowContainer = getattr(node, name)
            for item in container:
                if isinstance(item, CodeBlock):
                    for code in item:
                        self.visit(code)
                elif isinstance(item, Block):
                    self.visit(item)
                elif isinstance(item, (ast.Return, ast.Raise, ast.Assert,
                                       ast.Break, ast.Continue)):
                    self.visit(item)
                else:
                    raise RuntimeError(
                        "Unreachable: item in flow container that's not "
                        "CodeBlock, Block, Return, Raise, Assert, "
                        f"Break, Continue, but {type(item).__name__}")

