"""Детерминированная цветовая маркировка предметов.

Один и тот же предмет всегда получает один и тот же оттенок (hue), а разные
предметы разводятся по кругу так, чтобы соседние цвета не сливались.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

MIN_HUE_GAP = 22  # минимальное расстояние между оттенками, градусы
HUE_STEP = 37  # шаг сдвига при коллизии (взаимно прост с 360)


def normalize_subject(name: str) -> str:
    return " ".join(name.casefold().replace("ё", "е").split())


def _base_hue(name: str) -> int:
    digest = hashlib.sha1(normalize_subject(name).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 360


def _circular_gap(a: int, b: int) -> int:
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


def assign_hues(subjects: Iterable[str]) -> dict[str, int]:
    """Возвращает {normalize_subject(предмет): оттенок 0..359}.

    Порядок обработки отсортирован, поэтому результат зависит только от
    набора предметов, а не от порядка строк в исходном тексте.
    """
    unique = sorted({normalize_subject(s) for s in subjects})
    taken: list[int] = []
    result: dict[str, int] = {}
    for key in unique:
        hue = _base_hue(key)
        for _ in range(360 // HUE_STEP + 1):
            if all(_circular_gap(hue, t) >= MIN_HUE_GAP for t in taken):
                break
            hue = (hue + HUE_STEP) % 360
        taken.append(hue)
        result[key] = hue
    return result
