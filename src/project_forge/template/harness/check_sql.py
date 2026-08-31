from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_WORDS = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WITH|COPY)\b", re.IGNORECASE)
SELECT_WORD = re.compile(r"\bSELECT\b", re.IGNORECASE)
POSITIONAL_PARAMETER = re.compile(r"(?<!%)%[sbt]")
NAMED_PARAMETER = re.compile(r"(?<!%)%\(([^)]*)\)([A-Za-z])")
QUOTED_NAMED_PARAMETER = re.compile(
    r"(?P<quote>['\"])%\((?P<name>[^)]*)\)[sbt](?P=quote)"
)
PARAMETER_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
MEANINGLESS_PARAMETER_NAME = re.compile(r"^(?:arg|p|param|value)\d+$")
NUMBERED_DOLLAR_PARAMETER = re.compile(r"\$\d+")
VARIABLE_IN_LIST = re.compile(r"\bIN\s*\(\s*%\(", re.IGNORECASE)
FORBIDDEN_TEXT = ("async" + "pg",)
SQL_CONSTRUCTORS = frozenset(
    {"SQL", "Identifier", "Literal", "Placeholder", "Composed"}
)
SQL_CALL_METHODS = frozenset(
    {"copy", "copy_rows", "execute", "execute_many", "executemany", "fetch_all", "fetch_one"}
)
SINGLE_ROW_METHODS = frozenset({"execute", "fetch_all", "fetch_one"})
BATCH_METHODS = frozenset({"execute_many", "executemany"})


def _parameter_name_problem(name: str) -> str | None:
    if not name:
        return "Psycopg placeholders must have a non-empty name"
    if not PARAMETER_NAME.fullmatch(name):
        return f"SQL parameter {name!r} must use lower_snake_case"
    if MEANINGLESS_PARAMETER_NAME.fullmatch(name):
        return f"SQL parameter {name!r} must have a descriptive name"
    return None


def _placeholder_name_expression(node: ast.Call) -> ast.expr | None:
    if node.args:
        return node.args[0]
    return next(
        (keyword.value for keyword in node.keywords if keyword.arg == "name"),
        None,
    )


def _name_targets(node: ast.Assign | ast.AnnAssign) -> list[tuple[str, ast.expr]]:
    if isinstance(node, ast.AnnAssign):
        return (
            [(node.target.id, node.value)]
            if isinstance(node.target, ast.Name) and node.value is not None
            else []
        )
    return [
        (target.id, node.value) for target in node.targets if isinstance(target, ast.Name)
    ]


