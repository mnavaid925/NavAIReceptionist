#!/usr/bin/env python
"""PostToolUse hook — auto-verify a single edited file (fast).

Triggered after Edit/Write/MultiEdit. It inspects the changed file path and:
  - apps/**.py or config/**.py  -> runs Django's `manage.py check`
  - consumers/**.py, consumers.py -> flags blocking (sync) calls made directly
    routing.py, webhooks.py,         inside an `async def` — the #1 realtime bug
    tasks.py, config/asgi.py
  - agent tool-declaration files -> checks every declared tool is a plain dict
                                    and has a dispatcher branch
  - templates/**.html           -> compiles the template + flags a multi-line {# #}
                                    comment (which renders as VISIBLE TEXT)

Exit 0  = clean, or the file isn't a Django source/template (no-op).
Exit 2  = a real problem; the message on stderr is fed back to Claude to fix.

The script is cwd-independent: it derives the project root from its own location
(.claude/hooks/on_edit.py -> project root), so it works no matter how it's invoked.
"""
import ast
import io
import json
import os
import re
import sys

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HOOK_DIR))  # .claude/hooks -> .claude -> project root

# Calls that block the event loop when awaited-less inside `async def`.
BLOCKING_RE = re.compile(
    r"(\.objects\.|\brequests\.|\bhttpx\.Client\b|\btime\.sleep\b|\.save\(|\bconnection\.)"
)
# Escape hatches that make a blocking call legal inside async code.
ASYNC_SAFE_RE = re.compile(r"(sync_to_async|database_sync_to_async|run_in_executor|\bawait\s)")


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def _blocking_in_async(src, rel):
    """Regex pass over the bodies of `async def` blocks. Cheap, no imports."""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"{rel}: syntax error on line {exc.lineno}: {exc.msg}"]
    lines = src.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        # Lines belonging to a nested *sync* def run off the loop — ignore them.
        skip = set()
        for sub in ast.walk(node):
            if sub is not node and isinstance(sub, ast.FunctionDef):
                end = getattr(sub, "end_lineno", sub.lineno)
                skip.update(range(sub.lineno, end + 1))
        end_lineno = getattr(node, "end_lineno", node.lineno)
        for i in range(node.lineno, min(end_lineno, len(lines)) + 1):
            if i in skip:
                continue
            line = lines[i - 1]
            code = line.split("#", 1)[0]
            if BLOCKING_RE.search(code) and not ASYNC_SAFE_RE.search(code):
                out.append(
                    f"{rel}:{i}: blocking call inside `async def {node.name}` -> "
                    f"{code.strip()[:90]!r}. This stalls the media-stream event loop for every "
                    "concurrent call. Wrap it in database_sync_to_async()/sync_to_async(), or use "
                    "the async ORM API (aget/acreate/asave)."
                )
                break
    return out


