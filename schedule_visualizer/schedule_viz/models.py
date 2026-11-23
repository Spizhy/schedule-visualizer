"""Доменные модели: занятие и результат разбора."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

DAY_NAMES = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
DAY_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


class Parity(str, Enum):
    """Чётность недели, в которую проходит занятие."""

    ALL = "all"
    ODD = "odd"
    EVEN = "even"

    def is_compatible(self, other: "Parity") -> bool:
        """Могут ли два занятия оказаться в одну и ту же неделю."""
        return self is Parity.ALL or other is Parity.ALL or self is other


def format_minutes(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(slots=True)
class Lesson:
    day: int  # 0 = понедельник
    start: int  # минуты от полуночи
    end: int
    subject: str
    kind: str | None = None
    room: str | None = None
    teacher: str | None = None
    parity: Parity = Parity.ALL
    notes: str | None = None
    hue: int = 0
    conflict: bool = False

    @property
    def duration(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Lesson") -> bool:
        return (
            self.day == other.day
            and self.start < other.end
            and other.start < self.end
            and self.parity.is_compatible(other.parity)
        )

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "dayName": DAY_NAMES[self.day],
            "start": self.start,
            "end": self.end,
            "startText": format_minutes(self.start),
            "endText": format_minutes(self.end),
            "subject": self.subject,
            "kind": self.kind,
            "room": self.room,
            "teacher": self.teacher,
            "parity": self.parity.value,
            "notes": self.notes,
            "hue": self.hue,
            "conflict": self.conflict,
        }


@dataclass(slots=True)
class ParseResult:
    lessons: list[Lesson] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        subjects: dict[str, int] = {}
        for lesson in self.lessons:
            subjects.setdefault(lesson.subject, lesson.hue)
        return {
            "lessons": [lesson.to_dict() for lesson in self.lessons],
            "subjects": [
                {"name": name, "hue": hue} for name, hue in sorted(subjects.items())
            ],
            "warnings": self.warnings,
        }
