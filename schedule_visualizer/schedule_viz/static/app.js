"use strict";

const PARITY_LABEL = { odd: "нечёт.", even: "чёт." };
const DAY_NAMES = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];
const STORAGE_KEY = "schedule-viz:text";
const THEME_KEY = "schedule-viz:theme";

const $ = (id) => document.getElementById(id);
const els = {
  source: $("source"),
  schedule: $("schedule"),
  legend: $("legend"),
  stats: $("stats"),
  error: $("error"),
  warnings: $("warnings"),
  warningsCount: $("warnings-count"),
  warningsList: $("warnings-list"),
  dialog: $("details"),
  dSubject: $("d-subject"),
  dList: $("d-list"),
  parity: $("parity"),
  theme: $("btn-theme"),
};

const state = { data: null, parity: "all", hidden: new Set(), requestId: 0 };

/** Создаёт элемент; весь пользовательский текст идёт через textContent (без XSS). */
function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child) node.append(child);
  return node;
}

const debounce = (fn, ms) => {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
};

const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* приватный режим */ } },
};

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const label = theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
  els.theme.setAttribute("aria-label", label);
  els.theme.title = label;
}

/* ------------------------------ запрос к API ------------------------------ */
async function parse() {
  const text = els.source.value;
  store.set(STORAGE_KEY, text);
  const requestId = ++state.requestId;
  els.error.hidden = true;
  if (!text.trim()) {
    state.data = null;
    return render();
  }
  try {
    const response = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const payload = await response.json();
    if (requestId !== state.requestId) return; // устаревший ответ
    if (!response.ok) throw new Error(payload.error || response.statusText);
    state.data = payload;
  } catch (err) {
    if (requestId !== state.requestId) return;
    els.error.textContent = `Ошибка: ${err.message}`;
    els.error.hidden = false;
    return;
  }
  render();
}

/* -------------------------------- раскладка ------------------------------- */
/** Раскладывает пересекающиеся занятия по «дорожкам» бок о бок. */
function layoutLanes(lessons) {
  const sorted = [...lessons].sort((a, b) => a.start - b.start || a.end - b.end);
  const placed = [];
  let cluster = [];
  let clusterEnd = -1;

  const closeCluster = () => {
    const lanes = Math.max(1, ...cluster.map((p) => p.lane + 1));
    cluster.forEach((p) => { p.lanes = lanes; });
    placed.push(...cluster);
    cluster = [];
  };

  for (const lesson of sorted) {
    if (cluster.length && lesson.start >= clusterEnd) closeCluster();
    const taken = new Set(
      cluster.filter((p) => p.lesson.end > lesson.start).map((p) => p.lane)
    );
    let lane = 0;
    while (taken.has(lane)) lane++;
    cluster.push({ lesson, lane, lanes: 1 });
    clusterEnd = Math.max(clusterEnd, lesson.end);
  }
  if (cluster.length) closeCluster();
  return placed;
}

function visibleLessons() {
  return state.data.lessons.filter(
    (l) =>
      !state.hidden.has(l.subject) &&
      (state.parity === "all" || l.parity === "all" || l.parity === state.parity)
  );
}

const pad = (n) => String(n).padStart(2, "0");

/* -------------------------------- отрисовка ------------------------------- */
function render() {
  renderWarnings();
  renderLegend();
  renderGrid();
}

function renderWarnings() {
  const warnings = state.data?.warnings ?? [];
  els.warnings.hidden = warnings.length === 0;
  els.warningsCount.textContent = `Проверка расписания · ${warnings.length}`;
  els.warningsList.replaceChildren(...warnings.map((w) => h("li", { text: w })));
}

function renderLegend() {
  const subjects = state.data?.subjects ?? [];
  els.legend.replaceChildren(
    ...subjects.map((s) => {
      const chip = h(
        "button",
        {
          type: "button",
          class: "chip",
          "aria-pressed": String(!state.hidden.has(s.name)),
          onclick: () => {
            if (state.hidden.has(s.name)) state.hidden.delete(s.name);
            else state.hidden.add(s.name);
            chip.setAttribute("aria-pressed", String(!state.hidden.has(s.name)));
            renderGrid();
          },
        },
        h("span", { class: "dot" }),
        s.name
      );
      chip.style.setProperty("--h", s.hue);
      return chip;
    })
  );
}

