"""Разбор расписания из произвольного скопированного текста.

Поддерживаемые варианты записи (можно смешивать в одном тексте):

    Понедельник                      Пн 09:00-10:30 Алгебра, лекция, ауд. 205
    1. 08:30-10:05 Матанализ         Вт: 10:15 – 11:50 Физика (лаб.) 412 Иванов И.И.
       лекция, ауд. 301
       Иванов И.И.                   Среда
                                     2 пара Информатика, практика, каб. 12

Алгоритм построчный: заголовок дня задаёт текущий день, строка со временем
(или номером пары) открывает новое занятие, а строки без времени
дописываются к открытому занятию как продолжение. Из собранного текста
занятия последовательно «вырезаются» чётность недели, тип, аудитория и
преподаватель; то, что осталось, и есть название предмета.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .colors import assign_hues, normalize_subject
from .models import DAY_NAMES, Lesson, ParseResult, Parity, format_minutes

# Времена пар по умолчанию (типичная сетка вузов РФ). Можно передать свои.
DEFAULT_PAIR_TIMES: dict[int, tuple[str, str]] = {
    1: ("08:30", "10:05"),
    2: ("10:15", "11:50"),
    3: ("12:00", "13:35"),
    4: ("14:15", "15:50"),
    5: ("16:00", "17:35"),
    6: ("18:10", "19:45"),
    7: ("19:55", "21:30"),
}

_DAY_ALIASES: dict[str, int] = {}
for _idx, _names in enumerate(
    (
        ("понедельник", "пн", "пнд", "monday", "mon"),
        ("вторник", "вт", "втр", "tuesday", "tue"),
        ("среда", "среду", "ср", "срд", "wednesday", "wed"),
        ("четверг", "чт", "чтв", "thursday", "thu"),
        ("пятница", "пятницу", "пт", "птн", "friday", "fri"),
        ("суббота", "субботу", "сб", "сбт", "saturday", "sat"),
        ("воскресенье", "вс", "вск", "sunday", "sun"),
    )
):
    for _name in _names:
        _DAY_ALIASES[_name] = _idx


# --------------------------------------------------------------------------- #
# Регулярные выражения. Те, что работают по «нормализованному» тексту
# (нижний регистр, ё -> е), помечены суффиксом _N; остальные — по оригиналу.
# --------------------------------------------------------------------------- #
_TIME_RANGE_N = re.compile(
    r"(?:(?<![а-яa-z])с\s+)?(?<!\d)(\d{1,2})[:.](\d{2})\s*(?:-|–|—|−|до|to)\s*(\d{1,2})[:.](\d{2})(?!\d)"
)
_PAIR_N = re.compile(
    r"(?<![а-яa-z\d])(?:(\d)\s*-?\s*(?:я\s+)?пара|пара\s*№?\s*(\d))(?![а-яa-z\d])"
)
_DAY_WORD = re.compile(r"^([A-Za-zА-Яа-яЁё]+)\.?(.*)$")
_DATE_LIKE = re.compile(
    r"^[\(\[]?\s*(?:\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|\d{1,2}\s+[а-яё]+\.?(?:\s+\d{4})?)\s*[\)\]]?$",
    re.IGNORECASE,
)

_PARITY_N = re.compile(
    r"(?<![а-я])(?:по\s+)?(не)?чет(?:н\w*|\.)?(?![а-я])(?:\s*нед\w*\.?)?"
)

_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(rf"(?<![а-яa-z])(?:{alts})(?![а-яa-z])"))
    for label, alts in (
        ("Лекция", r"лекци\w*|лек\.?|lecture"),
        ("Семинар", r"семинар\w*|сем\.?|seminar"),
        ("Практика", r"практик\w*|практическ\w*|пр\.|пр(?=\))|practice"),
        ("Лабораторная", r"лабораторн\w*|лаб\.?|lab"),
        ("Экзамен", r"экзамен\w*|exam"),
        ("Зачёт", r"зачет\w*"),
        ("Консультация", r"консультаци\w*|конс\."),
    )
)

_ONLINE_N = re.compile(
    r"(?<![а-яa-z])(?:онлайн|online|дистанц\w*|zoom|ms\s+teams|teams)(?![а-яa-z])"
)
_ROOM_N = re.compile(
    r"(?<![а-яa-z])(?:ауд(?:итори\w*)?\.?|каб(?:инет\w*)?\.?|room|rm\.?)"
    r"\s*№?\s*(?P<room>[a-zа-я0-9][a-zа-я0-9\-/]*)"
)
# Аудитория без пометки «ауд.» в конце: «, 412» или просто « 412» (от 3 цифр).
_ROOM_TAIL_N = re.compile(
    r"(?:[,|]\s*(?=\d{2,4}[a-zа-я]?\s*$)|\s(?=\d{3,4}[a-zа-я]?\s*$))"
    r"(?P<room>\d{2,4}[a-zа-я]?)\s*$"
)

_TITLE = r"(?i:(?:ст\.?\s*)?преп(?:одаватель|\.)?|доц(?:ент|\.)?|проф(?:ессор|\.)?|асс(?:истент|\.)?)"
_SURNAME = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
_INITIALS = r"[А-ЯЁ]\.\s*(?:[А-ЯЁ]\.)?"
_TEACHER_SURNAME_FIRST = re.compile(rf"(?:{_TITLE}\s*)?(?P<name>{_SURNAME}\s+{_INITIALS})")
_TEACHER_INITIALS_FIRST = re.compile(rf"(?:{_TITLE}\s*)?(?P<name>{_INITIALS}\s*{_SURNAME})")
_TEACHER_FULL = re.compile(
    rf"(?:^|[,|;—–-])\s*(?P<name>{_SURNAME}\s+{_SURNAME}\s+{_SURNAME})\s*$"
)


def _norm(text: str) -> str:
    """Нижний регистр и ё -> е с сохранением длины строки (индексы совпадают)."""
    return "".join(
        (c.lower() if len(c.lower()) == 1 else c).replace("ё", "е") for c in text
    )


class _Text:
    """Строка, из которой можно последовательно «вырезать» найденные поля."""

    def __init__(self, text: str) -> None:
        self.text = text

    def cut(self, pattern: re.Pattern[str], *, normalized: bool = True, accept=None):
        """Вырезает первое подходящее вхождение и возвращает {группа: оригинал}."""
        source = _norm(self.text) if normalized else self.text
        for match in pattern.finditer(source):
            if accept is not None and not accept(source, match):
                continue
            groups: dict[int | str, str] = {0: self.text[match.start() : match.end()]}
            keys: list[int | str] = [*range(1, (match.re.groups or 0) + 1)]
            keys += list(match.groupdict())
            for key in keys:
                if match.start(key) >= 0:
                    groups[key] = self.text[match.start(key) : match.end(key)]
            self.text = f"{self.text[: match.start()]} {self.text[match.end() :]}"
            return groups
        return None


# --------------------------------------------------------------------------- #
# Построчный разбор
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class _Draft:
    day: int
    start: int
    end: int
    line_no: int
    fragments: list[str] = field(default_factory=list)


class _SlotError(ValueError):
    pass


def _clean_line(raw: str) -> str:
    line = raw.replace("\t", " | ").replace(" ", " ")
    line = re.sub(r"[*_`#>]+", " ", line)
    line = re.sub(r"^[\s•·▪●◦\-–—]+(?=\S)", "", line)
    line = re.sub(r"\s{2,}", " ", line)
    line = re.sub(r"(?:\s*\|\s*){2,}", " | ", line)
    return line.strip(" |\t")


def _split_day(line: str) -> tuple[int, str] | None:
    """Если строка начинается с дня недели — вернуть (день, остаток строки)."""
    match = _DAY_WORD.match(line)
    if not match:
        return None
    day = _DAY_ALIASES.get(_norm(match.group(1)))
    if day is None:
        return None
    rest = match.group(2).lstrip(" :,-–—.").strip()
    # «Среда обитания» — это предмет, а не заголовок дня.
    if rest and not _DATE_LIKE.match(rest) and not _has_slot(rest):
        return None
    return day, rest


def _has_slot(text: str) -> bool:
    norm = _norm(text)
    return bool(_TIME_RANGE_N.search(norm) or _PAIR_N.search(norm))


def _to_minutes(hours: str, minutes: str) -> int:
    h, m = int(hours), int(minutes)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise _SlotError(f"некорректное время {hours}:{minutes}")
    return h * 60 + m


def _find_slot(
    line: str, pair_times: dict[int, tuple[str, str]]
) -> tuple[int, int, str] | None:
    """Ищет время или номер пары. Возвращает (начало, конец, остаток строки)."""
    norm = _norm(line)
    cutter = _Text(line)

    if time_match := _TIME_RANGE_N.search(norm):
        start = _to_minutes(time_match.group(1), time_match.group(2))
        end = _to_minutes(time_match.group(3), time_match.group(4))
        if end <= start:
            raise _SlotError("конец занятия не позже его начала")
        cutter.cut(_TIME_RANGE_N)
        cutter.cut(_PAIR_N)  # «1 пара 08:30-10:05» — номер пары уже не нужен
        return start, end, cutter.text

    if pair_match := _PAIR_N.search(norm):
        number = int(pair_match.group(1) or pair_match.group(2))
        if number not in pair_times:
            raise _SlotError(f"неизвестный номер пары: {number}")
        s_text, e_text = pair_times[number]
        cutter.cut(_PAIR_N)
        return _to_minutes(*s_text.split(":")), _to_minutes(*e_text.split(":")), cutter.text

    return None


def _extract_lesson(draft: _Draft, warnings: list[str]) -> Lesson:
    text = _Text(" | ".join(draft.fragments))

    parity = Parity.ALL
    if hit := text.cut(_PARITY_N):
        parity = Parity.ODD if hit.get(1) else Parity.EVEN

    kind = None
    for label, pattern in _KINDS:
        if text.cut(pattern, accept=_kind_is_not_subject):
            kind = label
            break

    room = None
    if hit := text.cut(_ROOM_N):
        room = hit["room"].strip()
    elif text.cut(_ONLINE_N):
        room = "Онлайн"

    teacher = None
    for pattern in (_TEACHER_SURNAME_FIRST, _TEACHER_INITIALS_FIRST):
        if hit := text.cut(pattern, normalized=False):
            teacher = re.sub(r"\s+", " ", hit["name"]).strip()
            break
    else:
        tail = text.text.rstrip(" ,;|")
        if hit := _TEACHER_FULL.search(tail):
            teacher = re.sub(r"\s+", " ", hit["name"]).strip()
            text.text = tail[: hit.start("name")] + " "

    if room is None:
        text.text = text.text.rstrip(" ,;|")
        if hit := text.cut(_ROOM_TAIL_N):
            room = hit["room"].strip()

    cleaned = re.sub(r"\(\s*[,;|\s]*\)", " ", text.text)
    parts = []
    for fragment in cleaned.split("|"):
        fragment = re.sub(r"^\s*\d{1,2}\s*[.)]\s+", "", fragment)
        fragment = re.sub(r"(?:\s*,){2,}", ",", fragment)
        fragment = re.sub(r"\s+", " ", fragment).strip(" \t,;:·•–—-")
        if fragment:
            parts.append(fragment)

    subject = parts[0] if parts else ""
    notes = ", ".join(parts[1:]) or None
    if not subject:
        subject = "Без названия"
        warnings.append(
            f"Строка {draft.line_no}: не найдено название предмета "
            f"({DAY_NAMES[draft.day]}, {format_minutes(draft.start)})."
        )
    return Lesson(
        day=draft.day,
        start=draft.start,
        end=draft.end,
        subject=subject,
        kind=kind,
        room=room,
        teacher=teacher,
        parity=parity,
        notes=notes,
    )


def _kind_is_not_subject(source: str, match: re.Match[str]) -> bool:
    """«Практика по Python» — предмет; «Python, практика» — тип занятия."""
    if match.group(0).endswith("."):
        return True
    left = source[: match.start()].rstrip()
    right = source[match.end() :]
    at_left_edge = left == "" or left.endswith("|")
    words_follow = bool(right[:1].isspace() and right.lstrip()[:1].isalpha())
    return not (at_left_edge and words_follow)


def _mark_conflicts(lessons: list[Lesson], warnings: list[str]) -> None:
    for i, a in enumerate(lessons):
        for b in lessons[i + 1 :]:
            if b.day != a.day:
                break  # список отсортирован по дню
            if a.overlaps(b):
                a.conflict = b.conflict = True
                warnings.append(
                    f"Пересечение ({DAY_NAMES[a.day]}): «{a.subject}» "
                    f"({format_minutes(a.start)}–{format_minutes(a.end)}) и «{b.subject}» "
                    f"({format_minutes(b.start)}–{format_minutes(b.end)})."
                )


def parse_schedule(
    text: str, *, pair_times: dict[int, tuple[str, str]] | None = None
) -> ParseResult:
    """Разбирает текст расписания. Никогда не бросает исключений из-за формата:
    нераспознанное попадает в ``ParseResult.warnings``."""
    pair_times = pair_times or DEFAULT_PAIR_TIMES
    result = ParseResult()
    drafts: list[_Draft] = []
    current_day: int | None = None
    draft: _Draft | None = None

    def flush() -> None:
        nonlocal draft
        if draft is not None:
            drafts.append(draft)
            draft = None

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = _clean_line(raw)
        if not line:
            flush()
            continue

        if (day_hit := _split_day(line)) is not None:
            flush()
            current_day, line = day_hit
            if not line or not _has_slot(line):
                continue  # просто заголовок дня (возможно, с датой)

        try:
            slot = _find_slot(line, pair_times)
        except _SlotError as exc:
            flush()
            result.warnings.append(f"Строка {line_no}: {exc} — «{raw.strip()}».")
            continue

        if slot is not None:
            flush()
            if current_day is None:
                result.warnings.append(
                    f"Строка {line_no}: занятие вне дня недели пропущено — «{raw.strip()}»."
                )
                continue
            start, end, rest = slot
            draft = _Draft(current_day, start, end, line_no, [rest] if rest.strip() else [])
        elif draft is not None:
            draft.fragments.append(line)
        else:
            result.warnings.append(f"Строка {line_no} не распознана: «{raw.strip()}».")
    flush()

    lessons = [_extract_lesson(d, result.warnings) for d in drafts]
    hues = assign_hues(lesson.subject for lesson in lessons)
    for lesson in lessons:
        lesson.hue = hues[normalize_subject(lesson.subject)]
    lessons.sort(key=lambda x: (x.day, x.start, x.end, x.subject))
    _mark_conflicts(lessons, result.warnings)
    result.lessons = lessons
    return result
