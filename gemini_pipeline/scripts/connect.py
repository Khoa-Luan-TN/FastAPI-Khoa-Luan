# scripts/connect.py
import os
from pathlib import Path
from dotenv import load_dotenv

STATE_FILE = Path("Output/.gemini_key_index")


class KeyManager:
    def __init__(self, keys: list[str], state_file: Path = STATE_FILE):
        self.keys = keys
        self.state_file = state_file
        Path("Output").mkdir(parents=True, exist_ok=True)

    def _read_index(self) -> int:
        if self.state_file.exists():
            try:
                return int(self.state_file.read_text(encoding="utf-8").strip())
            except Exception:
                return 0
        return 0

    def _write_index(self, idx: int):
        self.state_file.write_text(str(idx), encoding="utf-8")

    def get_start_index_and_advance(self) -> int:
        """
        Mỗi lần chạy program: bắt đầu từ 1 key khác (round-robin).
        """
        n = len(self.keys)
        idx = self._read_index() % n
        self._write_index((idx + 1) % n)
        return idx


def get_key_manager(env_path: str = "config.env") -> KeyManager:
    load_dotenv(env_path)
    raw = (os.getenv("GEMINI_API_KEYS") or "").strip()
    if not raw:
        raise RuntimeError("Không tìm thấy GEMINI_API_KEYS trong config.env")

    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("GEMINI_API_KEYS rỗng hoặc sai định dạng")

    return KeyManager(keys)
