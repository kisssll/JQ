import { useEffect, useState } from "react";
import { ADMIN_PAGE_SIZE, calendarDate, dateKey, sportRequest, WEEKDAYS } from "./admin-api";

type Client = {
  id: number;
  name: string;
  contact: string;
  phone: string;
  participant: "self" | "child";
  visits: number;
  last_visit: string | null;
};
type Visit = { id: number; name: string; date: string | null; time: string; gym: string; discipline: string; coach: string };
type VisitPage = { visits: Visit[]; has_more: boolean };

function useSportPage<T>(slug: string, path: string | null) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ path: string; data?: T; error?: string }>();
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setResult(undefined);
    void sportRequest<T>(slug, path, { signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setResult({ path, data });
    }).catch((error: Error) => {
      if (!controller.signal.aborted) setResult({ path, error: error.message });
    });
    return () => controller.abort();
  }, [slug, path, attempt]);
  return { ...((path === result?.path && result) || {}), retry: () => setAttempt((value) => value + 1) };
}

function shortDate(value: string | null) {
  return value ? calendarDate(value).toLocaleDateString("ru-RU") : "—";
}

function Calendar({ current, month, day, counts, changeMonth, selectDay }: {
  current: string; month: string; day: string; counts: Record<string, number>;
  changeMonth: (month: string) => void; selectDay: (day: string) => void;
}) {
  const first = calendarDate(month);
  const year = first.getFullYear();
  const index = first.getMonth();
  const leading = (first.getDay() + 6) % 7;
  const length = new Date(year, index + 1, 0).getDate();
  return <aside className="admin-mini-calendar" aria-label="Календарь посещений">
    <div className="admin-calendar-nav">
      <button type="button" aria-label="Предыдущий месяц" onClick={() => changeMonth(dateKey(new Date(year, index - 1, 1)))}>‹</button>
      <h2>{first.toLocaleDateString("ru-RU", { month: "long", year: "numeric" })}</h2>
      <button type="button" aria-label="Следующий месяц" onClick={() => changeMonth(dateKey(new Date(year, index + 1, 1)))}>›</button>
    </div>
    <div className="admin-mini-grid">
      {WEEKDAYS.map((weekday) => <span className="admin-mini-weekday" key={weekday}>{weekday}</span>)}
      {Array.from({ length: leading }, (_, i) => <span aria-hidden="true" key={`empty-${i}`} />)}
      {Array.from({ length }, (_, i) => {
        const date = dateKey(new Date(year, index, i + 1));
        const count = counts[date] ?? 0;
        return <button key={date} type="button" aria-current={date === current ? "date" : undefined}
          aria-pressed={date === day} aria-label={`${shortDate(date)}${count ? `, посещений: ${count}` : ""}`}
          onClick={() => selectDay(date)}>
          {i + 1}{count > 0 && <span className="admin-visit-dot" aria-hidden="true" />}
        </button>;
      })}
    </div>
    <button className="admin-text-button" type="button" onClick={() => { changeMonth(`${current.slice(0, 7)}-01`); selectDay(current); }}>Сегодня</button>
  </aside>;
}

function VisitTable({ visits, selectClient }: { visits: Visit[]; selectClient?: (id: number, name: string) => void }) {
  return <div className="admin-table-scroll"><table className="admin-data-table admin-visit-table">
    <thead><tr>{selectClient && <th scope="col">Клиент</th>}<th scope="col">Зал</th><th scope="col">Дата</th><th scope="col">Время</th><th scope="col">Тренировка</th></tr></thead>
    <tbody>{visits.map((visit) => <tr key={visit.id}>
      {selectClient && <td><button className="admin-text-button" onClick={() => selectClient(visit.id, visit.name)}>{visit.name}</button></td>}
      <td>{visit.gym || "—"}</td><td>{shortDate(visit.date)}</td><td>{visit.time || "—"}</td>
      <td>{visit.discipline || "—"}{visit.coach && <small>{visit.coach}</small>}</td>
    </tr>)}</tbody>
  </table></div>;
}

function Pagination({ offset, more, onChange }: { offset: number; more?: boolean; onChange: (offset: number) => void }) {
  if (!offset && !more) return null;
  return <div className="admin-pagination" aria-label="Страницы списка">
    <button className="admin-secondary" disabled={!offset} onClick={() => onChange(offset - ADMIN_PAGE_SIZE)}>Назад</button>
    <span>Страница {offset / ADMIN_PAGE_SIZE + 1}</span>
    <button className="admin-secondary" disabled={!more} onClick={() => onChange(offset + ADMIN_PAGE_SIZE)}>Далее</button>
  </div>;
}

