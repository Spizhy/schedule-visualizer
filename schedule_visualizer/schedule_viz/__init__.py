"""Визуализатор расписания: текст -> структурированные занятия -> интерактивная сетка."""
from .models import Lesson, ParseResult, Parity
from .parser import parse_schedule

__all__ = ["Lesson", "ParseResult", "Parity", "parse_schedule"]
__version__ = "1.0.0"
