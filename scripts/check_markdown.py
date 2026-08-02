"""Find text that Streamlit will render as maths instead of as money.

Streamlit reads a `$...$` pair in markdown as LaTeX, so "$13,500 at step
4, $12,300 at step 10" renders as italic maths with both dollar signs
eaten. The page bodies are safe because every one of them goes through
`webdata.md`/`md_caption`/`md_info`, which escape. What those cannot
cover is text passed as an ARGUMENT -- `help=`, `caption=`, a widget
label -- which is where this bug has actually appeared twice.

So this walks the syntax tree of every module that imports streamlit and
reports literal strings, handed to a Streamlit call in a slot that
renders markdown, that contain two or more dollar signs. A single `$`
forms no pair and is fine: "TVL per bin ($)" renders as written.

It reads the source rather than the running app on purpose. A rendered
page only shows the strings that particular run happened to produce, and
the tooltip nobody opened is exactly the one that stays broken.

Runtime-built strings are checked only for the literal parts of an
f-string; a value interpolated at runtime cannot be judged from here.
Anything money-shaped that is built at runtime should go through
`webdata.hint` or `md` for that reason.

    python scripts/check_markdown.py
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Slots whose text Streamlit renders as markdown.
MARKDOWN_ARGS = {"help", "caption", "label", "placeholder", "text", "body"}

# Calls with a markdown-rendered first (or second) positional argument.
MARKDOWN_CALLS = {
    "markdown", "caption", "info", "warning", "error", "success", "metric",
    "image", "button", "number_input", "select_slider", "slider", "toast",
    "multiselect", "date_input", "expander", "subheader", "title", "header",
    "checkbox", "radio", "selectbox", "text_input", "download_button",
}

# webdata's own wrappers escape, so a literal handed to one is fine.
ESCAPING = {"md", "md_caption", "md_info", "hint", "escape"}


def literal(node):
    """The literal text of a node, or None if it is built at runtime."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):  # f-string: the literal parts only
        return "".join(part.value for part in node.values
                       if isinstance(part, ast.Constant)
                       and isinstance(part.value, str))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = literal(node.left), literal(node.right)
        if left is not None or right is not None:
            return (left or "") + (right or "")
    if isinstance(node, ast.Call):
        # help=hint("...") and friends are already escaped.
        name = getattr(node.func, "id", getattr(node.func, "attr", None))
        if name in ESCAPING:
            return None
    return None


def suspects(path):
    """Every markdown-rendered literal in this file with a $...$ pair."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) not in MARKDOWN_CALLS:
            continue
        slots = [(keyword.arg, keyword.value) for keyword in node.keywords
                 if keyword.arg in MARKDOWN_ARGS]
        slots += [(f"argument {i + 1}", arg)
                  for i, arg in enumerate(node.args[:2])]
        for slot, value in slots:
            text = literal(value)
            if text and text.count("$") >= 2:
                yield node.lineno, node.func.attr, slot, text


def main() -> int:
    found = 0
    for path in sorted(ROOT.glob("**/*.py")):
        if ".venv" in str(path) or "site-packages" in str(path):
            continue
        source = path.read_text(encoding="utf-8")
        if "streamlit" not in source:
            continue
        for line, call, slot, text in suspects(path):
            found += 1
            print(f"{path.relative_to(ROOT)}:{line}  st.{call}({slot})")
            print(f"    {text[:120]}")
    if found:
        print(f"\n{found} string(s) Streamlit will read as LaTeX. Wrap them "
              f"in webdata.hint() for a tooltip, or webdata.md() for body "
              f"text.")
    else:
        print("no markdown-rendered literal has a $...$ pair")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
