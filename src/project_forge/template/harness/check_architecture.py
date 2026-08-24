from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "backend/src/app"
SQL_COMPOSITION_TYPES = frozenset({"Identifier", "Literal", "Placeholder", "SQL"})


def _current_package(path: Path) -> tuple[str, ...]:
    relative = path.relative_to(APP_ROOT)
    return ("app", *relative.parts[:-1])


def _resolve_from_module(node: ast.ImportFrom, path: Path) -> str:
    if node.level == 0:
        return node.module or ""
    package = _current_package(path)
    keep = max(0, len(package) - (node.level - 1))
    parts = (*package[:keep], *((node.module or "").split(".") if node.module else ()))
    return ".".join(part for part in parts if part)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _canonical_name(node: ast.AST, bindings: dict[str, str]) -> str | None:
    dotted = _dotted_name(node)
    if not dotted:
        return None
    first, separator, remainder = dotted.partition(".")
    canonical = bindings.get(first, first)
    return f"{canonical}.{remainder}" if separator else canonical


def _binding_priority(canonical: str) -> int:
    roots = ("app", "fastapi", "psycopg")
    return int(any(canonical == root or canonical.startswith(f"{root}.") for root in roots))


def _target_names(node: ast.AST | None) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {name for element in node.elts for name in _target_names(element)}
    return set()


def _import_facts(tree: ast.AST, path: Path) -> tuple[set[str], dict[str, str]]:
    modules: set[str] = set()
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
                bound = alias.asname or alias.name.split(".", maxsplit=1)[0]
                bindings[bound] = alias.name if alias.asname else bound
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_from_module(node, path)
            if module:
                modules.add(module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                imported = f"{module}.{alias.name}" if module else alias.name
                bindings[alias.asname or alias.name] = imported
                if node.module is None:
                    modules.add(imported)

    # Follow simple aliases such as `Constructor = pg_sql.SQL`. This keeps the guard effective
    # without trying to become a full Python data-flow engine.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            value: ast.AST | None = None
            targets: set[str] = set()
            if isinstance(node, ast.Assign):
                value = node.value
                targets = {name for target in node.targets for name in _target_names(target)}
            elif isinstance(node, ast.AnnAssign):
                value = node.value
                targets = _target_names(node.target)
            if value is None:
                continue
            canonical = _canonical_name(value, bindings)
            if canonical is None:
                continue
            for target in targets:
                current = bindings.get(target)
                if current is None or _binding_priority(canonical) > _binding_priority(current):
                    bindings[target] = canonical
                    changed = True
    return modules, bindings


def _module_matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _is_app_repository_module(module: str) -> bool:
    if not _module_matches(module, "app"):
        return False
    return any(part in {"repository", "repositories"} for part in module.split(".")[1:])


def _module_candidates(modules: set[str], bindings: dict[str, str]) -> set[str]:
    return modules | set(bindings.values())


def is_service(path: Path) -> bool:
    return path.parent.name == "services" or path.name == "service.py"


def is_api(path: Path) -> bool:
    return path.parent.name == "api" or path.name == "api.py"


def is_repository(path: Path) -> bool:
    return path.parent.name == "repositories" or path.name == "repository.py"


def _is_sql_composition_call(node: ast.Call, bindings: dict[str, str]) -> bool:
    canonical = _canonical_name(node.func, bindings)
    if canonical is None:
        return False
    return canonical in {f"psycopg.sql.{name}" for name in SQL_COMPOSITION_TYPES}


def _annotation_is_factory_dep(annotation: ast.AST | None, bindings: dict[str, str]) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return "UnitOfWorkFactoryDep" in annotation.value
    for node in ast.walk(annotation):
        canonical = _canonical_name(node, bindings)
        if canonical and canonical.rsplit(".", maxsplit=1)[-1] == "UnitOfWorkFactoryDep":
            return True
    return False


def _factory_parameter_names(tree: ast.AST, bindings: dict[str, str]) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        names.update(
            argument.arg
            for argument in arguments
            if _annotation_is_factory_dep(argument.annotation, bindings)
        )
    return names


def _propagate_name_aliases(tree: ast.AST, names: set[str]) -> set[str]:
    result = set(names)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            value: ast.AST | None = None
            targets: set[str] = set()
            if isinstance(node, ast.Assign):
                value = node.value
                targets = {name for target in node.targets for name in _target_names(target)}
            elif isinstance(node, ast.AnnAssign):
                value = node.value
                targets = _target_names(node.target)
            if isinstance(value, ast.Name) and value.id in result:
                before = len(result)
                result.update(targets)
                changed = changed or len(result) != before
    return result


def _root_name(node: ast.AST) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _is_factory_call(node: ast.Call, factory_names: set[str]) -> bool:
    root = _root_name(node.func)
    return root in factory_names if root else False


def _contains_factory_call(node: ast.AST, factory_names: set[str]) -> bool:
    return any(
        isinstance(candidate, ast.Call) and _is_factory_call(candidate, factory_names)
        for candidate in ast.walk(node)
    )


def _api_boundary_problems(
    path: Path, tree: ast.AST, bindings: dict[str, str]
) -> list[str]:
    problems: list[str] = []
    factory_names = _propagate_name_aliases(tree, _factory_parameter_names(tree, bindings))
    factory_results: set[str] = set()
    unit_of_work_names: set[str] = set()

    for node in ast.walk(tree):
        value: ast.AST | None = None
        targets: set[str] = set()
        if isinstance(node, ast.Assign):
            value = node.value
            targets = {name for target in node.targets for name in _target_names(target)}
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            targets = _target_names(node.target)
        if value is not None and _contains_factory_call(value, factory_names):
            factory_results.update(targets)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_factory_call(node, factory_names):
            problems.append(
                f"{path}:{node.lineno}: API cannot call UnitOfWorkFactoryDep directly; "
                "pass it to a service"
            )
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                context_root = _root_name(item.context_expr)
                direct_entry = _contains_factory_call(item.context_expr, factory_names)
                indirect_entry = context_root in factory_names | factory_results
                if direct_entry or indirect_entry:
                    problems.append(
                        f"{path}:{node.lineno}: API cannot enter a unit of work directly"
                    )
                    unit_of_work_names.update(_target_names(item.optional_vars))

    # A direct `uow = await factory().__aenter__()` is also a forbidden unit-of-work handle.
    unit_of_work_names.update(factory_results)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in unit_of_work_names
            and not node.attr.startswith("__")
        ):
            problems.append(
                f"{path}:{node.lineno}: API cannot access repositories through a unit of work"
            )
    return problems


