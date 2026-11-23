import json
import threading
import unittest
import urllib.error
import urllib.request

from schedule_viz import Parity, parse_schedule
from schedule_viz.colors import assign_hues, normalize_subject
from schedule_viz.server import create_server


def one(text):
    result = parse_schedule(text)
    assert len(result.lessons) == 1, result
    return result.lessons[0]


class ParserTests(unittest.TestCase):
    def test_single_line_with_all_fields(self):
        lesson = one("Пн 09:00-10:30 Алгебра, лекция, ауд. 205, Петров П.П.")
        self.assertEqual(
            (lesson.day, lesson.start, lesson.end), (0, 9 * 60, 10 * 60 + 30)
        )
        self.assertEqual(lesson.subject, "Алгебра")
        self.assertEqual(lesson.kind, "Лекция")
        self.assertEqual(lesson.room, "205")
        self.assertEqual(lesson.teacher, "Петров П.П.")

    def test_day_header_and_multiline_lesson(self):
        text = "Вторник\n14:15-15:50 Дискретная математика\n  лекция, ауд. 305\n  Козлова Е.В.\n"
        lesson = one(text)
        self.assertEqual(lesson.day, 1)
        self.assertEqual(lesson.subject, "Дискретная математика")
        self.assertEqual((lesson.kind, lesson.room), ("Лекция", "305"))
        self.assertEqual(lesson.teacher, "Козлова Е.В.")

    def test_pair_number_uses_default_times(self):
        lesson = one("Среда\n2 пара Информатика, практика, каб. 12")
        self.assertEqual((lesson.start, lesson.end), (10 * 60 + 15, 11 * 60 + 50))
        self.assertEqual(lesson.room, "12")

    def test_numbered_list_and_dot_time(self):
        lesson = one("Четверг\n1. 8.30 – 10.05 Физика (лаб.) 412")
        self.assertEqual(lesson.subject, "Физика")
        self.assertEqual(lesson.kind, "Лабораторная")
        self.assertEqual(lesson.room, "412")

    def test_parity(self):
        odd = one("Пн 12:00-13:35 Английский (нечётная неделя)")
        even = one("Пн 12:00-13:35 Английский, по чётным")
        self.assertIs(odd.parity, Parity.ODD)
        self.assertIs(even.parity, Parity.EVEN)

    def test_words_that_only_look_like_parity_or_kind(self):
        lesson = one("Пн 09:00-10:30 Нечеткая логика")
        self.assertIs(lesson.parity, Parity.ALL)
        self.assertEqual(lesson.subject, "Нечеткая логика")
        lesson = one("Пн 09:00-10:30 Практика по программированию, ауд. 3")
        self.assertEqual(lesson.subject, "Практика по программированию")
        self.assertIsNone(lesson.kind)

    def test_day_word_inside_subject_is_not_a_header(self):
        result = parse_schedule("Пн\n09:00-10:30 Экология\nСреда обитания\n")
        self.assertEqual(len(result.lessons), 1)
        self.assertEqual(result.lessons[0].notes, "Среда обитания")

    def test_online_room_and_tab_separated_text(self):
        lesson = one("Пт\t09:00-10:30\tБазы данных\tлекция\tонлайн")
        self.assertEqual((lesson.subject, lesson.room), ("Базы данных", "Онлайн"))

    def test_conflicts_respect_parity(self):
        text = "Пн\n10:00-11:30 А (нечёт.)\n10:00-11:30 Б (чёт.)\n11:00-12:00 В\n"
        result = parse_schedule(text)
        flags = {lesson.subject: lesson.conflict for lesson in result.lessons}
        self.assertEqual(flags, {"А": True, "Б": True, "В": True})
        self.assertEqual(len(result.warnings), 2)  # А–В и Б–В, но не А–Б

    def test_invalid_input_never_raises(self):
        result = parse_schedule("25:99-26:00 мусор\nПн\n10:00-09:00 обратное время\n???")
        self.assertEqual(result.lessons, [])
        self.assertTrue(result.warnings)

    def test_lesson_without_day_is_skipped_with_warning(self):
        result = parse_schedule("09:00-10:30 Алгебра")
        self.assertEqual(result.lessons, [])
        self.assertIn("вне дня недели", result.warnings[0])

    def test_empty_text(self):
        result = parse_schedule("")
        self.assertEqual((result.lessons, result.warnings), ([], []))

    def test_lessons_sorted(self):
        result = parse_schedule("Вт 09:00-10:00 Б\nПн 12:00-13:00 В\nПн 08:00-09:00 А")
        self.assertEqual([x.subject for x in result.lessons], ["А", "В", "Б"])


class ColorTests(unittest.TestCase):
    def test_same_subject_same_hue_regardless_of_case_and_order(self):
        a = assign_hues(["Физика", "Алгебра", "Химия"])
        b = assign_hues(["химия", "ФИЗИКА", "алгебра"])
        self.assertEqual(a, b)
        self.assertIn(normalize_subject("Физика"), a)

    def test_hues_are_spread(self):
        names = [f"Предмет {i}" for i in range(12)]
        hues = sorted(assign_hues(names).values())
        gaps = [min(b - a, 360 - (b - a)) for a, b in zip(hues, hues[1:])]
        self.assertGreaterEqual(min(gaps), 10)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = create_server("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def post(self, body: bytes):
        request = urllib.request.Request(
            f"{self.base}/api/parse", data=body, headers={"Content-Type": "application/json"}
        )
        return urllib.request.urlopen(request)

    def test_parse_endpoint(self):
        payload = json.dumps({"text": "Пн 09:00-10:30 Алгебра"}).encode()
        with self.post(payload) as response:
            data = json.load(response)
        self.assertEqual(data["lessons"][0]["subject"], "Алгебра")
        self.assertEqual(data["subjects"][0]["name"], "Алгебра")

    def test_bad_json_returns_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(b"not json")
        self.assertEqual(ctx.exception.code, 400)

    def test_index_and_security_headers(self):
        with urllib.request.urlopen(self.base + "/") as response:
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_unknown_path_and_traversal_are_404(self):
        for path in ("/nope", "/static/../server.py", "/static/%2e%2e/server.py"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(self.base + path)
            self.assertEqual(ctx.exception.code, 404, path)


if __name__ == "__main__":
    unittest.main()
