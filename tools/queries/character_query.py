"""Character query helpers."""

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from tools.character_state_manager import CharacterStateManager
except ImportError:  # pragma: no cover - supports legacy path injection
    from character_state_manager import CharacterStateManager


class CharacterQuery:
    """Read-oriented access for character states and timeline."""

    def __init__(self, project_dir: Optional[Path] = None, novel_id: str = "my_novel"):
        self.manager = CharacterStateManager(project_dir=project_dir, novel_id=novel_id)

    def get_current_state(self, name: str) -> Dict[str, Any]:
        card = self.manager.get_character_card(name=name)
        state = self.manager.rebuild_state(character_id=card.static.id)
        return {
            "id": card.static.id,
            "name": card.static.name,
            "tier": card.static.tier,
            "state": state.model_dump(),
            "dynamic_profile": card.dynamic_profile,
            "snapshot": card.current_snapshot,
        }

    def get_rebuilt_state(self, name: str, until_chapter: Optional[str] = None) -> Dict[str, Any]:
        card = self.manager.get_character_card(name=name)
        state = self.manager.rebuild_state(character_id=card.static.id, until_chapter=until_chapter)
        return {
            "id": card.static.id,
            "name": card.static.name,
            "until_chapter": until_chapter,
            "state": state.model_dump(),
            "dynamic_profile": card.dynamic_profile,
        }

    def get_timeline(self, name: str) -> List[Dict[str, Any]]:
        card = self.manager.get_character_card(name=name)
        timeline = self.manager.get_timeline(character_id=card.static.id)
        return [mutation.model_dump() for mutation in timeline]