function renderGrid() {
  const data = state.data;
  if (!data || data.lessons.length === 0) {
    els.stats.textContent = "";
    els.schedule.replaceChildren(
      h("div", { class: "empty" },
        h("strong", { text: data ? "Занятия не распознаны" : "Расписание пока пустое" }),
        h("p", { text: data ? "Проверьте дни и время в исходном тексте" : "Вставьте текст расписания или загрузите пример" })
      )
    );
    return;
  }

  const lessons = visibleLessons();
  els.stats.textContent = `Занятий: ${lessons.length} · предметов: ${new Set(lessons.map((l) => l.subject)).size}`;
  if (lessons.length === 0) {
    els.schedule.replaceChildren(
      h("div", { class: "empty" },
        h("strong", { text: "Нет занятий по выбранным фильтрам" }),
        h("p", { text: "Выберите другую неделю или включите предметы в списке выше" })
      )
    );
    return;
  }

  // Диапазон времени считаем по всем занятиям, чтобы сетка не «прыгала» при фильтрах.
  const from = Math.floor(Math.min(...data.lessons.map((l) => l.start)) / 60) * 60;
  const to = Math.ceil(Math.max(...data.lessons.map((l) => l.end)) / 60) * 60;
  const lastDay = Math.max(4, ...data.lessons.map((l) => l.day));
  const days = [...Array(lastDay + 1).keys()];
  const today = (new Date().getDay() + 6) % 7;

  const grid = h("div", { class: "grid" });
  grid.style.setProperty("--cols", days.length);
  grid.style.setProperty("--duration", to - from);

  grid.append(h("div", { class: "corner", text: "Время" }));

  const axis = h("div", { class: "axis", "aria-hidden": "true" });
  for (let m = from; m <= to; m += 60) {
    const label = h("span", { text: `${pad(m / 60)}:00` });
    label.style.setProperty("--offset", m - from);
    axis.append(label);
  }
  grid.append(axis);

  for (const d of days) {
    const isToday = d === today;
    const marker = isToday ? " today" : "";
    const heading = h("h3", { class: `day-head${marker}` },
      h("span", { text: DAY_NAMES[d] }),
      isToday && h("span", { class: "today-label", text: "Сегодня" })
    );
    const col = h("div", { class: `day-col${marker}` });

    for (const { lesson, lane, lanes } of layoutLanes(lessons.filter((l) => l.day === d))) {
      col.append(lessonNode(lesson, lane, lanes, from));
    }
    if (isToday) {
      col.append(h("div", {
        class: "now-line", "data-from": from, "data-to": to, "aria-hidden": "true"
      }));
    }
    const day = h("div", { class: "day" }, heading, col);
    day.style.setProperty("--day-column", d + 2);
    grid.append(day);
  }

  els.schedule.replaceChildren(grid);
  updateNowLine();
}

function lessonNode(lesson, lane, lanes, from) {
  const duration = lesson.end - lesson.start;
  const room = lesson.room === "Онлайн" ? lesson.room : lesson.room && `ауд. ${lesson.room}`;
  const meta = [lesson.kind, room].filter(Boolean).join(" · ");
  const classes = ["lesson"];
  if (lesson.conflict) classes.push("conflict");
  if (duration < 52) classes.push("compact");
  if (lanes > 1) classes.push("narrow");
  const node = h(
    "button",
    {
      type: "button",
      class: classes.join(" "),
      "aria-label": [lesson.subject, `${lesson.dayName} ${lesson.startText}–${lesson.endText}`,
        PARITY_LABEL[lesson.parity], lesson.conflict && "Пересечение"].filter(Boolean).join(", "),
      onclick: () => showDetails(lesson),
    },
    h("span", { class: "time", text: `${lesson.startText}–${lesson.endText}` }),
    h("span", { class: "subject", text: lesson.subject }),
    PARITY_LABEL[lesson.parity] && h("span", { class: "badge", text: PARITY_LABEL[lesson.parity] }),
    lesson.conflict && h("span", { class: "conflict-label", text: "Пересечение" }),
    meta && h("span", { class: "meta", text: meta }),
    lesson.teacher && h("span", { class: "meta", text: lesson.teacher })
  );
  node.style.setProperty("--h", lesson.hue);
  node.style.setProperty("--offset", lesson.start - from);
  node.style.setProperty("--length", duration);
  node.style.setProperty("--lane-start", `${(lane / lanes) * 100}%`);
  node.style.setProperty("--lane-width", `${100 / lanes}%`);
  return node;
}

function updateNowLine() {
  const line = document.querySelector(".now-line");
  if (!line) return;
  const from = Number(line.dataset.from);
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  line.hidden = minutes < from || minutes > Number(line.dataset.to);
  line.style.setProperty("--offset", minutes - from);
}

function showDetails(lesson) {
  els.dSubject.textContent = lesson.subject;
  const rows = [
    ["День", lesson.dayName],
    ["Время", `${lesson.startText}–${lesson.endText}`],
    ["Тип", lesson.kind],
    ["Аудитория", lesson.room],
    ["Преподаватель", lesson.teacher],
    ["Неделя", { odd: "нечётная", even: "чётная" }[lesson.parity]],
    ["Заметки", lesson.notes],
    ["Внимание", lesson.conflict ? "пересекается с другим занятием" : null],
  ].filter(([, value]) => value);
  els.dList.replaceChildren(...rows.flatMap(([k, v]) => [h("dt", { text: k }), h("dd", { text: v })]));
  els.dialog.showModal();
}

/* ------------------------------- обработчики ------------------------------ */
els.source.addEventListener("input", debounce(parse, 300));

els.parity.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-parity]");
  if (!button) return;
  state.parity = button.dataset.parity;
  for (const b of els.parity.querySelectorAll("button")) {
    b.setAttribute("aria-pressed", String(b === button));
  }
  if (state.data) renderGrid();
});

$("btn-sample").addEventListener("click", async () => {
  try {
    const response = await fetch("/static/sample.txt");
    els.source.value = await response.text();
    state.hidden.clear();
    parse();
  } catch {
    els.error.textContent = "Не удалось загрузить пример";
    els.error.hidden = false;
  }
});
$("btn-clear").addEventListener("click", () => {
  els.source.value = "";
  state.hidden.clear();
  parse();
});
$("btn-print").addEventListener("click", () => window.print());
els.theme.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(theme);
  store.set(THEME_KEY, theme);
});

els.dialog.addEventListener("click", (event) => {
  if (event.target === els.dialog) els.dialog.close(); // клик по фону
});

setInterval(updateNowLine, 60_000);

if (location.protocol === "file:") {
  $("app").hidden = true;
  $("file-help").hidden = false;
} else {
  applyTheme(store.get(THEME_KEY) === "light" ? "light" : "dark");
  els.theme.hidden = false;
  els.source.value = store.get(STORAGE_KEY) ?? "";
  parse();
}
