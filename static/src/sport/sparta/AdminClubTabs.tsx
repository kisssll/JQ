import { useEffect, useState } from "react";
import type { Coach } from "./App";
import { sportRequest } from "./admin-api";

export type ClubProfile = {
  name: string; city: string; description: string;
  phone: string | null; address?: string | null; email?: string | null;
  logo_url?: string | null; cover_url?: string | null;
  vk_url?: string | null; telegram_url?: string | null;
};

type SiteItem = {
  id: number; name?: string; address?: string; description?: string; hours?: string;
  photo_url?: string | null; level?: string; code?: string; price?: number;
  unit?: string; items?: string[]; featured?: boolean; alt_text?: string; image_url?: string;
};
type SiteSection = "venues" | "disciplines" | "plans" | "gallery";
export type SiteCatalog = Record<SiteSection, SiteItem[]>;
export const EMPTY_SITE_CATALOG: SiteCatalog = { venues: [], disciplines: [], plans: [], gallery: [] };
const SECTION_LABELS: Record<SiteSection, string> = { venues: "Залы", disciplines: "Направления", plans: "Цены и абонементы", gallery: "Галерея" };

async function uploadSitePhoto(slug: string, fields: FormData, name: string): Promise<string | null> {
  const file = fields.get(`${name}_file`);
  if (file instanceof File && file.size > 0) {
    const body = new FormData();
    body.append("photo", file);
    return (await sportRequest<{ url: string }>(slug, "/manage/site-photo", { method: "POST", body })).url;
  }
  return String(fields.get(name) ?? "").trim() || null;
}

