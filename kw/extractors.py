"""Extra extractors registered into knoblog at runtime: function/keyword defaults in Python and JS/TS.

knoblog core reads constants; for library upgrades the knobs that bite are usually keyword defaults
(`def request(..., timeout=5.0)`), dataclass/class attributes and JS `defaults = { timeout: 0 }` objects.
"""
from __future__ import annotations

import ast
import re

from knoblog import extractors as KX

LITERAL_NODES = (ast.Constant, ast.Tuple, ast.List, ast.UnaryOp, ast.Dict, ast.Set)


def _lit(node) -> str | None:
    if not isinstance(node, LITERAL_NODES):
        return None
    try:
        ast.literal_eval(node)
    except Exception:
        return None
    s = ast.unparse(node)
    return s if len(s) <= 120 else None


def python_defaults(path: str, text: str) -> dict[str, dict]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    out: list[tuple[str, dict]] = []

    def visit(body, prefix: str):
        for n in body:
            if isinstance(n, ast.ClassDef) and not n.name.startswith("_"):
                visit(n.body, f"{prefix}{n.name}.")
                for st in n.body:  # class attributes / dataclass fields with literal defaults
                    tgt = st.target if isinstance(st, ast.AnnAssign) else (st.targets[0] if isinstance(st, ast.Assign) and len(st.targets) == 1 else None)
                    if isinstance(tgt, ast.Name) and not tgt.id.startswith("_") and getattr(st, "value", None) is not None:
                        v = _lit(st.value)
                        if v is not None:
                            out.append((f"{prefix}{n.name}.{tgt.id}", KX._rec(v)))
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not n.name.startswith("_") or n.name == "__init__"):
                a = n.args
                pos = a.posonlyargs + a.args
                pairs = list(zip(pos[len(pos) - len(a.defaults):], a.defaults)) + [(k, d) for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
                fname = prefix[:-1] if n.name == "__init__" and prefix else f"{prefix}{n.name}"
                for arg, d in pairs:
                    v = _lit(d)
                    if v is not None and not arg.arg.startswith("_"):
                        out.append((f"{fname}({arg.arg})", KX._rec(v)))
    visit(tree.body, "")
    return KX._dedupe(out)


_JS_LIT = r"""(-?\d[\d_.]*(?:e[-+]?\d+)?(?:\s*[*+]\s*\d[\d_.]*)*|true|false|null|undefined|'[^'\n]{0,80}'|"[^"\n]{0,80}"|`[^`$\n]{0,80}`|\[(?:\s*(?:'[^'\n]*'|"[^"\n]*"|-?\d[\d.]*|true|false)\s*,?)*\s*\])"""
_JS_CONST = re.compile(rf"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*[\w<>\[\]| ]+)?=\s*{_JS_LIT}\s*;?\s*(?://.*)?$")
_JS_OBJ_START = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)?\s*((?:[A-Za-z_$][\w$.]*)?(?:[Dd]efaults?|DEFAULTS?|[Cc]onfig|[Oo]ptions)\w*)\s*(?::[^=]+)?=\s*(?:Object\.freeze\()?\{\s*$")
_JS_KV = re.compile(rf"^\s*['\"]?([A-Za-z_$][\w$-]*)['\"]?\s*:\s*{_JS_LIT}\s*,?\s*(?://.*)?$")
_JS_NEST = re.compile(r"^\s*['\"]?([A-Za-z_$][\w$-]*)['\"]?\s*:\s*\{\s*$")


def js_defaults(path: str, text: str) -> dict[str, dict]:
    """`export const defaultConfig = Object.freeze({ a: 1, nested: { b: 'x' } })` -> defaultConfig.a, defaultConfig.nested.b."""
    out, stack, skip = [], [], 0
    for line in text.splitlines():
        code = re.sub(r"//.*$", "", line)
        if stack:
            if skip:  # inside a non-literal block (function body, array of objects...)
                skip += code.count("{") + code.count("[") - code.count("}") - code.count("]")
                continue
            m = _JS_NEST.match(code)
            if m:
                stack.append(m.group(1))
                continue
            m = _JS_KV.match(code)
            if m:
                out.append((".".join(stack + [m.group(1)]), KX._rec(m.group(2))))
                continue
            opened = code.count("{") + code.count("[") - code.count("}") - code.count("]")
            if opened > 0:
                skip = opened
                continue
            if re.match(r"^\s*[}\]]", code):
                stack.pop()
            continue
        m = _JS_OBJ_START.match(code)
        if m:
            stack = [m.group(1)]
            continue
        m = _JS_CONST.match(code)
        if m and (m.group(1).isupper() or re.search(r"default|timeout|max|min|limit|retr|size", m.group(1), re.I)):
            out.append((m.group(1), KX._rec(m.group(2))))
    return KX._dedupe(out)


_GO_LIT = r"(-?\d[\d_.]*(?:e[-+]?\d+)?(?:\s*\*\s*(?:time|units)\.\w+)?|true|false|\"[^\"\n]{0,80}\"|(?:[a-z]\w*\.)?[A-Z]\w*(?:\.\w+)?)"
_GO_ASSIGN = re.compile(rf"^\s*(\w+(?:\.\w+)+)\s*=\s*(?:(?:ptr|pointer|utilpointer|utilptr)\.(?:To|Int32|Int64|Bool|String|Float64)\w*(?:\[[\w.]+\])?\(|&)?{_GO_LIT}\)?\s*(?://.*)?$")
_GO_CONST = re.compile(rf"^\s*(?:const\s+)?(Default\w+|[A-Z]\w*(?:Timeout|Period|Interval|Limit|Max\w*|Min\w*|Size|Threshold|Seconds|Duration|QPS|Burst))\s*(?:[\w.]+\s*)?=\s*{_GO_LIT}\s*(?://.*)?$")


def go_defaults(path: str, text: str) -> dict[str, dict]:
    """Kubernetes-style SetDefaults_* assignments (`obj.Spec.Replicas = ptr.To[int32](1)`) and Default* constants."""
    out, fn = [], ""
    for line in text.splitlines():
        m = re.match(r"^func\s+(?:\([^)]*\)\s*)?(\w+)", line)
        if m:
            fn = re.sub(r"^SetDefaults_?", "", m.group(1))
            continue
        m = _GO_ASSIGN.match(line)
        if m and fn:
            field = m.group(1).split(".", 1)[1]
            out.append((f"{fn}.{field}", KX._rec(m.group(2))))
            continue
        m = _GO_CONST.match(line)
        if m:
            out.append((m.group(1), KX._rec(m.group(2))))
    return KX._dedupe(out)


def python_module_vars(path: str, text: str) -> dict[str, dict]:
    """Module-level `name = literal` / `name: T = literal`, plus `class X:` attributes (torch-style config.py files)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    out = []

    def walk(body, prefix):
        for st in body:
            if isinstance(st, ast.ClassDef):
                walk(st.body, f"{prefix}{st.name}.")
                continue
            tgt = st.target if isinstance(st, ast.AnnAssign) else (st.targets[0] if isinstance(st, ast.Assign) and len(st.targets) == 1 else None)
            val = getattr(st, "value", None)
            if isinstance(tgt, ast.Name) and val is not None and not tgt.id.startswith("__"):
                if isinstance(val, ast.Call) and val.args == [] and any(k.arg == "default" for k in val.keywords):
                    val = next(k.value for k in val.keywords if k.arg == "default")
                v = _lit(val)
                if v is not None:
                    out.append((f"{prefix}{tgt.id}", KX._rec(v)))
    walk(tree.body, "")
    return KX._dedupe(out)


def register() -> None:
    for name, fn in (("python_defaults", python_defaults), ("js_defaults", js_defaults), ("go_defaults", go_defaults), ("python_module_vars", python_module_vars)):
        KX.REGISTRY.setdefault(name, fn)
