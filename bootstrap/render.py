"""Template tree rendering and template self-validation.

No templating dependency (Jinja2 etc.) is used on purpose: the token
vocabulary is small and closed (see docs/TEMPLATE_MAINTENANCE.md), so a
flat regex substitution is sufficient and keeps the generated project's
own tooling free of any bootstrapper dependency.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .model import ProjectModel, token_map

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "template"

TOKEN_RE = re.compile(r"\{\{([A-Z_]+)\}\}")
KNOWN_TOKENS = {
    "SUITE_NAME",
    "ROOT_NAMESPACE",
    "ROOT_NAMESPACE_LOWER",
    "PLUGIN_GUID_ROOT",
    "AUTHOR",
    "THUNDERSTORE_NAMESPACE",
    "SUITE_VERSION",
    "JOTUNN_VERSION",
    "BEPINEX_VERSION",
    "NETFX_REF_VERSION",
    "CSHARP_LANG_VERSION",
    "MODULE_CATALOG_ROWS",
    "INCLUDED_MODULES_LIST",
    "COMPATIBILITY_BOUNDARIES_LIST",
}


class RenderError(RuntimeError):
    pass


OPTIONAL_DIR_FLAGS = {
    f"src{os.sep}__ROOT_NAMESPACE__.ServerCore": lambda m: m.server_core is not None,
    f"src{os.sep}__ROOT_NAMESPACE__.Client": lambda m: m.client is not None,
    f"src{os.sep}__ROOT_NAMESPACE__.Shared.Diagnostics": lambda m: m.shared_diagnostics is not None,
}


def _skip(rel_str: str, model: ProjectModel) -> bool:
    for prefix, present in OPTIONAL_DIR_FLAGS.items():
        if (rel_str == prefix or rel_str.startswith(prefix + os.sep)) and not present(model):
            return True
    return False


def _substitute(text: str, tokens: dict[str, str]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in tokens:
            raise RenderError(f"unknown template token {{{{{key}}}}}")
        return tokens[key]

    return TOKEN_RE.sub(repl, text)


def render_tree(model: ProjectModel, output_dir: Path) -> None:
    tokens = token_map(model)
    for src in sorted(TEMPLATE_DIR.rglob("*")):
        rel = src.relative_to(TEMPLATE_DIR)
        rel_str = str(rel)
        if _skip(rel_str, model):
            continue
        dest_rel = Path(*[part.replace("__ROOT_NAMESPACE__", model.params.root_namespace) for part in rel.parts])
        dest = output_dir / dest_rel
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = src.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            dest.write_bytes(data)
            continue
        dest.write_text(_substitute(text, tokens), encoding="utf-8", newline="\n")
        if src.suffix == ".sh":
            dest.chmod(0o755)


# --- template self-validation (backs scripts/validate-template.sh) ---

REQUIRED_TEMPLATE_PATHS = [
    "src/__ROOT_NAMESPACE__.Common",
    "src/__ROOT_NAMESPACE__.ServerCore",
    "src/__ROOT_NAMESPACE__.Client",
    "src/__ROOT_NAMESPACE__.Shared.Diagnostics",
    "tests/__ROOT_NAMESPACE__.Common.Tests",
    "tests/scaffold/test_scaffold.py",
    "scripts",
    "docs",
    ".context",
    ".omp",
    "packaging",
    "AGENTS.md",
    "README.md",
    "BOOTSTRAP_PROMPT.md",
    ".gitignore",
    ".editorconfig",
    "Directory.Build.props",
    "Directory.Packages.props",
    "DoPrebuild.props",
    "Environment.props.example",
    ".valheim/dev.json.example",
]

FORBIDDEN_TEMPLATE_PATHS = [
    "suite.config.json",
    "Environment.props",
    ".valheim/dev.json",
    "build/Suite.Generated.props",
    "packaging/profile-lock.json",
]

SECRET_NAME_PATTERN = re.compile(r"(?i)password|secret|credential|\.pfx$")
GAME_ASSET_PATTERN = re.compile(r"(?i)\.dll$|publicized_assemblies|assembly_valheim_publicized|MMHOOK_|unstripped_corlib")


def validate_template(template_dir: Path = TEMPLATE_DIR) -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_TEMPLATE_PATHS:
        if not (template_dir / rel).exists():
            errors.append(f"missing required template path: {rel}")
    for rel in FORBIDDEN_TEMPLATE_PATHS:
        if (template_dir / rel).exists():
            errors.append(f"template must not contain a generated/local artifact: {rel}")
    for f in template_dir.rglob("*"):
        if not f.is_file():
            continue
        if SECRET_NAME_PATTERN.search(f.name):
            errors.append(f"template file name looks like a secret: {f.relative_to(template_dir)}")
        if GAME_ASSET_PATTERN.search(str(f)):
            errors.append(f"template must not contain game/publicized assemblies: {f.relative_to(template_dir)}")
        if f.suffix == ".sh" and not os.access(f, os.X_OK):
            errors.append(f"template script is not executable: {f.relative_to(template_dir)}")
        try:
            text = f.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        for match in TOKEN_RE.finditer(text):
            if match.group(1) not in KNOWN_TOKENS:
                errors.append(f"unknown token {{{{{match.group(1)}}}}} in {f.relative_to(template_dir)}")
    return errors


if __name__ == "__main__":
    import sys

    errs = validate_template()
    if errs:
        for e in errs:
            print(f"template error: {e}", file=sys.stderr)
        sys.exit(2)
    print("template: structure valid, tokens known, no local secrets/game assets detected")
