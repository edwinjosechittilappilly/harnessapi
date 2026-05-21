from __future__ import annotations

import ast
import textwrap
import types

DEFAULT_IMPORT_BLOCKLIST = ["os", "subprocess", "socket", "sys", "importlib", "builtins"]
DEFAULT_CALL_BLOCKLIST = {"exec", "eval", "compile", "open", "__import__"}


def validate_handler_source(
    source: str,
    import_blocklist: list[str] | None = None,
    call_blocklist: set[str] | None = None,
) -> list[str]:
    """Static analysis of submitted handler source. Returns list of violations (empty = valid).

    Not a full sandbox — stops naive mistakes and obvious injection attempts.
    A future sandbox_executor hook can provide true process isolation.
    """
    if import_blocklist is None:
        import_blocklist = DEFAULT_IMPORT_BLOCKLIST
    if call_blocklist is None:
        call_blocklist = DEFAULT_CALL_BLOCKLIST

    violations: list[str] = []

    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError as exc:
        return [f"SyntaxError: {exc}"]

    blocked_modules = set(import_blocklist)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]
                    if module in blocked_modules:
                        violations.append(f"Blocked import: {alias.name!r}")
            else:
                module = (node.module or "").split(".")[0]
                if module in blocked_modules:
                    violations.append(f"Blocked import from: {node.module!r}")

        elif isinstance(node, ast.Call):
            func_name: str | None = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name and func_name in call_blocklist:
                violations.append(f"Blocked call: {func_name!r}")

    # Verify exactly one top-level async function named 'handle'
    top_level_fns = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and isinstance(n.col_offset, int) and n.col_offset == 0
    ]
    handle_fns = [f for f in top_level_fns if f.name == "handle"]
    if len(handle_fns) == 0:
        violations.append("Handler must define a top-level async function named 'handle'")
    elif len(handle_fns) > 1:
        violations.append("Handler must define exactly one 'handle' function")
    else:
        fn = handle_fns[0]
        args = fn.args
        positional = args.posonlyargs + args.args
        if len(positional) != 1:
            violations.append(
                f"'handle' must accept exactly one positional argument (input), got {len(positional)}"
            )

    return violations


def compile_variant_handler(
    source: str,
    skill_name: str,
    variant_id: str,
) -> object:
    """Compile and return the handle callable. Raises ValueError on failure."""
    dedented = textwrap.dedent(source)
    module = types.ModuleType(f"_variant_{skill_name}_{variant_id[:8]}")
    try:
        exec(compile(dedented, f"<variant:{skill_name}:{variant_id[:8]}>", "exec"), module.__dict__)
    except SyntaxError as exc:
        raise ValueError(f"SyntaxError in variant handler: {exc}") from exc
    handle_fn = getattr(module, "handle", None)
    if handle_fn is None:
        raise ValueError("Compiled source does not define a 'handle' function")
    return handle_fn