def scan(path: Path) -> list[str]:
    try:
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
            feature_version=(3, 11),
        )
    except SyntaxError as error:
        location = f":{error.lineno}" if error.lineno is not None else ""
        return [
            f"{path}{location}: Python source must be compatible with Python 3.11: "
            f"{error.msg}"
        ]
    modules, bindings = _import_facts(tree, path)
    candidates = _module_candidates(modules, bindings)
    problems: list[str] = []
    relative = path.relative_to(APP_ROOT)

    if relative.parts[0] == "domain":
        for module in sorted(candidates):
            forbidden = any(
                _module_matches(module, prefix)
                for prefix in ("fastapi", "psycopg", "app.api", "app.db", "app.services", "app.uow")
            ) or _is_app_repository_module(module)
            if forbidden:
                problems.append(f"{path}: domain cannot import {module}")

    if is_api(path):
        dependency_adapter = relative.parts == ("api", "dependencies.py")
        for module in sorted(candidates):
            forbidden = any(
                _module_matches(module, prefix)
                for prefix in ("psycopg", "app.db")
            ) or (
                _module_matches(module, "app.uow") and not dependency_adapter
            ) or _is_app_repository_module(module)
            if forbidden:
                problems.append(f"{path}: API cannot import infrastructure module {module}")
        problems.extend(_api_boundary_problems(path, tree, bindings))

    if is_service(path):
        for module in sorted(candidates):
            forbidden = any(
                _module_matches(module, prefix)
                for prefix in ("fastapi", "psycopg", "app.api")
            ) or _is_app_repository_module(module)
            if forbidden:
                problems.append(f"{path}: service cannot import {module}")

    if is_repository(path):
        for module in sorted(candidates):
            if any(
                _module_matches(module, prefix)
                for prefix in ("fastapi", "app.api", "app.services")
            ):
                problems.append(f"{path}: repository cannot import {module}")

    persistence_allowed = is_repository(path) or relative.parts[0] == "db"
    if not persistence_allowed:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"execute", "executemany"}
            ):
                problems.append(
                    f"{path}:{node.lineno}: SQL execution belongs in a repository or db adapter"
                )
            if isinstance(node, ast.Call) and _is_sql_composition_call(node, bindings):
                problems.append(
                    f"{path}:{node.lineno}: SQL composition belongs in a repository or db adapter"
                )

    return problems


def main() -> int:
    if not APP_ROOT.exists():
        return 0
    problems: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        problems.extend(scan(path))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
