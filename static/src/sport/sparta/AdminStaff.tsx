import { useEffect, useRef, useState } from "react";
import { sportRequest, SportRequestError } from "./admin-api";

const ROLE_LABELS = { owner: "Совладелец", manager: "Управляющий", admin: "Администратор", trainer: "Тренер" };
const PERMISSION_LABELS = {
  manage_gym: "Настройки клуба",
  manage_managers: "Управляющие",
  manage_admins: "Администраторы",
  manage_coaches: "Тренеры и услуги",
  manage_schedule: "Расписание",
  manage_bookings: "Записи и клиенты",
  manage_reviews: "Отзывы",
  view_finances: "Финансы и оплаты",
  manage_payroll: "Вознаграждение тренеров",
};
export type SportPermissions = Partial<Record<keyof typeof PERMISSION_LABELS | "manage_owners", boolean>>;
const ROLE_PERMISSIONS = { owner: "manage_owners", manager: "manage_managers", admin: "manage_admins", trainer: "manage_coaches" } as const;
type Credentials = { name: string; login: string; password: string };

export type StaffMember = {
  id: number;
  role: keyof typeof ROLE_LABELS;
  name: string;
  phone: string;
  hasAccount?: boolean;
  photo?: string | null;
  about: string;
  title?: string;
  experience?: string;
  tags?: string;
  permissions?: SportPermissions;
  isCreator?: boolean;
};

export default function AdminStaff({ slug, team, permissions, canAssignPermissions, onSaved, onRemoved, onCoachOrder }: {
  slug: string; team: StaffMember[]; onSaved: (member: StaffMember) => void; onRemoved: (member: StaffMember) => void;
  permissions: SportPermissions; canAssignPermissions: boolean;
  onCoachOrder: (ids: number[]) => void;
}) {
  const [editor, setEditor] = useState<StaffMember | "new" | null>(null);
  const [accessEditor, setAccessEditor] = useState<StaffMember | null>(null);
  const [removing, setRemoving] = useState(false);
  const [moving, setMoving] = useState(false);
  const [error, setError] = useState("");
  const [credentials, setCredentials] = useState<Credentials | null>(null);
  const trainers = team.filter((member) => member.role === "trainer");
  const orderedTeam = [...trainers, ...team.filter((member) => member.role !== "trainer")];
  const canEdit = (role: StaffMember["role"]) => permissions[ROLE_PERMISSIONS[role]]
    && (role !== "trainer" || canAssignPermissions);
  const assignableRoles = (["trainer", "admin", "manager", "owner"] as const).filter(canEdit);
  const busy = editor !== null || accessEditor !== null || removing || moving;

  async function moveCoach(id: number, direction: "up" | "down") {
    setMoving(true);
    setError("");
    try {
      const result = await sportRequest<{ order: number[] }>(slug, `/manage/coaches/${id}/move`, {
        method: "POST",
        body: new URLSearchParams({ direction }),
      });
      onCoachOrder(result.order);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось изменить порядок тренеров");
    } finally {
      setMoving(false);
    }
  }

  async function remove(member: StaffMember) {
    if (!window.confirm(`Убрать сотрудника «${member.name}» из команды клуба?`)) return;
    setRemoving(true);
    setError("");
    try {
      await sportRequest(slug, `/staff/${member.role}/${member.id}`, { method: "DELETE" });
      onRemoved(member);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось убрать сотрудника");
    } finally {
      setRemoving(false);
    }
  }

  return <section aria-labelledby="admin-staff-title">
    <div className="adm-top"><div><h1 id="admin-staff-title" className="adm-h">Сотрудники</h1>
      <p className="admin-hint">Здесь можно изменить данные тренеров и фотографии на сайте клуба.</p></div>
      {assignableRoles.length > 0 && <button className="btn btn-black" disabled={busy} onClick={() => setEditor("new")}>Добавить сотрудника</button>}
    </div>
    {error && <p className="sport-admin-alert" role="alert">{error}</p>}
    {editor && <StaffEditor slug={slug} member={editor === "new" ? null : editor} assignableRoles={assignableRoles} onCancel={() => setEditor(null)}
      onSave={(member, credentials) => { onSaved(member); setEditor(null); setCredentials(credentials ?? null); }} />}
    {credentials && <CredentialsDialog slug={slug} credentials={credentials} close={() => setCredentials(null)} />}
    {accessEditor && <AccessEditor slug={slug} member={accessEditor} onCancel={() => setAccessEditor(null)}
      onSave={(member) => { onSaved(member); setAccessEditor(null); }} />}
    <div className="admin-staff-grid">
      {orderedTeam.map((member, index) => <article className="admin-staff-card" key={`${member.role}-${member.id}`}>
        <div className="admin-staff-identity">
          {member.photo ? <img src={member.photo} alt="" /> : <span className="admin-staff-placeholder" aria-hidden="true">{member.name.charAt(0)}</span>}
          <div><h2>{member.name}</h2><p>{member.isCreator ? "Создатель клуба" : member.title || ROLE_LABELS[member.role]}</p></div>
        </div>
        {member.phone && <a href={`tel:${member.phone}`}>{member.phone}</a>}
        {member.role === "trainer" && <p className="admin-hint">{member.hasAccount ? "Аккаунт подключён" : "Без аккаунта"}</p>}
        {member.experience && <p>{member.experience}</p>}
        {member.tags && <p>{member.tags}</p>}
        {member.about && <p className="admin-staff-about">{member.about}</p>}
        <div className="admin-form-actions">
          {canEdit(member.role) && <button className="admin-secondary" disabled={busy} onClick={() => setEditor(member)}>Изменить</button>}
          {canAssignPermissions && (member.role === "admin" || member.role === "manager") && !member.isCreator &&
            <button className="admin-secondary" disabled={busy} onClick={() => setAccessEditor(member)}>Права доступа</button>}
          {!member.isCreator && canEdit(member.role) && <button className="admin-text-button" disabled={busy} onClick={() => void remove(member)}>Убрать из команды</button>}
          {member.role === "trainer" && canEdit("trainer") && trainers.length > 1 && <>
            <button className="admin-secondary" disabled={busy || index === 0} aria-label={`Переместить выше: ${member.name}`}
              onClick={() => void moveCoach(member.id, "up")}>↑</button>
            <button className="admin-secondary" disabled={busy || index === trainers.length - 1} aria-label={`Переместить ниже: ${member.name}`}
              onClick={() => void moveCoach(member.id, "down")}>↓</button>
          </>}
        </div>
      </article>)}
    </div>
  </section>;
}

