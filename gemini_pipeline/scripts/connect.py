import sys
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.services.infrastructure.gemini_client import (  # noqa: E402
    get_gemini_rotation_state_file,
    load_gemini_key_config,
)


class KeyManager:
    """
    Carrier mỏng để pipeline giữ tương thích với code cũ.

    state_file local chỉ còn dùng để ghi snapshot debug theo từng job/workspace.
    Rotation state chuẩn dùng chung toàn hệ thống nằm ở app/core/gemini_rotation_state.json.
    """

    def __init__(
        self,
        keys: list[str],
        labels: list[str],
        *,
        env_path: Path,
        state_file: Optional[Path] = None,
    ) -> None:
        self.keys = keys
        self.labels = labels
        self.env_path = env_path
        self.state_file: Optional[Path] = state_file
        self.authoritative_state_file = get_gemini_rotation_state_file()


def get_key_manager(env_path: str = "config.env", state_file: Optional[Path] = None) -> KeyManager:
    config = load_gemini_key_config(env_path)
    return KeyManager(
        config["keys"],
        config["labels"],
        env_path=Path(config["env_path"]),
        state_file=Path(state_file).expanduser().resolve() if state_file else None,
    )
