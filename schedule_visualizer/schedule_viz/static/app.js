"use strict";

const PARITY_LABEL = { odd: "нечёт.", even: "чёт." };
const DAY_NAMES = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];
const SHORT_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const COURSE_HUES = [212, 42, 130, 267, 334, 180, 18, 234, 68, 307];
const STORAGE_KEY = "schedule-viz:text";
const THEME_KEY = "schedule-viz:theme";
const mobile = matchMedia("screen and (max-width: 760px)");
const localDay = (date = new Date()) => (date.getDay() + 6) % 7;

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
  editor: $("editor"),
  editorToggle: $("btn-editor"),
  visualize: $("btn-visualize"),
  clear: $("btn-clear"),
  sample: $("btn-sample"),
  print: $("btn-print"),
  footer: $("schedule-footer"),
  view: $("view"),
  day: $("selected-day"),
  dayControls: $("day-controls"),
};

const state = { data: null, parity: "all", view: "week", day: localDay(), hidden: new Set(), hues: new Map(), requestId: 0 };

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

function syncTheme() {
  applyTheme(store.get(THEME_KEY) || (mobile.matches ? "light" : "dark"));
}

function setEditorOpen(open) {
  els.editor.hidden = !open;
  els.editorToggle.setAttribute("aria-expanded", String(open));
}

function setBusy(busy) {
  const hasText = Boolean(els.source.value.trim());
  els.visualize.disabled = busy || !hasText;
  els.visualize.textContent = busy ? "Разбираем расписание…" : "Визуализировать";
  els.sample.disabled = busy;
  els.clear.hidden = !hasText;
  els.schedule.setAttribute("aria-busy", String(busy));
}

/* ------------------------------ запрос к API ------------------------------ */
async function parse() {
  const text = els.source.value;
  store.set(STORAGE_KEY, text);
  const requestId = ++state.requestId;
  els.error.hidden = true;
  if (!text.trim()) {
    state.data = null;
    setBusy(false);
    return render();
  }
  setBusy(true);
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
  } finally {
    if (requestId === state.requestId) setBusy(false);
  }
  render();
  if (mobile.matches && state.data.lessons.length && !els.editor.hidden) {
    const focusWasInEditor = els.editor.contains(document.activeElement);
    setEditorOpen(false);
    if (focusWasInEditor) els.editorToggle.focus();
  }
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
  const names = [...new Set(state.data?.lessons.map((lesson) => lesson.subject) ?? [])];
  state.hues = new Map(names.map((name, index) => [name, COURSE_HUES[index]]));
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
  const subjects = new Map((state.data?.subjects ?? []).map((subject) => [subject.name, subject]));
  els.legend.replaceChildren(
    ...[...state.hues.keys()].map((name) => {
      const s = subjects.get(name);
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
      chip.style.setProperty("--h", state.hues.get(s.name) ?? s.hue);
      return chip;
    })
  );
}