function AccessEditor({ slug, member, onCancel, onSave }: {
  slug: string; member: StaffMember; onCancel: () => void; onSave: (member: StaffMember) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  return <form className="admin-editor" onSubmit={async (event) => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const permissions = Object.fromEntries(Object.keys(PERMISSION_LABELS).map((key) => [key, fields.has(key)]));
    setSaving(true);
    setError("");
    try {
      const result = await sportRequest<{ member: StaffMember }>(slug, `/manage/staff/${member.id}/permissions`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(permissions),
      });
      onSave(result.member);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось сохранить права");
    } finally {
      setSaving(false);
    }
  }}>
    <h2 className="adm-sub">Права доступа · {member.name}</h2>
    {error && <p className="sport-admin-alert" role="alert">{error}</p>}
    <fieldset disabled={saving}>
      <div className="admin-editor-grid">{Object.entries(PERMISSION_LABELS).map(([key, label]) =>
        <label className="admin-check" key={key}><input type="checkbox" name={key}
          defaultChecked={member.permissions?.[key as keyof SportPermissions] === true} />{label}</label>
      )}</div>
      <div className="admin-form-actions"><button className="btn btn-black" type="submit">{saving ? "Сохраняем…" : "Сохранить права"}</button>
        <button className="admin-secondary" type="button" onClick={() => {
          if (window.confirm("Вы точно хотите отменить редактирование прав?")) onCancel();
        }}>Отмена</button></div>
    </fieldset>
  </form>;
}

function CredentialsDialog({ slug, credentials, close }: { slug: string; credentials: Credentials; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const login = new URL("/sport/login", window.location.origin);
  login.searchParams.set("redirect", `/sport/${encodeURIComponent(slug)}/admin`);
  const text = `Вход в Руми Спорт\nЛогин (телефон): ${credentials.login}\nВременный пароль: ${credentials.password}\nСайт: ${login}`;
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }
  useEffect(() => {
    const panel = dialog.current;
    panel?.showModal();
    void copy();
    return () => panel?.close();
  }, [text]);
  return <dialog ref={dialog} className="admin-editor-dialog" aria-labelledby="sport-credentials-title" onCancel={(event) => {
    event.preventDefault();
    close();
  }}>
    <div className="admin-editor">
      <h2 id="sport-credentials-title" className="adm-sub">Данные для входа</h2>
      <p>{credentials.name}</p>
      <div className="admin-editor-grid">
        <label>Телефон<input readOnly value={credentials.login} /></label>
        <label>Временный пароль<input readOnly value={credentials.password} /></label>
      </div>
      <p className="admin-hint" role="status">{copyState === "copied" ? "Телефон и пароль скопированы."
        : copyState === "failed" ? "Автокопирование недоступно. Нажмите «Скопировать» или выделите данные вручную." : "Передайте эти данные сотруднику. Пароль показывается один раз."}</p>
      <div className="admin-form-actions">
        <button className="btn btn-black" type="button" onClick={() => void copy()}>Скопировать</button>
        <button className="admin-secondary" type="button" onClick={close}>Готово</button>
      </div>
    </div>
  </dialog>;
}

