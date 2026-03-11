from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import List, Optional


@dataclass
class ParsedQuery:
    original_query: str
    cleaned_query: str

    class_hint: Optional[int]

    topic_num: Optional[int]
    topic_name: Optional[str]
    topic_requested: bool

    lesson_num: Optional[int]
    lesson_name: Optional[str]
    lesson_requested: bool

    chunk_num: Optional[int]
    chunk_name: Optional[str]
    chunk_requested: bool

    primary_keyword: str
    secondary_keywords: List[str]

    def to_dict(self) -> dict:
        return asdict(self)


# -------------------------------------------------------
# SAFE conversational fillers only
# Không đưa các từ cấu trúc như: bài, chủ đề, chương, mục
# Không đưa các từ nối như: và, hoặc
# Không đưa các từ có thể mang nghĩa nội dung như: không, hay, biết, theo, trong...
# -------------------------------------------------------
_FILLERS: list[str] = [
    # dài và rõ nghĩa nhất
    "bạn có thể cho tôi xem",
    "bạn có thể cho tôi biết",
    "bạn có thể",
    "vui lòng cho tôi biết",
    "vui lòng cho tôi xem",
    "xin cho tôi biết",
    "xin cho tôi xem",
    "xin cho tôi",
    "tôi muốn tìm kiếm",
    "mình muốn tìm kiếm",
    "tôi muốn xem",
    "mình muốn xem",
    "tôi muốn biết",
    "mình muốn biết",
    "hãy cho tôi xem",
    "hãy cho tôi biết",
    "hãy giải thích cho tôi",
    "hãy cho tôi",
    "giúp mình hỏi về",
    "giúp mình hỏi",
    "giúp mình xem",
    "giúp mình biết",
    "giúp mình",
    "giúp tôi hỏi về",
    "giúp tôi hỏi",
    "giúp tôi tìm kiếm",
    "giúp tôi tìm",
    "giúp tôi xem",
    "giúp tôi biết",
    "giúp tôi",
    "cho mình hỏi về",
    "cho mình hỏi",
    "cho mình xem",
    "cho mình biết",
    "cho tôi hỏi về",
    "cho tôi hỏi",
    "cho tôi xem",
    "cho tôi biết",
    "hãy giải thích",
    "hãy trình bày",
    "hãy tìm kiếm",
    "hãy tìm",
    "giải thích giúp mình",
    "giải thích giúp tôi",
    "giải thích cho mình",
    "giải thích",
    "thông tin về",
    "nội dung về",

    # ngắn nhưng vẫn khá an toàn
    "tôi muốn",
    "mình muốn",
    "cho mình",
    "cho tôi",
    "vui lòng",
    "làm ơn",
    "xin hãy",
    "hỏi về",
    "tìm kiếm",
    "hãy",
    "xem",

    # đại từ / hô ngữ an toàn
    "tôi",
    "mình",
    "bạn",
    "anh",
    "chị",
    "em",
    "xin",
]
_FILLERS = sorted(set(_FILLERS), key=len, reverse=True)


# -------------------------------------------------------
# Tail noise: chỉ xoá ở cuối / đầu câu, không xoá giữa câu
# -------------------------------------------------------
_TAIL_NOISE: list[str] = [
    "được không",
    "đúng không",
    "phải không",
    "có được không",
    "nhé",
    "nhỉ",
    "nha",
    "ha",
    "ạ",
    "ơi",
]
_TAIL_NOISE = sorted(set(_TAIL_NOISE), key=len, reverse=True)


# -------------------------------------------------------
# Wrappers before structural triggers
# Example:
# - "thông tin bài hệ điều hành" -> "bài hệ điều hành"
# - "nội dung chủ đề dữ liệu" -> "chủ đề dữ liệu"
# -------------------------------------------------------
_ENTITY_WRAPPERS: list[tuple[str, str]] = [
    ("thông tin bài học", "bài học"),
    ("thông tin bài", "bài"),
    ("thông tin chủ đề", "chủ đề"),
    ("thông tin chương", "chương"),
    ("thông tin mục", "mục"),
    ("nội dung bài học", "bài học"),
    ("nội dung bài", "bài"),
    ("nội dung chủ đề", "chủ đề"),
    ("nội dung chương", "chương"),
    ("nội dung mục", "mục"),
    ("kiến thức bài", "bài"),
    ("kiến thức chủ đề", "chủ đề"),
    ("kiến thức chương", "chương"),
    ("kiến thức mục", "mục"),
    ("khái niệm bài", "bài"),
    ("khái niệm chủ đề", "chủ đề"),
    ("khái niệm chương", "chương"),
    ("khái niệm mục", "mục"),
    ("định nghĩa bài", "bài"),
    ("định nghĩa chủ đề", "chủ đề"),
    ("định nghĩa chương", "chương"),
    ("định nghĩa mục", "mục"),
]
_ENTITY_WRAPPERS = sorted(set(_ENTITY_WRAPPERS), key=lambda x: len(x[0]), reverse=True)


