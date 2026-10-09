// 周目录契约的唯一计算入口。
// 目录与文件名面向人，使用日期范围；ISO 周数只作为机器元数据。

const DAY_MS = 24 * 60 * 60 * 1000;

function pad(value) {
  return String(value).padStart(2, '0');
}

export function parseDateOnly(input) {
  if (input instanceof Date) {
    return new Date(Date.UTC(input.getFullYear(), input.getMonth(), input.getDate()));
  }
  const text = String(input || '').trim();
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) {
    throw new Error(`invalid date, expected YYYY-MM-DD: ${text}`);
  }
  const [, year, month, day] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (
    date.getUTCFullYear() !== Number(year) ||
    date.getUTCMonth() !== Number(month) - 1 ||
    date.getUTCDate() !== Number(day)
  ) {
    throw new Error(`invalid calendar date: ${text}`);
  }
  return date;
}

export function formatDateOnly(date) {
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

export function mondayOf(input) {
  const date = parseDateOnly(input);
  // getUTCDay(): 0=Sunday .. 6=Saturday; 复盘周固定为周一到周日
  const offset = (date.getUTCDay() + 6) % 7;
  return new Date(date.getTime() - offset * DAY_MS);
}

export function isoWeek(input) {
  const monday = mondayOf(input);
  const thursday = new Date(monday.getTime() + 3 * DAY_MS);
  const isoYear = thursday.getUTCFullYear();
  const firstThursday = new Date(Date.UTC(isoYear, 0, 4));
  const firstMonday = mondayOf(formatDateOnly(firstThursday));
  const week = Math.round((monday.getTime() - firstMonday.getTime()) / (7 * DAY_MS)) + 1;
  return { isoYear, isoWeekNumber: week, label: `${isoYear}-W${pad(week)}` };
}

export function weekLabel(weekStart, weekEnd) {
  const start = parseDateOnly(weekStart);
  const end = parseDateOnly(weekEnd);
  const startText = formatDateOnly(start);
  if (start.getUTCFullYear() === end.getUTCFullYear()) {
    return `${startText} 至 ${pad(end.getUTCMonth() + 1)}-${pad(end.getUTCDate())}`;
  }
  return `${startText} 至 ${formatDateOnly(end)}`;
}

export function resolveWeek(input) {
  const monday = mondayOf(input);
  const sunday = new Date(monday.getTime() + 6 * DAY_MS);
  const weekStart = formatDateOnly(monday);
  const weekEnd = formatDateOnly(sunday);
  const iso = isoWeek(weekStart);
  const label = weekLabel(weekStart, weekEnd);
  return {
    week_start: weekStart,
    week_end: weekEnd,
    iso_week: iso.label,
    iso_year: iso.isoYear,
    iso_week_number: iso.isoWeekNumber,
    // 归档年月固定取 week_start，跨月周不产生第二个候选目录
    archive_year: String(monday.getUTCFullYear()),
    archive_month: pad(monday.getUTCMonth() + 1),
    week_label: label,
    week_dir_name: label,
    report_file_name: `${label} 周复盘.md`,
  };
}

export function weekDirRelativePath(input, archiveRelativeDir = '工作/周报') {
  const week = resolveWeek(input);
  const base = String(archiveRelativeDir).replace(/^\/+|\/+$/g, '');
  return `${base}/${week.archive_year}/${week.archive_month}/${week.week_dir_name}`;
}

export function isWeekDirName(name) {
  const same = /^\d{4}-\d{2}-\d{2} 至 \d{2}-\d{2}$/;
  const cross = /^\d{4}-\d{2}-\d{2} 至 \d{4}-\d{2}-\d{2}$/;
  return same.test(String(name)) || cross.test(String(name));
}

export function reportFileNameForWeekDir(name) {
  if (!isWeekDirName(name)) {
    throw new Error(`not a week dir name: ${name}`);
  }
  return `${name} 周复盘.md`;
}