function StaffEditor({ slug, member, assignableRoles, onCancel, onSave }: {
  slug: string; member: StaffMember | null; onCancel: () => void; onSave: (member: StaffMember, credentials?: Credentials | null) => void;
  assignableRoles: readonly StaffMember["role"][];
}) {
  const [role, setRole] = useState<StaffMember["role"]>(member?.role ?? assignableRoles[0] ?? "trainer");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [removePhoto, setRemovePhoto] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    setPreview("");
    if (!file || file.size > 5 * 1024 * 1024 || /\.hei[cf]$/i.test(file.name)) return;
    const reader = new FileReader();
    reader.onload = () => { if (typeof reader.result === "string") setPreview(reader.result); };
    reader.readAsDataURL(file);
    return () => { if (reader.readyState === FileReader.LOADING) reader.abort(); };
  }, [file]);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = new FormData(event.currentTarget);
    if (!file) body.delete("photo");
    body.set("remove_photo", String(removePhoto));
    setSaving(true);
    setError("");
    setSessionExpired(false);
    try {
      const path = member ? `/staff/${member.role}/${member.id}` : "/staff";
      const result = await sportRequest<{ member: StaffMember; credentials?: Credentials | null }>(slug, path, { method: member ? "PUT" : "POST", body });
      onSave(result.member, result.credentials);
    } catch (error) {
      if (error instanceof SportRequestError && error.status === 401) {
        setSessionExpired(true);
        setError("Сессия истекла. Войдите в новой вкладке, затем снова нажмите «Сохранить». Форма останется открытой.");
      } else {
        setError(error instanceof Error ? error.message : "Не удалось сохранить карточку");
      }
    } finally {
      setSaving(false);
    }
  }

  const photo = preview || (!removePhoto && member?.photo);
  return <form className="admin-editor" onSubmit={save}>
    <h2 className="adm-sub">{member ? `Карточка сотрудника · ${member.name}` : "Новый сотрудник"}</h2>
    {error && <p className="sport-admin-alert" role="alert">{error}</p>}
    {sessionExpired && <a href={`/sport/login?redirect=${encodeURIComponent(`/sport/${slug}/admin`)}`} target="_blank" rel="noopener noreferrer">Войти в аккаунт ↗</a>}
    <fieldset disabled={saving}>
      <div className="admin-staff-editor-layout">
      <div className="admin-editor-grid admin-staff-editor-fields">
        <label>Имя<input name="name" defaultValue={member?.name} required minLength={2} maxLength={160} autoFocus placeholder="Фамилия, имя, отчество" /></label>
        {member ? <label>{member.role === "trainer" && !member.hasAccount ? "Телефон для входа" : "Контактный телефон"}<input name="contact_phone" type="tel" maxLength={24} defaultValue={member.phone} /></label>
          : <label>Телефон для входа<input name="phone" type="tel" maxLength={24} placeholder="+7 900 000-00-00" required /></label>}
        {!member && <label>Роль<select name="role" value={role} onChange={(event) => setRole(event.target.value as StaffMember["role"])}>
          {assignableRoles.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}
        </select></label>}
        {!member && role === "owner" && <p className="admin-hint admin-editor-wide">Совладелец получает права владельца клуба.</p>}
        {!member && role === "trainer" && <p className="admin-hint admin-editor-wide">Чтобы совмещать роли тренера и владельца, укажите тот же телефон для входа.</p>}
        {role === "trainer" && <>
          <label>Должность на сайте<input name="title" maxLength={160} defaultValue={member?.title ?? "Тренер"} /></label>
          <label>Опыт и квалификация<input name="experience" maxLength={160} defaultValue={member?.experience} placeholder="Например, 1-й дан" /></label>
          <label>Направления<input name="tags" maxLength={300} defaultValue={member?.tags} placeholder="Например, ММА и грэпплинг" /></label>
        </>}
        <label className="admin-editor-wide">{role === "trainer" ? "Биография для сайта" : "О сотруднике"}<textarea name="about" defaultValue={member?.about} maxLength={4000} rows={4} /></label>
      </div>
        <div className="admin-editor-grid admin-staff-photo-panel">
          {photo ? <img src={photo} alt="Предпросмотр фотографии сотрудника" /> : <div className="admin-photo-empty">Предпросмотр фотографии</div>}
          <label>{member?.photo ? "Заменить фото" : "Загрузить фото"}<input type="file" name="photo" accept="image/*,.heic,.heif" onChange={(event) => {
            setFile(event.currentTarget.files?.[0] ?? null);
            if (event.currentTarget.files?.length) setRemovePhoto(false);
          }} /></label>
          <p className="admin-hint">До 5 МБ. Квадратное фото лучше подходит для карточки тренера.</p>
          {member?.photo && !file && !removePhoto && <button className="admin-text-button" type="button" onClick={() => setRemovePhoto(true)}>Удалить фото</button>}
          {removePhoto && <button className="admin-text-button" type="button" onClick={() => setRemovePhoto(false)}>Вернуть фото</button>}
        </div>
      </div>
      <div className="admin-form-actions">
        <button className="btn btn-black" type="submit">{saving ? "Сохраняем…" : "Сохранить"}</button>
        <button className="admin-secondary" type="button" onClick={() => {
          if (window.confirm("Вы точно хотите отменить редактирование? Несохранённые изменения пропадут.")) onCancel();
        }}>Отмена</button>
      </div>
    </fieldset>
  </form>;
}