function renderGrid() {
  const data = state.data;
  els.footer.hidden = !data?.lessons.length;
  els.print.hidden = !data?.lessons.length;
  els.print.disabled = true;
  els.parity.hidden = !data?.lessons.some((lesson) => lesson.parity !== "all");
  els.dayControls.hidden = state.view !== "day" || !data?.lessons.length;
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

  const filtered = visibleLessons();
  const lessons = state.view === "day" ? filtered.filter((lesson) => lesson.day === state.day) : filtered;
  els.stats.textContent = `Занятий: ${lessons.length} · предметов: ${new Set(lessons.map((l) => l.subject)).size}`;
  if (lessons.length === 0) {
    els.schedule.replaceChildren(
      h("div", { class: "empty" },
        h("strong", { text: state.view === "day" ? "В этот день нет занятий" : "Нет занятий по выбранным фильтрам" }),
        h("p", { text: "Выберите другой день, неделю или предмет" })
      )
    );
    return;
  }
  els.print.disabled = false;

  // Диапазон времени считаем по всем занятиям, чтобы сетка не «прыгала» при фильтрах.
  const starts = [...new Set(data.lessons.map((lesson) => lesson.start))].sort((a, b) => a - b);
  const from = starts[0];
  const to = Math.max(...data.lessons.map((l) => l.end));
  const lastDay = Math.max(4, ...data.lessons.map((l) => l.day));
  const days = state.view === "day" ? [state.day] : [...Array(lastDay + 1).keys()];
  const today = localDay();

  const grid = h("div", { class: `grid grid--${state.view}` });
  grid.style.setProperty("--cols", days.length);
  grid.style.setProperty("--duration", to - from);

  grid.append(h("div", { class: "corner", "aria-hidden": "true" }));

  const axis = h("div", { class: "axis", "aria-hidden": "true" });
  const ticks = [];
  for (const minute of starts) {
    if (!ticks.length || minute - ticks.at(-1) >= 30) ticks.push(minute);
  }
  for (const m of ticks) {
    const label = h("span", { text: `${pad(Math.floor(m / 60))}:${pad(m % 60)}` });
    label.style.setProperty("--offset", m - from);
    axis.append(label);
  }
  grid.append(axis);

  for (const [index, d] of days.entries()) {
    const isToday = d === today;
    const marker = isToday ? " today" : "";
    const heading = h("h3", { class: `day-head${marker}` },
      h("span", { class: "day-short", "aria-hidden": "true", text: SHORT_DAYS[d] }),
      h("span", { class: "day-full", text: DAY_NAMES[d] }),
      isToday && h("span", { class: "today-label", text: "Сегодня" })
    );
    const col = h("div", { class: `day-col${marker}` });
    for (const m of ticks.slice(1)) {
      const rule = h("span", { class: "time-rule", "aria-hidden": "true" });
      rule.style.setProperty("--offset", m - from);
      col.append(rule);
    }

    for (const { lesson, lane, lanes } of layoutLanes(lessons.filter((l) => l.day === d))) {
      col.append(lessonNode(lesson, lane, lanes, from));
    }
    if (isToday) {
      col.append(h("div", {
        class: "now-line", "data-from": from, "data-to": to, "aria-hidden": "true"
      }));
    }
    const day = h("div", { class: "day" }, heading, col);
    day.style.setProperty("--day-column", index + 2);
    grid.append(day);
  }

  els.schedule.replaceChildren(grid);
  updateTimeline();
}

function lessonNode(lesson, lane, lanes, from) {
  const duration = lesson.end - lesson.start;
  const room = lesson.room === "Онлайн" ? lesson.room : lesson.room && `ауд. ${lesson.room}`;
  const meta = [room, lesson.kind, lesson.teacher].filter(Boolean);
  const classes = ["lesson"];
  if (lesson.conflict) classes.push("conflict");
  if (duration < 52) classes.push("compact");
  if (lanes > 1) classes.push("narrow");
  const node = h(
    "button",
    {
      type: "button",
      class: classes.join(" "),
      "data-day": lesson.day,
      "data-start": lesson.start,
      "data-parity": lesson.parity,
      "aria-label": [lesson.subject, `${lesson.dayName} ${lesson.startText}–${lesson.endText}`,
        PARITY_LABEL[lesson.parity], lesson.conflict && "Пересечение"].filter(Boolean).join(", "),
      onclick: () => showDetails(lesson),
    },
    h("span", { class: "time", text: `${lesson.startText}–${lesson.endText}` }),
    h("span", { class: "subject", text: lesson.subject }),
    PARITY_LABEL[lesson.parity] && h("span", { class: "badge", text: PARITY_LABEL[lesson.parity] }),
    meta.length && h("span", { class: "meta" }, ...meta.map((text) => h("span", { text }))),
    lesson.conflict && h("span", { class: "conflict-label", text: "Пересечение" }),
    h("span", { class: "next-label", text: "Следующая пара", hidden: "" })
  );
  node.style.setProperty("--h", state.hues.get(lesson.subject) ?? lesson.hue);
  node.style.setProperty("--offset", lesson.start - from);
  node.style.setProperty("--length", duration);
  node.style.setProperty("--lane-start", `${(lane / lanes) * 100}%`);
  node.style.setProperty("--lane-width", `${100 / lanes}%`);
  return node;
}