def _tool_parity(src, rel, path):
    """Declared LLM tools must be plain dicts AND have a dispatcher branch."""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"{rel}: syntax error on line {exc.lineno}: {exc.msg}"]
    declared = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if "name" not in keys or "description" not in keys:
            continue
        pairs = dict(zip(keys, node.values)) if len(keys) == len(node.values) else {}
        name_node = pairs.get("name")
        if not (isinstance(name_node, ast.Constant) and isinstance(name_node.value, str)):
            continue
        if "parameters" not in keys:
            out.append(
                f"{rel}:{node.lineno}: tool declaration {name_node.value!r} has no 'parameters' key. "
                "A declaration must be a provider-agnostic plain dict with name/description/parameters."
            )
            continue
        declared.append(name_node.value)
    if not declared:
        return out
    # A dispatcher branch may live in this file or a sibling in the same package.
    haystack = src
    try:
        folder = os.path.dirname(path)
        # Compare real paths, not raw strings: on Windows os.path.join yields '\' while
        # the hook payload carries '/', so a naive != would fail to exclude the edited
        # file, append it to the haystack twice and make the count check below a no-op.
        self_key = os.path.normcase(os.path.abspath(path))
        # Filter to .py BEFORE capping at 40: capping the raw listdir first means a folder
        # whose first 40 alphabetical entries are fixtures/JSON/__pycache__ never reaches
        # the module holding the dispatcher, producing a false "declared but undispatched"
        # that blocks the edit with exit 2.
        for fn in sorted(f for f in os.listdir(folder) if f.endswith(".py"))[:40]:
            sib_path = os.path.join(folder, fn)
            if os.path.normcase(os.path.abspath(sib_path)) == self_key:
                continue
            sib = _read(sib_path)
            if sib:
                haystack += "\n" + sib
    except Exception:
        pass
    for name in declared:
        if haystack.count(f'"{name}"') + haystack.count(f"'{name}'") < 2:
            out.append(
                f"{rel}: tool {name!r} is declared but no dispatcher branch handles it. "
                "A declared-but-undispatched tool fails silently mid-call — add the branch and "
                "return the {ok, data, error} envelope."
            )
    return out


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    fp = (payload.get("tool_input") or {}).get("file_path") or ""
    if not fp:
        return 0
    norm = fp.replace("\\", "/")
    # The segment tests below ("/apps/", "/config/", "/templates/") need a leading slash.
    # A relative file_path in the payload would otherwise make the WHOLE hook a silent
    # no-op — indistinguishable from the legitimate "not a Django file" exit 0.
    if not os.path.isabs(fp):
        norm = ROOT.replace("\\", "/").rstrip("/") + "/" + norm.lstrip("./")
    base = norm.rsplit("/", 1)[-1]
    is_py = norm.endswith(".py") and ("/apps/" in norm or "/config/" in norm)
    is_html = norm.endswith(".html") and "/templates/" in norm
    if not (is_py or is_html):
        return 0  # not a Django source/template — nothing to verify
    # `consumers/` may be a package or (per the backend-structure rule) still a flat
    # consumers.py at the app root; webhooks.py/tasks.py carry async work too.
    is_realtime = is_py and (
        "/consumers/" in norm
        or base in ("consumers.py", "routing.py", "asgi.py", "webhooks.py", "tasks.py")
    )
    is_tools = is_py and "tool" in base and ("/agent/" in norm or base.startswith("tools"))

    problems = []

    # AST passes first — they are stdlib-only and stay useful even if Django can't load.
    if is_realtime or is_tools:
        src = _read(fp)
        if src is not None:
            rel = norm.split("/apps/", 1)[-1] if "/apps/" in norm else base
            if is_realtime:
                problems.extend(_blocking_in_async(src, rel))
            if is_tools:
                problems.extend(_tool_parity(src, rel, fp))

    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        import django
        django.setup()
    except Exception as exc:  # never block on environment problems
        print(f"[auto-verify] django checks skipped ({exc.__class__.__name__}: {exc})")
        if not problems:
            return 0
        django = None

    if django is not None and is_py:
        from django.core.management import call_command
        from django.core.management.base import SystemCheckError
        buf = io.StringIO()
        try:
            call_command("check", stdout=buf, stderr=buf)
        except SystemCheckError:
            problems.append("manage.py check failed:\n" + buf.getvalue().strip())
        except Exception as exc:
            problems.append(f"manage.py check error: {exc}")

    if django is not None and is_html:
        rel = norm.rsplit("/templates/", 1)[1]
        from django.template import TemplateSyntaxError
        from django.template.loader import get_template
        try:
            get_template(rel)
        except TemplateSyntaxError as exc:
            problems.append(f"Template {rel}: syntax error: {exc}")
        except Exception:
            pass  # missing includes / unrelated load errors — don't block
        try:
            with open(fp, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    idx = line.find("{#")
                    if idx != -1 and "#}" not in line[idx:]:
                        problems.append(
                            f"Template {rel}:{i} opens a '{{#' comment with no closing '#}}' on the "
                            "same line. A multi-line {# #} comment renders as VISIBLE TEXT in the page "
                            "- use {% comment %}...{% endcomment %} instead."
                        )
                        break
        except Exception:
            pass

    if problems:
        sys.stderr.write(
            "AUTO-VERIFY failed after editing " + os.path.basename(fp) + ":\n- "
            + "\n- ".join(problems) + "\nPlease fix this before continuing.\n"
        )
        return 2

    print(f"[auto-verify] {os.path.basename(fp)}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