# -------------------------------------------------------
# Structural trigger regex
# Segment-based parsing to avoid greedy swallowing.
# -------------------------------------------------------
_SEGMENT_RE = re.compile(
    r"(?<!\S)(?P<topic>chủ\s+đề|chương)(?=\s|$)"
    r"|(?<!\S)(?P<lesson>bài\s+học|bài)(?=\s|$)"
    r"|(?<!thư )(?<!\S)(?P<chunk>mục)(?=\s|$)",
    re.IGNORECASE,
)


_WEAK_STRUCT_NAME_SUFFIX_PHRASES = sorted([
    "thuộc về",
    "ở trong",
    "nằm trong",
    "ở trên",
    "ở dưới",
], key=len, reverse=True)

_WEAK_STRUCT_NAME_SUFFIX_TOKENS = {
    "trong",
    "của",
    "ở",
    "về",
    "thuộc",
    "trên",
    "dưới",
}

_WEAK_ONLY_TOKENS = {
    "trong",
    "của",
    "ở",
    "về",
    "thuộc",
    "nằm",
    "trên",
    "dưới",
}

# -------------------------------------------------------
# Helpers
# -------------------------------------------------------
def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _normalize_text(s: str) -> str:
    """
    Chuẩn hoá nhẹ:
    - lowercase
    - đổi dấu câu phổ biến thành khoảng trắng
    - giữ số và chữ tiếng Việt
    """
    s = str(s or "").lower()
    s = re.sub(r"[,:;!?()\[\]{}\"'`~@#$%^&*_+=<>/\\|-]+", " ", s)
    return _ws(s)


def _strip_phrases_space_bounded(s: str, phrases: list[str]) -> str:
    for phrase in phrases:
        pattern = r"(?<!\S)" + re.escape(phrase) + r"(?!\S)"
        s = re.sub(pattern, " ", s, flags=re.IGNORECASE)
    return _ws(s)


def _strip_fillers(s: str) -> str:
    return _strip_phrases_space_bounded(s, _FILLERS)

def _strip_weak_struct_tail(name: str) -> str:
    s = _ws((name or "").lower())
    if not s:
        return ""

    changed = True
    while changed:
        changed = False

        # cắt cụm yếu ở cuối trước
        for phrase in _WEAK_STRUCT_NAME_SUFFIX_PHRASES:
            pattern = r"(?<!\S)" + re.escape(phrase) + r"$"
            new_s = _ws(re.sub(pattern, " ", s, flags=re.IGNORECASE))
            if new_s != s:
                s = new_s
                changed = True
                break

        if changed:
            continue

        # cắt 1 token yếu ở cuối
        tokens = s.split()
        if tokens and tokens[-1] in _WEAK_STRUCT_NAME_SUFFIX_TOKENS:
            tokens.pop()
            s = " ".join(tokens)
            changed = True

    return _ws(s)


def _strip_tail_noise(s: str) -> str:
    """
    Chỉ xoá các từ đệm ở đầu/cuối câu để tránh phá nghĩa giữa câu.
    Ví dụ:
      "mạng lan nhé" -> "mạng lan"
      "ạ bài 8" -> "bài 8"
    """
    s = _ws(s)
    if not s:
        return s

    changed = True
    while changed:
        changed = False
        for phrase in _TAIL_NOISE:
            head_pat = r"^(?:" + re.escape(phrase) + r")(?=\s|$)"
            tail_pat = r"(?<!\S)(?:" + re.escape(phrase) + r")$"

            new_s = re.sub(head_pat, " ", s, flags=re.IGNORECASE)
            new_s = re.sub(tail_pat, " ", new_s, flags=re.IGNORECASE)
            new_s = _ws(new_s)

            if new_s != s:
                s = new_s
                changed = True
    return s


def _strip_entity_wrappers(s: str) -> str:
    for src, dst in _ENTITY_WRAPPERS:
        pattern = r"(?<!\S)" + re.escape(src) + r"(?!\S)"
        s = re.sub(pattern, dst, s, flags=re.IGNORECASE)
    return _ws(s)


def _extract_class_hint(s: str) -> tuple[Optional[int], str]:
    m = re.search(r"lớp\s+(\d+)", s, re.IGNORECASE)
    if not m:
        return None, s
    value = int(m.group(1))
    remaining = _ws(s[: m.start()] + s[m.end() :])
    return value, remaining


