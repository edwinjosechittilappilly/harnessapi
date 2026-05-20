from __future__ import annotations

import ast
import importlib.util
import json
import tomllib
import types
from pathlib import Path
from typing import Iterator

from .models import SkillInput, SkillOutput
from .skill import Skill, SkillMeta


class SkillsDirectoryProvider:
    """Scans a directory tree and yields a Skill for each valid skill folder."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def discover(self) -> Iterator[Skill]:
        for folder in sorted(self.root.iterdir()):
            if folder.is_dir() and not folder.name.startswith("_"):
                skill = self._load_skill(folder)
                if skill is not None:
                    yield skill

    # ------------------------------------------------------------------
    def _load_skill(self, folder: Path) -> Skill | None:
        handler_path = folder / "handler.py"
        models_path = folder / "models.py"
        if not handler_path.exists() or not models_path.exists():
            return None

        meta = self._load_meta(folder)
        pkg = self._make_package(folder)
        models_mod = self._load_module(models_path, f"{pkg.__name__}.models", pkg)
        handler_mod = self._load_module(handler_path, f"{pkg.__name__}.handler", pkg)

        input_model = getattr(models_mod, "Input", None)
        output_model = getattr(models_mod, "Output", None)
        if input_model is None or output_model is None:
            raise TypeError(
                f"Skill '{folder.name}': models.py must define Input and Output classes"
            )
        if not issubclass(input_model, SkillInput):
            raise TypeError(
                f"Skill '{folder.name}': Input must subclass SkillInput"
            )
        if not issubclass(output_model, SkillOutput):
            raise TypeError(
                f"Skill '{folder.name}': Output must subclass SkillOutput"
            )

        handle_fn = getattr(handler_mod, "handle", None)
        if handle_fn is None:
            raise TypeError(
                f"Skill '{folder.name}': handler.py must define a 'handle' function"
            )

        return Skill(
            meta=meta,
            input_model=input_model,
            output_model=output_model,
            handler=handle_fn,
            edit_handler=self._load_edit_handler(folder, pkg),
            folder=folder,
            examples=self._load_examples(folder),
            defaults=self._load_defaults(folder),
        )

    @staticmethod
    def _make_package(folder: Path) -> types.ModuleType:
        """Create a synthetic package namespace for a skill folder."""
        import sys
        pkg_name = f"_harnessapi_skill_{folder.name}"
        if pkg_name in sys.modules:
            return sys.modules[pkg_name]
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(folder)]  # type: ignore[assignment]
        pkg.__package__ = pkg_name
        pkg.__spec__ = None  # type: ignore[assignment]
        sys.modules[pkg_name] = pkg
        return pkg

    def _load_meta(self, folder: Path) -> SkillMeta:
        toml_path = folder / "skill.toml"
        data: dict = {}
        if toml_path.exists():
            with toml_path.open("rb") as f:
                raw = tomllib.load(f)
            data = raw.get("skill", {})
        handler_path = folder / "handler.py"
        description = data.get("description") or _extract_docstring(handler_path) or ""
        return SkillMeta(
            name=data.get("name", folder.name),
            description=description,
            is_mcp=data.get("is_mcp", True),
            tags=data.get("tags", []),
            timeout_secs=data.get("timeout_secs", 30.0),
        )

    @staticmethod
    def _load_module(
        path: Path, module_name: str, package: types.ModuleType | None = None
    ) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(
            module_name,
            path,
            submodule_search_locations=[],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {path}")
        module = importlib.util.module_from_spec(spec)
        if package is not None:
            module.__package__ = package.__name__
        import sys
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    def _load_edit_handler(self, folder: Path, pkg: types.ModuleType | None = None):
        edit_path = folder / "edit" / "handler.py"
        if not edit_path.exists():
            return None
        mod = self._load_module(edit_path, f"_skill_{folder.name}_edit", pkg)
        return getattr(mod, "handle", None)

    @staticmethod
    def _load_examples(folder: Path) -> list[dict]:
        examples_dir = folder / "examples"
        if not examples_dir.exists():
            return []
        return [
            json.loads(f.read_text())
            for f in sorted(examples_dir.glob("*.json"))
        ]

    @staticmethod
    def _load_defaults(folder: Path) -> dict | None:
        p = folder / "defaults" / "input.json"
        return json.loads(p.read_text()) if p.exists() else None


def _extract_docstring(path: Path) -> str | None:
    try:
        tree = ast.parse(path.read_text())
        return ast.get_docstring(tree)
    except Exception:
        return None
