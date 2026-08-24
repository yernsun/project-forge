from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_WORDS = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b", re.IGNORECASE)
SELECT_WORD = re.compile(r"\bSELECT\b", re.IGNORECASE)
POSITIONAL_PARAMETER = re.compile(r"(?<!%)%s")
NUMBERED_DOLLAR_PARAMETER = re.compile(r"\$\d+")
VARIABLE_IN_LIST = re.compile(r"\bIN\s*\(\s*%\(", re.IGNORECASE)
FORBIDDEN_TEXT = ("async" + "pg",)
SQL_CONSTRUCTORS = frozenset({"SQL", "Identifier", "Literal", "Placeholder"})


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
    string_only = constructor != "Literal"
    if all(
        isinstance(value, ast.Constant)
        and (not string_only or isinstance(value.value, str))
        for value in values
    ):
        return True
    return (
        constructor == "Placeholder"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Name)
        and _has_identifier_guard(scopes.scope_for(node), node.args[0].id)
    )


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

        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
        ):
            return self._analyze_call_result(
                node.value, node.slice.value, scope, nested_seen
            )

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return _QueryShape(raw_sql=SQL_WORDS.search(node.value) is not None)
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
        return problems

    aliases = _SqlAliases.collect(tree)
    scopes = _ScopeIndex(tree)
    queries = _QueryAnalyzer(aliases, scopes)
    repository = path.parent.name == "repositories" or path.name == "repository.py"
    sql_boundary = repository or "/db/" in path_text

    for node in ast.walk(tree):
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
        if (
            sql_boundary
            and constructor is not None
            and not _constructor_arguments_are_static(node, constructor, scopes)
            and not _trusted_migration_sql(path, node, aliases)
        ):
            problems.append(
                f"{path}:{node.lineno}: psycopg.sql.{constructor} arguments "
                "must be static literals"
            )

        if not isinstance(node.func, ast.Attribute) or node.func.attr != "execute":
            continue
        if node.args:
            query = node.args[0]
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
        if repository:
            keywords = {keyword.arg for keyword in node.keywords}
            if "prepare" not in keywords:
                problems.append(
                    f"{path}:{node.lineno}: repository queries must choose prepare=True/False"
                )

    if POSITIONAL_PARAMETER.search(text):
        problems.append(f"{path}: use named Psycopg parameters instead of positional %s")
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