@dataclass
class _SqlAliases:
    modules: set[str]
    psycopg_modules: set[str]
    constructors: dict[str, str]

    @classmethod
    def collect(cls, tree: ast.Module) -> _SqlAliases:
        aliases = cls(set(), set(), {})
        assignments: list[tuple[str, ast.expr]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for imported in node.names:
                    bound = imported.asname or imported.name.split(".")[0]
                    if imported.name == "psycopg.sql" and imported.asname:
                        aliases.modules.add(bound)
                    elif imported.name in {"psycopg", "psycopg.sql"}:
                        aliases.psycopg_modules.add(bound)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "psycopg":
                    for imported in node.names:
                        if imported.name == "sql":
                            aliases.modules.add(imported.asname or imported.name)
                elif node.module == "psycopg.sql":
                    for imported in node.names:
                        if imported.name in SQL_CONSTRUCTORS:
                            aliases.constructors[imported.asname or imported.name] = imported.name
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                assignments.extend(_name_targets(node))

        changed = True
        while changed:
            changed = False
            for target, value in assignments:
                if aliases.is_sql_module(value) and target not in aliases.modules:
                    aliases.modules.add(target)
                    changed = True
                constructor = aliases.constructor_name(value)
                if constructor is not None and aliases.constructors.get(target) != constructor:
                    aliases.constructors[target] = constructor
                    changed = True
        return aliases

    def is_sql_module(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.modules
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "sql"
            and isinstance(node.value, ast.Name)
            and node.value.id in self.psycopg_modules
        )

    def constructor_name(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return self.constructors.get(node.id)
        if (
            isinstance(node, ast.Attribute)
            and node.attr in SQL_CONSTRUCTORS
            and self.is_sql_module(node.value)
        ):
            return node.attr
        return None

    def call_constructor(self, node: ast.Call) -> str | None:
        return self.constructor_name(node.func)


@dataclass(frozen=True)
class _Binding:
    expression: ast.expr
    element: int | None
    scope: ast.AST


class _ScopeIndex(ast.NodeVisitor):
    def __init__(self, tree: ast.Module) -> None:
        self.module = tree
        self.current: ast.AST = tree
        self.parents: dict[ast.AST, ast.AST | None] = {tree: None}
        self.node_scopes: dict[ast.AST, ast.AST] = {}
        self.bound: dict[ast.AST, set[str]] = {tree: set()}
        self.bindings: dict[ast.AST, dict[str, list[_Binding]]] = {tree: {}}
        self.functions: dict[ast.AST, dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]] = {
            tree: {}
        }
        self.visit(tree)

    def generic_visit(self, node: ast.AST) -> None:
        self.node_scopes[node] = self.current
        super().generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        parent = self.current
        self.node_scopes[node] = parent
        self.bound[parent].add(node.name)
        self.functions[parent].setdefault(node.name, []).append(node)
        self.parents[node] = parent
        self.bound[node] = {
            argument.arg
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
        }
        if node.args.vararg is not None:
            self.bound[node].add(node.args.vararg.arg)
        if node.args.kwarg is not None:
            self.bound[node].add(node.args.kwarg.arg)
        self.bindings[node] = {}
        self.functions[node] = {}
        self.current = node
        for statement in node.body:
            self.visit(statement)
        self.current = parent

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _record(self, target: ast.expr, value: ast.expr, element: int | None = None) -> None:
        if isinstance(target, ast.Name):
            self.bound[self.current].add(target.id)
            self.bindings[self.current].setdefault(target.id, []).append(
                _Binding(value, element, self.current)
            )
            return
        if not isinstance(target, (ast.Tuple, ast.List)):
            return
        if isinstance(value, (ast.Tuple, ast.List)) and len(target.elts) == len(value.elts):
            for nested_target, nested_value in zip(target.elts, value.elts, strict=True):
                self._record(nested_target, nested_value)
            return
        for index, nested_target in enumerate(target.elts):
            self._record(nested_target, value, index)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.node_scopes[node] = self.current
        for target in node.targets:
            self._record(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.node_scopes[node] = self.current
        if node.value is not None:
            self._record(node.target, node.value)
        self.generic_visit(node)

    def scope_for(self, node: ast.AST) -> ast.AST:
        return self.node_scopes.get(node, self.module)

    def _scope_chain(self, scope: ast.AST) -> list[ast.AST]:
        result: list[ast.AST] = []
        current: ast.AST | None = scope
        while current is not None:
            result.append(current)
            current = self.parents.get(current)
        return result

    def find_bindings(self, name: str, scope: ast.AST) -> list[_Binding]:
        for candidate in self._scope_chain(scope):
            if name in self.bound[candidate]:
                return self.bindings[candidate].get(name, [])
        return []

    def find_functions(
        self, name: str, scope: ast.AST
    ) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
        for candidate in self._scope_chain(scope):
            found = self.functions[candidate].get(name)
            if found:
                return found
            if name in self.bound[candidate]:
                return []
        return []


class _ReturnCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.values: list[ast.expr] = []

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is not None:
            self.values.append(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        del node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        del node

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        del node


def _has_identifier_guard(scope: ast.AST, name: str) -> bool:
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for statement in scope.body:
        if not isinstance(statement, ast.If) or not isinstance(statement.test, ast.UnaryOp):
            continue
        call = statement.test.operand
        if (
            isinstance(statement.test.op, ast.Not)
            and isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "isidentifier"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == name
            and not call.args
            and not call.keywords
            and any(isinstance(child, ast.Raise) for child in statement.body)
        ):
            return True
    return False


def _constructor_arguments_are_static(
    node: ast.Call,
    constructor: str,
    scopes: _ScopeIndex,
) -> bool:
    values = [*node.args, *(keyword.value for keyword in node.keywords)]
    if not values or any(keyword.arg is None for keyword in node.keywords):
        return False
    if constructor == "Placeholder":
        name = _placeholder_name_expression(node)
        if name is None:
            return False
        name_is_safe = (
            isinstance(name, ast.Constant)
            and isinstance(name.value, str)
            and _parameter_name_problem(name.value) is None
        ) or (
            isinstance(name, ast.Name)
            and _has_identifier_guard(scopes.scope_for(node), name.id)
        )
        if not name_is_safe:
            return False
        format_values = [
            value
            for value in values
            if value is not name
        ]
        return all(
            isinstance(value, ast.Constant) and value.value in {"s", "b", "t"}
            for value in format_values
        )
    string_only = constructor != "Literal"
    if all(
        isinstance(value, ast.Constant)
        and (not string_only or isinstance(value.value, str))
        for value in values
    ):
        return True
    return False


def _trusted_migration_sql(path: Path, node: ast.expr, aliases: _SqlAliases) -> bool:
    if path.name != "migration_engine.py" or not isinstance(node, ast.Call):
        return False
    return (
        aliases.call_constructor(node) == "SQL"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == "up_sql"
        and isinstance(node.args[0].value, ast.Name)
        and node.args[0].value.id == "migration"
    )


@dataclass(frozen=True)
class _QueryShape:
    static_composable: bool = False
    select_anchor: bool = False
    raw_sql: bool = False


class _QueryAnalyzer:
    def __init__(self, aliases: _SqlAliases, scopes: _ScopeIndex) -> None:
        self.aliases = aliases
        self.scopes = scopes

    @staticmethod
    def _merge(shapes: list[_QueryShape]) -> _QueryShape:
        if not shapes:
            return _QueryShape()
        static = all(shape.static_composable for shape in shapes)
        all_safe = all(shape.static_composable or shape.select_anchor for shape in shapes)
        return _QueryShape(
            static_composable=static,
            select_anchor=all_safe and any(shape.select_anchor for shape in shapes),
            raw_sql=any(shape.raw_sql for shape in shapes),
        )

    def analyze(
        self,
        node: ast.expr,
        scope: ast.AST,
        seen: frozenset[tuple[int, int]] = frozenset(),
    ) -> _QueryShape:
        marker = (id(node), id(scope))
        if marker in seen:
            return _QueryShape()
        nested_seen = seen | {marker}

        if isinstance(node, ast.Call):
            constructor = self.aliases.call_constructor(node)
            if constructor is not None:
                static = _constructor_arguments_are_static(node, constructor, self.scopes)
                select = (
                    constructor == "SQL"
                    and static
                    and any(
                        isinstance(argument, ast.Constant)
                        and isinstance(argument.value, str)
                        and SELECT_WORD.search(argument.value)
                        for argument in node.args
                    )
                )
                return _QueryShape(static_composable=static, select_anchor=select)
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"format", "join"}:
                parts = [
                    self.analyze(node.func.value, scope, nested_seen),
                    *(self.analyze(argument, scope, nested_seen) for argument in node.args),
                    *(
                        self.analyze(keyword.value, scope, nested_seen)
                        for keyword in node.keywords
                    ),
                ]
                static = all(part.static_composable for part in parts)
                return _QueryShape(
                    static_composable=static,
                    select_anchor=any(part.select_anchor for part in parts),
                    raw_sql=any(part.raw_sql for part in parts),
                )
            return self._analyze_call_result(node, None, scope, nested_seen)

        if isinstance(node, ast.Name):
            shapes: list[_QueryShape] = []
            for binding in self.scopes.find_bindings(node.id, scope):
                if binding.element is None:
                    shapes.append(self.analyze(binding.expression, binding.scope, nested_seen))
                else:
                    shapes.append(
                        self._analyze_call_result(
                            binding.expression,
                            binding.element,
                            binding.scope,
                            nested_seen,
                        )
                    )
            return self._merge(shapes)

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.analyze(node.left, scope, nested_seen)
            right = self.analyze(node.right, scope, nested_seen)
            return _QueryShape(
                static_composable=left.static_composable and right.static_composable,
                select_anchor=left.select_anchor or right.select_anchor,
                raw_sql=left.raw_sql or right.raw_sql,
            )

        if isinstance(node, ast.IfExp):
            return self._merge(
                [
                    self.analyze(node.body, scope, nested_seen),
                    self.analyze(node.orelse, scope, nested_seen),
                ]
            )

        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return self._merge(
                [self.analyze(element, scope, nested_seen) for element in node.elts]
            )

        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
                return self._analyze_call_result(
                    node.value, node.slice.value, scope, nested_seen
                )
            return self._analyze_mapping_values(node.value, scope, nested_seen)

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return _QueryShape(raw_sql=SQL_WORDS.search(node.value) is not None)
        return _QueryShape()

    def _analyze_mapping_values(
        self,
        node: ast.expr,
        scope: ast.AST,
        seen: frozenset[tuple[int, int]],
    ) -> _QueryShape:
        if isinstance(node, ast.Dict):
            return self._merge(
                [self.analyze(value, scope, seen) for value in node.values]
            )
        if isinstance(node, ast.Name):
            shapes = [
                self._analyze_mapping_values(binding.expression, binding.scope, seen)
                for binding in self.scopes.find_bindings(node.id, scope)
            ]
            return self._merge(shapes)
        return _QueryShape()

    def _analyze_call_result(
        self,
        node: ast.expr,
        element: int | None,
        scope: ast.AST,
        seen: frozenset[tuple[int, int]],
    ) -> _QueryShape:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            return _QueryShape()
        shapes: list[_QueryShape] = []
        for function in self.scopes.find_functions(node.func.id, scope):
            collector = _ReturnCollector()
            for statement in function.body:
                collector.visit(statement)
            for value in collector.values:
                result = value
                if element is not None:
                    if not isinstance(value, (ast.Tuple, ast.List)) or element >= len(value.elts):
                        shapes.append(_QueryShape())
                        continue
                    result = value.elts[element]
                shapes.append(self.analyze(result, function, seen))
        return self._merge(shapes)


def _parameter_container_kind(
    node: ast.expr,
    scope: ast.AST,
    scopes: _ScopeIndex,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> str:
    marker = (id(node), id(scope))
    if marker in seen:
        return "unknown"
    nested_seen = seen | {marker}

    if isinstance(node, (ast.Dict, ast.DictComp)):
        return "mapping"
    if isinstance(node, (ast.List, ast.ListComp, ast.Set, ast.SetComp, ast.Tuple)):
        return "sequence"
    if isinstance(node, ast.Constant):
        return "none" if node.value is None else "scalar"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "dict":
            return "mapping"
        if node.func.id in {"list", "set", "tuple"}:
            return "sequence"
        kinds: set[str] = set()
        for function in scopes.find_functions(node.func.id, scope):
            collector = _ReturnCollector()
            for statement in function.body:
                collector.visit(statement)
            kinds.update(
                _parameter_container_kind(value, function, scopes, nested_seen)
                for value in collector.values
            )
        if len(kinds) == 1:
            return kinds.pop()
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _parameter_container_kind(node.left, scope, scopes, nested_seen)
        right = _parameter_container_kind(node.right, scope, scopes, nested_seen)
        return "mapping" if left == right == "mapping" else "unknown"
    if isinstance(node, ast.IfExp):
        body = _parameter_container_kind(node.body, scope, scopes, nested_seen)
        alternate = _parameter_container_kind(node.orelse, scope, scopes, nested_seen)
        return body if body == alternate else "unknown"
    if isinstance(node, ast.Name):
        kinds = {
            _parameter_binding_kind(binding, scopes, nested_seen)
            for binding in scopes.find_bindings(node.id, scope)
        }
        return kinds.pop() if len(kinds) == 1 else "unknown"
    return "unknown"


def _parameter_binding_kind(
    binding: _Binding,
    scopes: _ScopeIndex,
    seen: frozenset[tuple[int, int]],
) -> str:
    if binding.element is None:
        return _parameter_container_kind(
            binding.expression,
            binding.scope,
            scopes,
            seen,
        )
    if not isinstance(binding.expression, ast.Call) or not isinstance(
        binding.expression.func, ast.Name
    ):
        return "unknown"
    kinds: set[str] = set()
    for function in scopes.find_functions(binding.expression.func.id, binding.scope):
        collector = _ReturnCollector()
        for statement in function.body:
            collector.visit(statement)
        for value in collector.values:
            if not isinstance(value, (ast.Tuple, ast.List)):
                kinds.add("unknown")
                continue
            if binding.element >= len(value.elts):
                kinds.add("unknown")
                continue
            kinds.add(
                _parameter_container_kind(
                    value.elts[binding.element],
                    function,
                    scopes,
                    seen,
                )
            )
    return kinds.pop() if len(kinds) == 1 else "unknown"


def _annotation_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _annotation_is_mapping(node: ast.expr | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Subscript):
        return _annotation_name(node.value) in {"Mapping", "dict"}
    return _annotation_name(node) == "RepositoryParameters"


def _annotation_is_mapping_iterable(node: ast.expr | None) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    if _annotation_name(node.value) not in {
        "Generator",
        "Iterable",
        "Iterator",
        "Sequence",
        "list",
        "set",
        "tuple",
    }:
        return False
    element = node.slice
    if isinstance(element, ast.Tuple) and element.elts:
        element = element.elts[0]
    return _annotation_is_mapping(element)


def _argument_annotation(scope: ast.AST, name: str) -> ast.expr | None:
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    arguments = (*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs)
    return next(
        (argument.annotation for argument in arguments if argument.arg == name),
        None,
    )


def _batch_parameter_kind(
    node: ast.expr,
    scope: ast.AST,
    scopes: _ScopeIndex,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> str:
    marker = (id(node), id(scope))
    if marker in seen:
        return "unknown"
    nested_seen = seen | {marker}

    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        if not node.elts:
            return "mapping_iterable"
        element_kinds = {
            _parameter_container_kind(element, scope, scopes)
            for element in node.elts
        }
        if element_kinds == {"mapping"}:
            return "mapping_iterable"
        if element_kinds & {"scalar", "sequence"}:
            return "positional_iterable"
        return "unknown"
    if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        element_kind = _parameter_container_kind(node.elt, scope, scopes)
        if element_kind == "mapping":
            return "mapping_iterable"
        if element_kind in {"scalar", "sequence"}:
            return "positional_iterable"
        return "unknown"
    if isinstance(node, ast.Name):
        bindings = scopes.find_bindings(node.id, scope)
        kinds = {
            _batch_parameter_kind(
                binding.expression,
                binding.scope,
                scopes,
                nested_seen,
            )
            for binding in bindings
        }
        if len(kinds) == 1:
            return kinds.pop()
        if not bindings and _annotation_is_mapping_iterable(
            _argument_annotation(scope, node.id)
        ):
            return "mapping_iterable"
        return "unknown"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in {"list", "set", "tuple"} and node.args:
            return _batch_parameter_kind(node.args[0], scope, scopes, nested_seen)
        kinds = {
            "mapping_iterable"
            for function in scopes.find_functions(node.func.id, scope)
            if _annotation_is_mapping_iterable(function.returns)
        }
        return kinds.pop() if len(kinds) == 1 else "unknown"
    return "unknown"


def _call_argument(
    node: ast.Call,
    position: int,
    keyword_name: str | tuple[str, ...],
) -> ast.expr | None:
    if len(node.args) > position:
        return node.args[position]
    keyword_names = (
        {keyword_name} if isinstance(keyword_name, str) else set(keyword_name)
    )
    return next(
        (
            keyword.value
            for keyword in node.keywords
            if keyword.arg in keyword_names
        ),
        None,
    )


def _parent_index(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _inside_loop(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = parents.get(node)
    while current is not None:
        if isinstance(
            current,
            (
                ast.For,
                ast.AsyncFor,
                ast.comprehension,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            return True
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        current = parents.get(current)
    return False


def _trusted_repository_adapter_call(
    path: Path,
    node: ast.Call,
    method: str,
    scopes: _ScopeIndex,
) -> bool:
    if path.name != "repository_connection.py":
        return False
    scope = scopes.scope_for(node)
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    expected = {
        "copy_rows": "copy",
        "execute": "execute",
        "execute_many": "executemany",
        "fetch_all": "execute",
        "fetch_one": "execute",
    }
    query = _call_argument(node, 0, "query")
    return (
        expected.get(scope.name) == method
        and isinstance(query, ast.Name)
        and query.id == "query"
    )


def _scan_migration_module(
    path: Path,
    tree: ast.Module,
    problems: list[str],
) -> list[str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        up_sql = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "up_sql"),
            None,
        )
        if up_sql is not None and not (
            isinstance(up_sql, ast.Constant) and isinstance(up_sql.value, str)
        ):
            problems.append(
                f"{path}:{node.lineno}: migration up_sql must be one static string literal"
            )
    return problems


def scan(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems = [f"{path}: forbidden token {token!r}" for token in FORBIDDEN_TEXT if token in text]
    try:
        tree = ast.parse(text, filename=str(path), feature_version=(3, 11))
    except SyntaxError as error:
        location = f":{error.lineno}" if error.lineno is not None else ""
        problems.append(
            f"{path}{location}: Python source must be compatible with Python 3.11: "
            f"{error.msg}"
        )
        return problems
    path_text = path.as_posix()
    if "/db/migrations/" in path_text:
        _scan_migration_module(path, tree, problems)

    aliases = _SqlAliases.collect(tree)
    scopes = _ScopeIndex(tree)
    queries = _QueryAnalyzer(aliases, scopes)
    parents = _parent_index(tree)
    repository = path.parent.name == "repositories" or path.name == "repository.py"
    sql_boundary = repository or "/db/" in path_text

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and QUOTED_NAMED_PARAMETER.search(node.value)
        ):
            problems.append(
                f"{path}:{node.lineno}: SQL parameter placeholders must not be quoted"
            )

        if isinstance(node, ast.JoinedStr):
            literal = "".join(
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            if SQL_WORDS.search(literal):
                problems.append(f"{path}:{node.lineno}: SQL f-string is forbidden")

        if not isinstance(node, ast.Call):
            continue
        constructor = aliases.call_constructor(node)
        constructor_problem_reported = False
        if sql_boundary and constructor == "Literal":
            problems.append(
                f"{path}:{node.lineno}: psycopg.sql.Literal is forbidden; "
                "bind runtime values with named parameters"
            )
            constructor_problem_reported = True
        if sql_boundary and constructor == "Composed":
            problems.append(
                f"{path}:{node.lineno}: do not instantiate psycopg.sql.Composed directly; "
                "compose trusted objects with SQL.format, SQL.join, or +"
            )
            constructor_problem_reported = True
        if sql_boundary and constructor == "Placeholder":
            name = _placeholder_name_expression(node)
            if name is None:
                problems.append(
                    f"{path}:{node.lineno}: Psycopg Placeholder must have a name"
                )
                constructor_problem_reported = True
            elif isinstance(name, ast.Constant) and isinstance(name.value, str):
                name_problem = _parameter_name_problem(name.value)
                if name_problem is not None:
                    problems.append(f"{path}:{node.lineno}: {name_problem}")
                    constructor_problem_reported = True
        if (
            sql_boundary
            and constructor is not None
            and not _constructor_arguments_are_static(node, constructor, scopes)
            and not _trusted_migration_sql(path, node, aliases)
            and not constructor_problem_reported
        ):
            problems.append(
                f"{path}:{node.lineno}: psycopg.sql.{constructor} arguments "
                "must be static literals"
            )

        if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            receiver = queries.analyze(node.func.value, scopes.scope_for(node))
            if receiver.static_composable:
                replacements = [
                    *node.args,
                    *(keyword.value for keyword in node.keywords),
                ]
                if any(
                    not queries.analyze(
                        replacement,
                        scopes.scope_for(node),
                    ).static_composable
                    for replacement in replacements
                ):
                    problems.append(
                        f"{path}:{node.lineno}: psycopg.sql.SQL.format replacements "
                        "must be safe Composable objects; bind values by name"
                    )

        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and node.args
            and isinstance(node.args[0], (ast.List, ast.Tuple, ast.Set))
        ):
            receiver = queries.analyze(node.func.value, scopes.scope_for(node))
            joined = queries.analyze(node.args[0], scopes.scope_for(node))
            if receiver.static_composable and not joined.static_composable:
                problems.append(
                    f"{path}:{node.lineno}: psycopg.sql.SQL.join items must be "
                    "safe Composable objects"
                )

        if (
            not isinstance(node.func, ast.Attribute)
            or node.func.attr not in SQL_CALL_METHODS
        ):
            continue
        method = node.func.attr
        trusted_adapter = _trusted_repository_adapter_call(path, node, method, scopes)
        query = _call_argument(node, 0, "query")
        if query is not None and not trusted_adapter:
            shape = queries.analyze(query, scopes.scope_for(node))
            if shape.raw_sql:
                problems.append(
                    f"{path}:{node.lineno}: wrap executable SQL with psycopg.sql.SQL"
                )
            elif (
                sql_boundary
                and not isinstance(query, ast.Constant)
                and not shape.static_composable
                and not shape.select_anchor
                and not _trusted_migration_sql(path, query, aliases)
            ):
                problems.append(
                    f"{path}:{node.lineno}: dynamic execute must contain a literal SELECT anchor"
                )
        if method in SINGLE_ROW_METHODS:
            parameters = _call_argument(node, 1, ("parameters", "params"))
            if parameters is not None and _parameter_container_kind(
                parameters,
                scopes.scope_for(node),
                scopes,
            ) in {"scalar", "sequence"}:
                problems.append(
                    f"{path}:{node.lineno}: named Psycopg parameters require a mapping"
                )
        if method in BATCH_METHODS and not trusted_adapter:
            parameter_sets = _call_argument(
                node,
                1,
                ("parameter_sets", "params_seq"),
            )
            if parameter_sets is None or _batch_parameter_kind(
                parameter_sets,
                scopes.scope_for(node),
                scopes,
            ) != "mapping_iterable":
                problems.append(
                    f"{path}:{node.lineno}: execute_many requires an iterable of "
                    "named parameter mappings; positional batch rows are forbidden"
                )
        if repository and method in SINGLE_ROW_METHODS and _inside_loop(node, parents):
            problems.append(
                f"{path}:{node.lineno}: do not execute single-row SQL inside a loop; "
                "use set-based SQL, execute_many, or copy_rows"
            )
        if repository and method in SINGLE_ROW_METHODS:
            keywords = {keyword.arg for keyword in node.keywords}
            if "prepare" not in keywords:
                problems.append(
                    f"{path}:{node.lineno}: repository queries must choose prepare=True/False"
                )

    if POSITIONAL_PARAMETER.search(text):
        problems.append(
            f"{path}: use named Psycopg parameters instead of positional %s/%b/%t"
        )
    for match in NAMED_PARAMETER.finditer(text):
        name, conversion = match.groups()
        name_problem = _parameter_name_problem(name)
        if name_problem is not None:
            problems.append(f"{path}: {name_problem}")
        if conversion not in {"s", "b", "t"}:
            problems.append(
                f"{path}: SQL parameter {name!r} uses unsupported %{conversion} format"
            )
    if NUMBERED_DOLLAR_PARAMETER.search(text):
        problems.append(f"{path}: numbered dollar SQL parameters are forbidden")
    if VARIABLE_IN_LIST.search(text):
        problems.append(f"{path}: bind variable lists once with = ANY(array_parameter)")
    return problems


def main() -> int:
    backend = ROOT / "backend/src"
    if not backend.exists():
        return 0
    problems: list[str] = []
    for path in backend.rglob("*.py"):
        problems.extend(scan(path))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