def _find_structural_segments(
    s: str,
) -> tuple[list[tuple[str, str]], str]:
    """
    Find all structural segments in order, regardless of segment order in the sentence.

    Example:
    "chương 2 bài 3 mục 1 các phần của hệ điều hành"
    ->
    [
        ("topic",  "chương 2"),
        ("lesson", "bài 3"),
        ("chunk",  "mục 1 các phần của hệ điều hành"),
    ]

    Also returns leftover text outside structural segments (usually text before
    the first trigger).
    """
    matches = list(_SEGMENT_RE.finditer(s))
    if not matches:
        return [], _ws(s)

    segments: list[tuple[str, str]] = []
    prefix = _ws(s[: matches[0].start()])

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(s)
        segment_text = _ws(s[start:end])

        if m.lastgroup == "topic":
            kind = "topic"
        elif m.lastgroup == "lesson":
            kind = "lesson"
        else:
            kind = "chunk"

        segments.append((kind, segment_text))

    return segments, prefix



def _drop_weak_struct_name(name: Optional[str]) -> Optional[str]:
    s = _strip_weak_struct_tail(name or "")
    if not s:
        return None

    tokens = s.split()
    if len(tokens) <= 3 and all(tok in _WEAK_ONLY_TOKENS for tok in tokens):
        return None

    return s

def _parse_segment(kind: str, segment_text: str) -> tuple[Optional[int], Optional[str]]:
    if kind == "topic":
        body = re.sub(r"^(?:chủ\s+đề|chương)\s*", "", segment_text, flags=re.IGNORECASE)
    elif kind == "lesson":
        body = re.sub(r"^(?:bài(?:\s+học)?)\s*", "", segment_text, flags=re.IGNORECASE)
    else:
        body = re.sub(r"^(?:mục)\s*", "", segment_text, flags=re.IGNORECASE)

    body = _strip_fillers(_ws(body))
    body = _strip_tail_noise(body)

    if not body:
        return None, None

    m = re.match(r"^(\d+)(?:\s+(.*))?$", body, re.IGNORECASE)
    if m:
        num = int(m.group(1))
        name = _ws(m.group(2) or "") or None
        name = _drop_weak_struct_name(name)
        return num, name

    name = _drop_weak_struct_name(body)
    return None, name

def _split_keywords(cleaned: str) -> tuple[str, List[str]]:
    if not cleaned:
        return "", []

    parts = [
        p.strip()
        for p in re.split(r"\s*(?:,|và|hoặc)\s*", cleaned)
        if p.strip()
    ]
    if not parts:
        return "", []

    return parts[0], parts[1:]


# -------------------------------------------------------
# Main parser
# -------------------------------------------------------
def parse_query(raw: str) -> ParsedQuery:
    original = raw
    s = _normalize_text(raw)

    # 1) Strip general conversational fillers early
    s = _strip_fillers(s)
    s = _strip_tail_noise(s)

    # 2) Extract class hint only from "lớp + số"
    class_hint, s = _extract_class_hint(s)

    # 3) Convert wrappers like "thông tin bài" -> "bài"
    s = _strip_entity_wrappers(s)

    # 4) Initialize outputs
    topic_num: Optional[int] = None
    topic_name: Optional[str] = None
    topic_requested: bool = False

    lesson_num: Optional[int] = None
    lesson_name: Optional[str] = None
    lesson_requested: bool = False

    chunk_num: Optional[int] = None
    chunk_name: Optional[str] = None
    chunk_requested: bool = False

    # 5) Segment-based structural parsing
    segments, leftover = _find_structural_segments(s)

    for kind, text in segments:
        num, name = _parse_segment(kind, text)

        if kind == "topic":
            topic_requested = True
            if topic_num is None:
                topic_num = num
            if topic_name is None:
                topic_name = name

        elif kind == "lesson":
            lesson_requested = True
            if lesson_num is None:
                lesson_num = num
            if lesson_name is None:
                lesson_name = name

        else:  # chunk
            chunk_requested = True
            if chunk_num is None:
                chunk_num = num
            if chunk_name is None:
                chunk_name = name

    # 6) Whatever remains outside structural segments becomes keyword space
    cleaned = _strip_fillers(_ws(leftover))
    cleaned = _strip_tail_noise(cleaned)

    # 7) Build primary / secondary keywords from leftover free text only
    primary_keyword, secondary_keywords = _split_keywords(cleaned)

    return ParsedQuery(
        original_query=original,
        cleaned_query=cleaned,
        class_hint=class_hint,
        topic_num=topic_num,
        topic_name=topic_name,
        topic_requested=topic_requested,
        lesson_num=lesson_num,
        lesson_name=lesson_name,
        lesson_requested=lesson_requested,
        chunk_num=chunk_num,
        chunk_name=chunk_name,
        chunk_requested=chunk_requested,
        primary_keyword=primary_keyword,
        secondary_keywords=secondary_keywords,
    )