function updateTimeline() {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const today = localDay(now);
  const line = els.schedule.querySelector(".now-line");
  if (line) {
    const from = Number(line.dataset.from);
    line.hidden = minutes < from || minutes > Number(line.dataset.to);
    line.style.setProperty("--offset", minutes - from);
  }
  const cards = [...els.schedule.querySelectorAll(".lesson")];
  const upcoming = cards.find((card) => Number(card.dataset.day) === today &&
    Number(card.dataset.start) >= minutes && (card.dataset.parity === "all" || card.dataset.parity === state.parity));
  for (const card of cards) {
    card.querySelector(".next-label").hidden = card !== upcoming;
    if (card === upcoming) card.setAttribute("aria-description", "Следующая пара");
    else card.removeAttribute("aria-description");
  }
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
els.source.addEventListener("input", () => {
  state.requestId++;
  store.set(STORAGE_KEY, els.source.value);
  els.error.hidden = true;
  setBusy(false);
});
els.editor.addEventListener("submit", (event) => {
  event.preventDefault();
  parse();
});
els.editorToggle.addEventListener("click", () => setEditorOpen(els.editor.hidden));
mobile.addEventListener("change", () => {
  if (matchMedia("print").matches) return;
  document.documentElement.dataset.narrow = String(mobile.matches);
  setEditorOpen(!mobile.matches || !state.data?.lessons.length);
  syncTheme();
});

els.day.append(...DAY_NAMES.map((text, day) => h("option", { value: day, text })));
els.day.addEventListener("change", () => {
  state.day = Number(els.day.value);
  renderGrid();
});

els.view.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button) return;
  state.view = button.dataset.view;
  for (const option of els.view.querySelectorAll("button")) {
    option.setAttribute("aria-pressed", String(option === button));
  }
  if (state.view === "day") {
    const lessons = state.data ? visibleLessons() : [];
    if (lessons.length && !lessons.some((lesson) => lesson.day === state.day)) state.day = lessons[0].day;
    els.day.value = String(state.day);
  }
  renderGrid();
});

els.parity.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-parity]");
  if (!button) return;
  state.parity = button.dataset.parity;
  for (const b of els.parity.querySelectorAll("button")) {
    b.setAttribute("aria-pressed", String(b === button));
  }
  if (state.data) renderGrid();
});

els.sample.addEventListener("click", async () => {
  const requestId = ++state.requestId;
  els.sample.disabled = true;
  try {
    const response = await fetch("/static/sample.txt");
    if (!response.ok) throw new Error(response.statusText);
    const sample = await response.text();
    if (requestId !== state.requestId) return;
    els.source.value = sample;
    state.hidden.clear();
    await parse();
  } catch {
    if (requestId !== state.requestId) return;
    setBusy(false);
    els.error.textContent = "Не удалось загрузить пример";
    els.error.hidden = false;
  }
});
els.clear.addEventListener("click", () => {
  els.source.value = "";
  state.hidden.clear();
  parse();
});
els.print.addEventListener("click", () => window.print());
els.theme.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(theme);
  store.set(THEME_KEY, theme);
});

els.dialog.addEventListener("click", (event) => {
  if (event.target === els.dialog) els.dialog.close(); // клик по фону
});

setInterval(updateTimeline, 60_000);

if (location.protocol === "file:") {
  $("app").hidden = true;
  $("file-help").hidden = false;
} else {
  document.documentElement.dataset.narrow = String(mobile.matches);
  syncTheme();
  els.theme.hidden = false;
  els.source.value = store.get(STORAGE_KEY) ?? "";
  setEditorOpen(!mobile.matches || !els.source.value.trim());
  parse().then(() => {
    if (mobile.matches && !state.data?.lessons.length) setEditorOpen(true);
  });
}
