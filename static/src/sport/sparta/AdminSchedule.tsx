import { useEffect, useRef, useState } from "react";
import type { Booking, Coach, Discipline, Gym, Training } from "./App";
import { calendarDate, dateKey, WEEKDAYS } from "./admin-api";
import { sportRequest } from "./admin-api";

type Closure = { id: number; coach_id: number | null; venue_id: number | null; date: string; reason: string };

type ScheduleProps = {
  slug: string;
  current: string;
  role: string;
  gyms: Gym[];
  coaches: Coach[];
  disciplines: Discipline[];
  bookings: Booking[];
  trainings: Training[];
  exceptions: Record<string, boolean>;
  onTraining: (item: Training) => Promise<void>;
  onException: (key: string, enabled: boolean) => Promise<void>;
};

const ALL = "all";
const DAYS = [1, 2, 3, 4, 5, 6, 0];

function moveDate(date: string, days: number) {
  const result = calendarDate(date);
  result.setDate(result.getDate() + days);
  return dateKey(result);
}

export default function AdminSchedule({ slug, current, role, gyms, coaches, disciplines, bookings, trainings, exceptions, onTraining, onException }: ScheduleProps) {
  const [date, setDate] = useState(current);
  const [gym, setGym] = useState(ALL);
  const [coach, setCoach] = useState(ALL);
  const [editing, setEditing] = useState<{ item: Training; isNew: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [closures, setClosures] = useState<Closure[]>([]);
  const [vacationCoach, setVacationCoach] = useState("");
  const [vacationFrom, setVacationFrom] = useState(current);
  const [vacationTo, setVacationTo] = useState(current);
  const [vacationMessage, setVacationMessage] = useState("");
  useEffect(() => {
    sportRequest<Closure[]>(slug, "/closures").then(setClosures).catch(() => {});
  }, [slug]);
  const addVacation = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!vacationCoach || vacationTo < vacationFrom) return;
    if (!window.confirm("Оформить отпуск? Занятия на выбранные даты отменятся, существующие записи будут отменены. Клиентов нужно уведомить.")) return;
    await persist(async () => {
      const result = await sportRequest<{ cancelled_bookings: number }>(slug, "/closures", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ coach_id: Number(vacationCoach), date: vacationFrom, date_to: vacationTo, reason: "Отпуск" }),
      });
      setClosures(await sportRequest<Closure[]>(slug, "/closures"));
      setVacationMessage(`Отпуск сохранён. Отменено записей: ${result.cancelled_bookings}. Сообщите клиентам об отмене.`);
    });
  };
  const selectedDay = (calendarDate(date).getDay() + 6) % 7;
  const monday = moveDate(date, -selectedDay);
  const dates = DAYS.map((_, i) => moveDate(monday, i));
  const shown = trainings.filter((item) => (gym === ALL || item.gym === gym) && (coach === ALL || item.coach === coach));
  const dateLabel = (value: string) => calendarDate(value).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
  const scheduleLabel = `${dateLabel(dates[0])} — ${dateLabel(dates[6])}`;
  const activeCoaches = Array.from(new Set([...coaches.map((item) => item.name), ...trainings.map((item) => item.coach)])).filter(Boolean);

  const addTraining = () => {
    setError("");
    const id = crypto.randomUUID?.() ?? `training-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setEditing({ isNew: true, item: { id, days: [], time: "", end: "", active: true,
      gym: "", coach: "", discipline: "", color: "#c72527" } });
  };

  const editTraining = (item: Training) => {
    setError("");
    setEditing({ item, isNew: false });
  };

  async function persist(save: () => Promise<void>, afterSave?: () => void) {
    setSaving(true);
    setError("");
    try {
      await save();
      afterSave?.();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось сохранить расписание");
    } finally {
      setSaving(false);
    }
  }

  return <section aria-labelledby="admin-schedule-title">
    <div className="adm-top"><h1 id="admin-schedule-title" className="adm-h">Расписание</h1>
      {role !== "trainer" && <button className="btn btn-black" disabled={saving} onClick={addTraining}>Новая тренировка</button>}
    </div>
    {!editing && error && <p className="sport-admin-alert" role="alert">{error}</p>}
    {role !== "trainer" && <form className="admin-vacation" onSubmit={(event) => void addVacation(event)}>
      <h2>Отпуск тренера</h2>
      <label>Тренер<select required value={vacationCoach} onChange={(event) => setVacationCoach(event.target.value)}><option value="">Выберите тренера</option>{coaches.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>С<input required type="date" min={current} value={vacationFrom} onChange={(event) => setVacationFrom(event.target.value)} /></label>
      <label>По<input required type="date" min={vacationFrom} value={vacationTo} onChange={(event) => setVacationTo(event.target.value)} /></label>
      <button className="btn btn-black" disabled={saving}>Отменить занятия на период</button>
      <p>Занятия тренера в эти даты станут недоступны для записи. Записанных клиентов нужно уведомить.</p>
      {vacationMessage && <p role="status">{vacationMessage}</p>}
    </form>}
    {closures.filter((item) => item.reason === "Отпуск").length > 0 && <details className="admin-vacation-list"><summary>Дни отпуска ({closures.filter((item) => item.reason === "Отпуск").length})</summary><div>{closures.filter((item) => item.reason === "Отпуск").map((item) => <div key={item.id}><span>{item.date} · {coaches.find((coach) => coach.id === item.coach_id)?.name || "Тренер"}</span>{role !== "trainer" && <button type="button" disabled={saving} onClick={() => { if (!window.confirm("Убрать день отпуска и вернуть занятия в расписание?")) return; void persist(async () => { await sportRequest(slug, `/closures/${item.id}`, { method: "DELETE" }); setClosures(await sportRequest<Closure[]>(slug, "/closures")); }); }}>Убрать</button>}</div>)}</div></details>}
    {editing && <TrainingEditor item={editing.item} isNew={editing.isNew} gyms={gyms} coaches={coaches} disciplines={disciplines} readOnlyCoach={role === "trainer"}
      saving={saving} saveError={error} cancel={() => { setEditing(null); setError(""); }} onSave={(item) => void persist(() => onTraining(item), () => {
        setEditing(null);
        if (gym !== ALL && item.gym !== gym) setGym(item.gym);
        if (coach !== ALL && item.coach !== coach) setCoach(item.coach);
      })} />}
    <div className="admin-schedule-toolbar">
      <div className="calendar-controls">
        <button aria-label="Предыдущая неделя" onClick={() => setDate(moveDate(date, -7))}>‹</button>
        <span aria-live="polite">{scheduleLabel}</span>
        <button aria-label="Следующая неделя" onClick={() => setDate(moveDate(date, 7))}>›</button>
        <button className="admin-secondary" onClick={() => setDate(current)}>Сегодня</button>
      </div>
      <div className="filters">
        <select aria-label="Зал" value={gym} onChange={(event) => setGym(event.target.value)}>
          <option value={ALL}>Все залы</option>{gyms.map((item) => <option key={item.id}>{item.address}</option>)}
        </select>
        {role !== "trainer" && <select aria-label="Тренер" value={coach} onChange={(event) => setCoach(event.target.value)}>
          <option value={ALL}>Все тренеры</option>{activeCoaches.map((name) => <option key={name}>{name}</option>)}
        </select>}
      </div>
    </div>
    <div className="admin-schedule-days" aria-label="Дни недели">
      {dates.map((day, index) => <button className="admin-secondary" key={day} aria-pressed={day === date} onClick={() => setDate(day)}>
        {WEEKDAYS[index]} <span>{calendarDate(day).getDate()}</span>
      </button>)}
    </div>
    <div className="admin-schedule-week">
      {dates.map((day, index) => {
        const slots = shown.filter((item) => item.active && item.days.includes(DAYS[index])).sort((a, b) => a.time.localeCompare(b.time));
        return <section className={`week-day${day === date ? " admin-schedule-selected" : ""}`} key={day} aria-label={`${WEEKDAYS[index]}, ${dateLabel(day)}`}>
          <div className="week-day-head"><b>{WEEKDAYS[index]}</b><strong>{dateLabel(day)}</strong>{day === current && <span>Сегодня</span>}</div>
          {slots.length === 0 && <p className="week-empty">Нет занятий</p>}
          {slots.map((item) => {
            const key = `${day}:${item.id}`;
            const cancelled = exceptions[key] === false || closures.some((closed) => closed.date === day && (closed.coach_id === null || closed.coach_id === item.coachId || coaches.find((coach) => coach.id === closed.coach_id)?.name === item.coach) && closed.venue_id === null);
            const count = bookings.filter((booking) => booking.sessionId === item.id && booking.date === day && booking.status !== "cancelled").length;
            return <article className={`week-class${cancelled ? " week-class-off" : ""}`} style={{ borderLeft: `4px solid ${item.color || "#c72527"}` }} key={item.id}>
              <b>{item.time}–{item.end}</b><strong>{item.discipline}</strong><span>{item.coach}</span><span>{item.gym}</span>
              <small>{count ? `Записей: ${count}` : "Без записей"}</small>
              {cancelled && <small>Занятие отменено</small>}
              <button disabled={saving} onClick={() => editTraining(item)}>Изменить расписание</button>
              {role !== "trainer" && !closures.some((closed) => closed.date === day && (closed.coach_id === null || closed.coach_id === item.coachId || coaches.find((coach) => coach.id === closed.coach_id)?.name === item.coach) && closed.venue_id === null) && day >= current && <button disabled={saving} onClick={() => {
                const affected = count ? ` Записей: ${count}. Сообщите об отмене записанным клиентам.` : "";
                if (!cancelled && !window.confirm(`Вы точно хотите отменить занятие?${affected}`)) return;
                void persist(() => onException(key, cancelled));
              }}>{cancelled ? "Вернуть занятие" : "Отменить занятие"}</button>}
            </article>;
          })}
        </section>;
      })}
    </div>
    <h2 className="adm-sub">Регулярные тренировки</h2>
    {shown.length === 0 && <p className="admin-hint">Тренировок по выбранным фильтрам пока нет.</p>}
    <div className="admin-training-list">{shown.map((item) => <article className="admin-training" style={{ borderLeft: `4px solid ${item.color || "#c72527"}` }} key={item.id}>
      <div><b>{item.time}–{item.end}</b><strong>{item.discipline}</strong><span>{item.coach}</span><span>{item.gym}</span>
        <small>{WEEKDAYS.filter((_, index) => item.days.includes(DAYS[index])).join(", ")}</small></div>
      <div className="admin-training-actions"><button className="ghost" disabled={saving} onClick={() => editTraining(item)}>Изменить</button>
        <button disabled={saving || editing !== null} onClick={() => void persist(() => onTraining({ ...item, active: !item.active }))}>{item.active ? "Приостановить" : "Включить"}</button></div>
    </article>)}</div>
  </section>;
}

function TrainingEditor({ item, isNew, gyms, coaches, disciplines, readOnlyCoach, saving, saveError, cancel, onSave }: {
  item: Training; gyms: Gym[]; coaches: Coach[]; disciplines: Discipline[]; readOnlyCoach: boolean;
  isNew: boolean; saving: boolean; saveError: string; cancel: () => void; onSave: (item: Training) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState(item);
  const [error, setError] = useState("");
  useEffect(() => {
    const panel = dialog.current;
    panel?.showModal();
    return () => panel?.close();
  }, []);
  const set = <K extends keyof Training,>(field: K, value: Training[K]) => setDraft((previous) => ({ ...previous, [field]: value }));
  const options = (current: string, values: string[]) => Array.from(new Set([current, ...values])).filter(Boolean);
  return <dialog ref={dialog} className="admin-editor-dialog" aria-labelledby="training-editor-title" onCancel={(event) => {
    event.preventDefault();
    if (!saving && window.confirm("Вы точно хотите отменить редактирование? Несохранённые изменения пропадут.")) cancel();
  }}><form className="admin-editor" onSubmit={(event) => {
    event.preventDefault();
    if (saving) return;
    const discipline = draft.discipline.trim();
    if (!discipline) { setError("Укажите группу или направление."); return; }
    if (!draft.days.length) { setError("Выберите хотя бы один день недели."); return; }
    if (draft.time >= draft.end) { setError("Время окончания должно быть позже начала."); return; }
    setError("");
    onSave({ ...draft, discipline });
  }}>
    <h2 id="training-editor-title" className="adm-sub">{isNew ? "Новая тренировка" : "Изменить регулярную тренировку"}</h2>
    {!isNew && <p className="admin-hint">Изменения применятся к регулярному расписанию занятия.</p>}
    {(error || saveError) && <p className="sport-admin-alert" role="alert">{error || saveError}</p>}
    <fieldset disabled={saving}>
      <div className="admin-editor-grid">
        <label>Тренер<select required value={draft.coach} disabled={readOnlyCoach} onChange={(event) => set("coach", event.target.value)}>
          <option value="">Выберите тренера</option>{options(item.coach, coaches.map((row) => row.name)).map((name) => <option key={name}>{name}</option>)}
        </select></label>
        <label>Зал<select required value={draft.gym} onChange={(event) => set("gym", event.target.value)}>
          <option value="">Выберите зал</option>{options(item.gym, gyms.map((row) => row.address)).map((address) => <option key={address}>{address}</option>)}
        </select></label>
        <label>Группа или направление<input required maxLength={120} list="training-disciplines" value={draft.discipline}
          onChange={(event) => set("discipline", event.target.value)} /></label>
        <datalist id="training-disciplines">{disciplines.map((row) => <option key={row.key} value={row.key} />)}</datalist>
        <label>Начало<input type="time" value={draft.time} required onChange={(event) => set("time", event.target.value)} /></label>
        <label>Окончание<input type="time" value={draft.end} required onChange={(event) => set("end", event.target.value)} /></label>
        <label>Цвет тренировки<input type="color" value={draft.color || "#c72527"} onChange={(event) => set("color", event.target.value)} /></label>
        <fieldset className="admin-editor-wide"><legend>Дни недели</legend><div className="day-checks">{DAYS.map((day, index) => <label key={day}>
          <input type="checkbox" checked={draft.days.includes(day)} onChange={(event) => set("days", event.target.checked
            ? [...draft.days, day] : draft.days.filter((value) => value !== day))} />{WEEKDAYS[index]}</label>)}</div></fieldset>
        <label className="admin-check"><input type="checkbox" checked={draft.active} onChange={(event) => set("active", event.target.checked)} />Тренировка активна</label>
      </div>
      <div className="admin-form-actions"><button type="submit" className="btn btn-black">{saving ? "Сохраняем…" : "Сохранить"}</button>
        <button type="button" className="admin-secondary" onClick={() => {
          if (window.confirm("Вы точно хотите отменить редактирование? Несохранённые изменения пропадут.")) cancel();
        }}>Отмена</button></div>
    </fieldset>
  </form></dialog>;
}