function SitePhotoField({ name, label, url }: { name: string; label: string; url?: string | null }) {
  const [value, setValue] = useState(url ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  useEffect(() => {
    if (!file || !file.type.startsWith("image/")) return;
    const local = URL.createObjectURL(file);
    setPreview(local);
    return () => URL.revokeObjectURL(local);
  }, [file]);
  const image = preview || (/^(https?:\/\/|\/(uploads|photos|static)\/)/i.test(value) ? value : "");
  return <div className="admin-site-photo">
    <label>{label}<input name={name} value={value} onChange={(event) => setValue(event.target.value)} placeholder="Загрузите файл или вставьте ссылку" maxLength={500} /></label>
    <label>Выбрать файл<input name={`${name}_file`} type="file" accept="image/*,.heic,.heif" onChange={(event) => {
      setPreview("");
      setFile(event.target.files?.[0] ?? null);
    }} /></label>
    {image && <img src={image} alt={`Предпросмотр: ${label}`} />}
  </div>;
}

function saveJson<T>(slug: string, path: string, body: object) {
  return sportRequest<T>(slug, path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

export function ClubSettings({ slug, profile, catalog, onSaved, onCatalogSaved }: {
  slug: string; profile: ClubProfile; catalog: SiteCatalog; onSaved: (value: ClubProfile) => void; onCatalogSaved: (value: SiteCatalog) => void;
}) {
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  return <section><h1 className="adm-h">Мой клуб</h1>
    <p className="admin-hint">Сохранённые изменения видны на публичной странице клуба.</p>
    <form className="admin-editor" key={JSON.stringify(profile)} onSubmit={async (event) => {
      event.preventDefault();
      const fields = new FormData(event.currentTarget);
      const value = (name: string) => String(fields.get(name) ?? "").trim();
      setSaving(true);
      setStatus("");
      try {
        const [logo_url, cover_url] = await Promise.all([
          uploadSitePhoto(slug, fields, "logo_url"), uploadSitePhoto(slug, fields, "cover_url"),
        ]);
        const result = await saveJson<{ organization: ClubProfile }>(slug, "/manage/profile", {
          name: value("name"), description: value("description"), address: value("address"),
          phone: value("phone") || null, email: value("email") || null,
          vk_url: value("vk_url") || null, telegram_url: value("telegram_url") || null,
          logo_url, cover_url,
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
        <label>Сообщество ВКонтакте<input name="vk_url" type="url" defaultValue={profile.vk_url ?? ""} placeholder="https://vk.com/..." maxLength={500} /></label>
        <label>Канал или группа Telegram<input name="telegram_url" type="url" defaultValue={profile.telegram_url ?? ""} placeholder="https://t.me/..." maxLength={500} /></label>
        <SitePhotoField name="logo_url" label="Логотип" url={profile.logo_url} />
        <SitePhotoField name="cover_url" label="Фото на главной" url={profile.cover_url} />
      </div><div className="admin-form-actions"><button className="btn btn-black" type="submit">Сохранить</button></div></fieldset>
      {status && <p role="status">{status}</p>}
    </form>
    <SiteCatalogEditor slug={slug} catalog={catalog} onSaved={onCatalogSaved} />
  </section>;
}

function SiteCatalogEditor({ slug, catalog, onSaved }: { slug: string; catalog: SiteCatalog; onSaved: (value: SiteCatalog) => void }) {
  const [editor, setEditor] = useState<{ section: SiteSection; item?: SiteItem } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function mutate(path: string, method: string, body?: object) {
    await sportRequest(slug, `/manage/${path}`, {
      method,
      ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
    });
    try {
      onSaved(await sportRequest<SiteCatalog>(slug, "/manage"));
      return "Изменения сохранены.";
    } catch {
      return "Изменения сохранены. Обновите страницу, чтобы увидеть актуальный список.";
    }
  }

  async function perform(action: () => Promise<string>) {
    setBusy(true);
    setMessage("");
    try {
      const result = await action();
      setEditor(null);
      setMessage(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось сохранить изменения.");
    } finally {
      setBusy(false);
    }
  }

  const field = (name: string, label: string, value?: string, required = false, maxLength = 160) =>
    <label>{label}<input name={name} required={required} defaultValue={value ?? ""} maxLength={maxLength} /></label>;
  return <section aria-label="Контент сайта">
    {message && <p role="status">{message}</p>}
    {(Object.entries(SECTION_LABELS) as [SiteSection, string][]).map(([section, title]) => <div className="admin-editor" key={section}>
      <div className="admin-site-item"><h2 className="adm-sub">{title}</h2><button className="admin-secondary" disabled={busy || !!editor || (section === "gallery" && catalog.gallery.length >= 16)} onClick={() => setEditor({ section })}>Добавить</button></div>
      {section === "gallery" && <p className="admin-hint">{catalog.gallery.length} из 16 фото · файл до 5 МБ</p>}
      <div className="admin-site-photo-strip">{catalog[section].map((item) => <div className="admin-site-item" key={item.id}>
        {(item.image_url || item.photo_url) && <img className="admin-site-thumb" src={item.image_url || item.photo_url || ""} alt="" loading="lazy" />}
        <span>{item.name || item.alt_text || "Фотография"}</span>
        <div className="admin-form-actions">
          <button className="admin-secondary" disabled={busy || !!editor} onClick={() => setEditor({ section, item })}>Изменить</button>
          <button className="admin-text-button" disabled={busy || !!editor} onClick={() => {
            if (window.confirm("Убрать эту карточку с сайта?")) void perform(() => mutate(`${section}/${item.id}`, "DELETE"));
          }}>Убрать с сайта</button>
        </div>
      </div>)}
      </div>
      {editor?.section === section && <form className="admin-site-item-editor" onSubmit={(event) => {
        event.preventDefault();
        const fields = new FormData(event.currentTarget);
        const value = (name: string) => String(fields.get(name) ?? "").trim();
        void perform(async () => {
          const item = editor.item;
          const body = section === "gallery"
            ? { image_url: await uploadSitePhoto(slug, fields, "image_url"), alt_text: value("alt_text") }
            : section === "plans"
              ? { name: value("name"), price: Number(value("price")), unit: value("unit"), items: value("items").split(/\r?\n/).map(line => line.trim()).filter(Boolean), code: item?.code ?? crypto.randomUUID(), featured: item?.featured ?? false }
              : { name: value("name"), description: value("description"), photo_url: await uploadSitePhoto(slug, fields, "photo_url"),
                  ...(section === "venues" ? { address: value("address"), hours: value("hours") } : { level: item?.level ?? "" }) };
          if (section === "gallery" && !("image_url" in body && body.image_url)) throw new Error("Выберите фотографию или укажите ссылку.");
          return mutate(item ? `${section}/${item.id}` : section, item ? "PUT" : "POST", body);
        });
      }}>
        <fieldset disabled={busy}>
          <div className="admin-editor-grid">
            {section !== "gallery" && field("name", "Название", editor.item?.name, true, section === "venues" ? 160 : 120)}
            {section === "venues" && <>{field("address", "Адрес", editor.item?.address, true, 300)}{field("hours", "Часы работы", editor.item?.hours)}</>}
            {(section === "venues" || section === "disciplines") && <>
              <label>Описание<textarea name="description" rows={3} maxLength={2000} defaultValue={editor.item?.description} /></label>
              <SitePhotoField name="photo_url" label="Фото карточки" url={editor.item?.photo_url} />
            </>}
            {section === "plans" && <>
              <label>Цена, ₽<input type="number" name="price" min={0} max={2147483647} required defaultValue={editor.item?.price} /></label>
              {field("unit", "Подпись цены", editor.item?.unit, false, 80)}
              <label>Условия, по одному на строку<textarea name="items" rows={3} defaultValue={editor.item?.items?.join("\n")} /></label>
            </>}
            {section === "gallery" && <>
              {field("alt_text", "Подпись фотографии", editor.item?.alt_text, false, 200)}
              <SitePhotoField name="image_url" label="Фото для галереи" url={editor.item?.image_url} />
            </>}
          </div>
          <div className="admin-form-actions"><button className="btn btn-black" type="submit">Сохранить</button><button className="admin-secondary" type="button" onClick={() => setEditor(null)}>Отмена</button></div>
        </fieldset>
      </form>}
    </div>)}
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
