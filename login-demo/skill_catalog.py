"""Read-only catalog of the repository's B2B skill instruction files."""

import re
from pathlib import Path

import yaml

_SAFE_ID = re.compile(r"^b2b-[a-z0-9][a-z0-9-]{0,100}$")


class SkillCatalog:
    def __init__(self, root: Path | None):
        self.root = Path(root) if root is not None else None
        self._skills: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if self.root is None or not self.root.is_dir():
            return
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or not _SAFE_ID.fullmatch(directory.name):
                continue
            path = directory / "SKILL.md"
            if not path.is_file():
                continue
            try:
                raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
                if not raw.startswith("---\n"):
                    continue
                boundary = raw.find("\n---\n", 4)
                if boundary < 0:
                    continue
                metadata = yaml.safe_load(raw[4:boundary])
                body = raw[boundary + 5:].strip()
            except (OSError, UnicodeError, yaml.YAMLError):
                continue
            if not isinstance(metadata, dict) or metadata.get("name") != directory.name:
                continue
            description = str(metadata.get("description") or "").strip()
            if not description:
                continue
            instruction = str(metadata.get("injection_prompt") or body).strip()[:16000]
            display_name = description.split("—", 1)[0].strip() or directory.name
            self._skills[directory.name] = {
                "id": directory.name,
                "name": display_name[:200],
                "description": description[:1000],
                "category": str(metadata.get("category") or "业务技能")[:200],
                "instruction": instruction,
            }

    def has(self, skill_id: str) -> bool:
        return skill_id in self._skills

    def instruction(self, skill_id: str) -> str:
        return self._skills[skill_id]["instruction"]

    def public(self) -> list[dict[str, str]]:
        return [
            {key: skill[key] for key in ("id", "name", "description", "category")}
            for skill in self._skills.values()
        ]