function DataMessage({ error, retry }: { error?: string; retry: () => void }) {
  return error ? <div className="admin-data-message" role="alert">{error} <button className="admin-text-button" onClick={retry}>Повторить</button></div>
    : <p className="admin-data-message" role="status">Загружаем данные…</p>;
}

export default function AdminClients({ slug, current }: { slug: string; current: string }) {
  const [month, setMonth] = useState(`${current.slice(0, 7)}-01`);
  const [day, setDay] = useState("");
  const [search, setSearch] = useState("");
  const [client, setClient] = useState<{ id: number; name: string } | null>(null);
  const [offset, setOffset] = useState(0);
  const pagination = `offset=${offset}&limit=${ADMIN_PAGE_SIZE}`;
  const selection = client ? `client=${client.id}` : day ? `day=${day}` : "";
  const clients = useSportPage<{ clients: Client[]; has_more: boolean }>(slug, selection ? null : `/manage/clients?${pagination}&search=${encodeURIComponent(search)}`);
  const visits = useSportPage<VisitPage>(slug, selection ? `/manage/visits?${selection}&${pagination}` : null);
  const calendar = useSportPage<{ counts: Record<string, number> }>(slug, `/manage/visits/calendar?month=${month}`);
  const openClient = (id: number, name: string) => { setClient({ id, name }); setOffset(0); };
  const selectDay = (date: string) => { setDay(date); setClient(null); setOffset(0); };

  return <section aria-labelledby="admin-clients-title">
    <h1 id="admin-clients-title" className="adm-h">Клиенты</h1>
    <div className="admin-clients-layout">
      <div className="admin-calendar-pane">
        <Calendar current={current} month={month} day={day} counts={calendar.data?.counts ?? {}}
          changeMonth={setMonth} selectDay={selectDay} />
        {calendar.error && <DataMessage error={calendar.error} retry={calendar.retry} />}
      </div>
      <section className="admin-data-panel" aria-label={client ? "История посещений клиента" : day ? "Посещения за день" : "Список клиентов"}>
        <div className="admin-data-head">
          {(day || client) && <button className="admin-text-button" onClick={() => { setDay(""); setClient(null); setOffset(0); }}>Все клиенты</button>}
          {client && day && <button className="admin-text-button" onClick={() => { setClient(null); setOffset(0); }}>К посещениям {shortDate(day)}</button>}
          <h2 className="adm-sub">{client?.name ?? (day ? `Посещения ${shortDate(day)}` : "Все клиенты")}</h2>
          {client && <p className="admin-hint">История посещений клуба</p>}
          {!day && !client && <input className="record-search" type="search" aria-label="Поиск клиентов" placeholder="Имя или телефон"
            maxLength={160} value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} />}
        </div>
        {selection ? <>
          {!visits.data ? <DataMessage error={visits.error} retry={visits.retry} /> : visits.data.visits.length > 0
            ? <VisitTable visits={visits.data.visits} selectClient={client ? undefined : openClient} />
            : <p className="admin-data-message">Отмеченных посещений пока нет.</p>}
          <Pagination offset={offset} more={visits.data?.has_more} onChange={setOffset} />
        </> : <>
          {!clients.data ? <DataMessage error={clients.error} retry={clients.retry} /> : clients.data.clients.length > 0
            ? <div className="admin-table-scroll"><table className="admin-data-table admin-directory-table">
              <colgroup><col /><col /><col /><col /></colgroup>
              <thead><tr><th scope="col">Клиент</th><th scope="col">Телефон</th><th scope="col">Визиты</th><th scope="col">Последний визит</th></tr></thead>
              <tbody>{clients.data.clients.map((row) => <tr key={row.id}>
                <td><button className="admin-text-button" onClick={() => openClient(row.id, row.name)}>{row.name}</button>
                  {row.participant === "child" && <small>Контакт: {row.contact}</small>}</td>
                <td><a href={`tel:${row.phone}`}>{row.phone}</a></td><td>{row.visits}</td><td>{shortDate(row.last_visit)}</td>
              </tr>)}</tbody>
            </table></div>
            : <p className="admin-data-message">{search ? "По этому запросу клиентов нет." : "Клиенты появятся после первой заявки."}</p>}
          <Pagination offset={offset} more={clients.data?.has_more} onChange={setOffset} />
        </>}
      </section>
    </div>
  </section>;
}
