import { useEffect, useState } from "react";
import type { Coach } from "./App";
import { sportRequest } from "./admin-api";

export type ClubProfile = { name: string; city: string; description: string; phone: string; address?: string; email?: string };

function saveJson<T>(slug: string, path: string, body: object) {
  return sportRequest<T>(slug, path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

export function ClubSettings({ slug, profile, onSaved }: { slug: string; profile: ClubProfile; onSaved: (value: ClubProfile) => void }) {
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  return <section><h1 className="adm-h">Мой клуб</h1>
    <form className="admin-editor" onSubmit={async (event) => {
      event.preventDefault();
      const fields = new FormData(event.currentTarget);
      const values = Object.fromEntries(fields);
      setSaving(true);
      setStatus("");
      try {
        const result = await saveJson<{ organization: ClubProfile }>(slug, "/manage/profile", {
          ...values, phone: values.phone || undefined, email: values.email || undefined,
        });
        onSaved(result.organization);
        setStatus("Настройки клуба сохранены.");
      } catch (error) {
        setStatus(error instanceof Error ? error.message : "Не удалось сохранить настройки.");
      } finally {
        setSaving(false);
      }
    }}>
      <fieldset disabled={saving}><div className="admin-editor-grid">
        <label>Название<input name="name" defaultValue={profile.name} required minLength={2} maxLength={160} /></label>
        <label>Адрес<input name="address" defaultValue={profile.address ?? ""} maxLength={300} /></label>
        <label>Телефон<input name="phone" type="tel" defaultValue={profile.phone ?? ""} maxLength={24} /></label>
        <label>Электронная почта<input name="email" type="email" defaultValue={profile.email ?? ""} /></label>
        <label className="admin-editor-wide">Описание<textarea name="description" rows={5} maxLength={4000} defaultValue={profile.description} /></label>
      </div><div className="admin-form-actions"><button className="btn btn-black" type="submit">Сохранить</button></div></fieldset>
      {status && <p role="status">{status}</p>}
    </form>
  </section>;
}

type Review = { id: number; author: string; rating: number; comment: string; admin_response: string | null };

export function ClubReviews({ slug }: { slug: string }) {
  const [reviews, setReviews] = useState<Review[] | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    sportRequest<Review[]>(slug, "/reviews", { signal: controller.signal }).then(setReviews).catch((error) => {
      if (!controller.signal.aborted) setError(error.message);
    });
    return () => controller.abort();
  }, [slug]);
  return <section><h1 className="adm-h">Отзывы</h1>
    {error && <p className="sport-admin-alert" role="alert">{error}</p>}
    {!error && !reviews && <p role="status">Загружаем отзывы…</p>}
    {reviews?.length === 0 && <p>Отзывов пока нет.</p>}
    {reviews?.map((review) => <form className="admin-editor" key={review.id} onSubmit={async (event) => {
      event.preventDefault();
      const answer = String(new FormData(event.currentTarget).get("answer")).trim();
      if (!answer || saving) return;
      setSaving(true);
      setError("");
      try {
        const result = await saveJson<{ admin_response: string }>(slug, `/reviews/${review.id}/reply`, { admin_response: answer });
        setReviews((previous) => previous?.map((item) => item.id === review.id ? { ...item, admin_response: result.admin_response } : item) ?? []);
      } catch (error) {
        setError(error instanceof Error ? error.message : "Не удалось сохранить ответ.");
      } finally {
        setSaving(false);
      }
    }}>
      <h2 className="adm-sub">{review.author} · {review.rating}/5</h2>
      <p>{review.comment}</p>
      <fieldset disabled={saving}><div className="admin-editor-grid">
        <label>Ответ клуба<textarea name="answer" rows={3} required maxLength={2000} defaultValue={review.admin_response ?? ""} /></label>
      </div><div className="admin-form-actions"><button className="btn btn-black" type="submit">Сохранить ответ</button></div></fieldset>
    </form>)}
  </section>;
}

type Payroll = {
  commission_percent: number; base_rate: number; bonus: number; notes: string;
  total_sessions: number; total_revenue: number; total_payout: number;
};

export function CoachPayroll({ slug, coaches, canEdit }: { slug: string; coaches: Coach[]; canEdit: boolean }) {
  const [selected, setSelected] = useState(coaches[0]?.id ?? 0);
  return <section><h1 className="adm-h">{canEdit ? "Вознаграждения" : "Моё вознаграждение"}</h1>
    {canEdit && <div className="filters"><select aria-label="Тренер" value={selected} onChange={(event) => setSelected(Number(event.target.value))}>
      {coaches.map((coach) => <option key={coach.id} value={coach.id}>{coach.name}</option>)}
    </select></div>}
    {selected ? <PayrollDetails key={selected} slug={slug} coachId={selected} canEdit={canEdit} /> : <p>Тренеров пока нет.</p>}
  </section>;
}

function PayrollDetails({ slug, coachId, canEdit }: { slug: string; coachId: number; canEdit: boolean }) {
  const [summary, setSummary] = useState<Payroll | null>(null);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const path = `/coaches/${coachId}/payroll`;
  useEffect(() => {
    const controller = new AbortController();
    sportRequest<Payroll>(slug, `${path}/summary`, { signal: controller.signal }).then(setSummary).catch((error) => {
      if (!controller.signal.aborted) setStatus(error.message);
    });
    return () => controller.abort();
  }, [slug, path]);
  return <>
    {status && <p role="status">{status}</p>}
    {!status && !summary && <p role="status">Загружаем расчёт…</p>}
    {summary && <div className="kpis kpis-3">
      <div className="kpi"><span>Учтено записей</span><b>{summary.total_sessions}</b></div>
      <div className="kpi"><span>Сумма записей</span><b>{summary.total_revenue.toLocaleString("ru-RU")} ₽</b></div>
      <div className="kpi"><span>К выплате по расчёту</span><b>{summary.total_payout.toLocaleString("ru-RU")} ₽</b></div>
    </div>}
    {summary && canEdit && <form className="admin-editor" onSubmit={async (event) => {
      event.preventDefault();
      const fields = new FormData(event.currentTarget);
      setSaving(true);
      setStatus("");
      try {
        await saveJson(slug, path, {
          commission_percent: Number(fields.get("commission_percent")),
          base_rate_per_session: Number(fields.get("base_rate_per_session")),
          bonus: Number(fields.get("bonus")), notes: fields.get("notes"),
        });
        setSummary(await sportRequest<Payroll>(slug, `${path}/summary`));
        setStatus("Условия вознаграждения сохранены.");
      } catch (error) {
        setStatus(error instanceof Error ? error.message : "Не удалось сохранить условия.");
      } finally {
        setSaving(false);
      }
    }}>
      <fieldset disabled={saving}><div className="admin-editor-grid">
        <label>Комиссия, %<input type="number" name="commission_percent" min={0} max={100} required defaultValue={summary.commission_percent} /></label>
        <label>Ставка за занятие, ₽<input type="number" name="base_rate_per_session" min={0} required defaultValue={summary.base_rate} /></label>
        <label>Бонус, ₽<input type="number" name="bonus" min={0} required defaultValue={summary.bonus} /></label>
        <label>Примечание<input name="notes" maxLength={255} defaultValue={summary.notes} /></label>
      </div><div className="admin-form-actions"><button className="btn btn-black" type="submit">Сохранить условия</button></div></fieldset>
    </form>}
  </>;
}
