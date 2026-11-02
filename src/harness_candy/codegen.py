"""Generacion de esqueletos de proyecto (v3 §5.1 adk init / plantillas).

``scaffold_project(dir, name, author)`` crea un repo Python minimo y
funcional: pyproject.toml, paquete src, test smoke, CI de GitHub, README y
LICENSE (MIT). Usa el motor de plantillas propio (templates.py).

``scaffold_agent(dir, name, model)`` anade un agente al catalogo
(agents.json) del proyecto generado.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .templates import render_string

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

PYPROJECT_TMPL = """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{{ name }}"
version = "0.1.0"
description = "{{ description }}"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
{{ name_dash }} = "{{ pkg }}.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
"""

README_TMPL = """# {{ name }}

{{ description }}

## Uso

```bash
pip install -e .
python -m unittest discover -s tests -v
```

## Licencia

MIT (ver LICENSE).
"""

INIT_TMPL = '''"""{{ name }}."""
__version__ = "0.1.0"
'''

CLI_TMPL = '''"""CLI minima del proyecto {{ name }}."""
import argparse


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="{{ name_dash }}")
    p.add_argument("--version", action="store_true")
    args = p.parse_args(argv)
    if args.version:
        from . import __version__

        print(__version__)
        return 0
    print("hola desde {{ name }}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

SMOKE_TEST_TMPL = '''"""Test smoke del paquete."""
import unittest

import {{ pkg }}


class TestSmoke(unittest.TestCase):
    def test_version(self):
        self.assertTrue({{ pkg }}.__version__)


if __name__ == "__main__":
    unittest.main()
'''

CI_TMPL = """name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install -e .
      - run: python -m unittest discover -s tests -v
"""

LICENSE_MIT = """MIT License

Copyright (c) 2026 {{ author }}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

AGENTS_JSON_TMPL = {
    "agents": [
        {
            "name": "XEV",
            "model": "{{ model }}",
            "roles": ["xev"],
            "system_prompt": "Eres un agente ejecutor.",
            "guardrails": ["json_strict"],
        }
    ]
}


def _pkg_name(name: str) -> str:
    return name.replace("-", "_")


def scaffold_project(
    directory: str | Path,
    name: str,
    *,
    author: str = "AAA1234fdja",
    description: str = "Proyecto generado con harness-candy codegen",
    model: str = "modelo-ligero",
) -> dict[str, Path]:
    """Crea el esqueleto; devuelve {nombre_archivo: ruta}."""
    if not _NAME_RE.fullmatch(name.replace("-", "_")):
        raise ValueError(f"nombre de proyecto invalido: {name!r} (use [a-z0-9-])")
    root = Path(directory)
    pkg = _pkg_name(name)
    ctx = {"name": name, "name_dash": name, "pkg": pkg, "author": author, "description": description, "model": model}
    archivos: dict[str, Path] = {}

    def escribir(rel: str, contenido: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido, encoding="utf-8")
        archivos[rel] = p

    escribir("pyproject.toml", render_string(PYPROJECT_TMPL, **ctx))
    escribir("README.md", render_string(README_TMPL, **ctx))
    escribir(f"src/{pkg}/__init__.py", render_string(INIT_TMPL, **ctx))
    escribir(f"src/{pkg}/cli.py", render_string(CLI_TMPL, **ctx))
    escribir(f"src/{pkg}/__main__.py", '"""python -m {{ pkg }}"""\nfrom .cli import main\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'.replace("{{ pkg }}", pkg))
    escribir("tests/test_smoke.py", render_string(SMOKE_TEST_TMPL, **ctx))
    escribir(".github/workflows/ci.yml", CI_TMPL)
    escribir("LICENSE", render_string(LICENSE_MIT, **ctx))
    escribir(".gitignore", "__pycache__/\n*.pyc\n.venv/\nbuild/\ndist/\n*.egg-info/\n")
    agents = json.loads(render_string(json.dumps(AGENTS_JSON_TMPL), **ctx))
    escribir("agents.json", json.dumps(agents, ensure_ascii=False, indent=2) + "\n")
    return archivos


def scaffold_agent(directory: str | Path, name: str, *, model: str = "modelo-ligero", roles: list[str] | None = None) -> dict:
    """Anade un agente al agents.json existente (o lo crea)."""
    p = Path(directory) / "agents.json"
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        data = {"agents": []}
    entrada = {
        "name": name,
        "model": model,
        "roles": roles or [name.lower()],
        "system_prompt": f"Eres {name}, agente del sistema.",
        "guardrails": ["json_strict"],
    }
    if any(a["name"] == name for a in data["agents"]):
        raise ValueError(f"ya existe un agente llamado {name!r}")
    data["agents"].append(entrada)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entrada
