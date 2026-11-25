import { useEffect, useState } from "react";
import { sportRequest } from "./admin-api";

const ROLE_LABELS = { owner: "Владелец", manager: "Управляющий", admin: "Администратор", trainer: "Тренер" };
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

export type StaffMember = {
  id: number;
  role: keyof typeof ROLE_LABELS;
  name: string;
  phone: string;
  photo?: string | null;
  about: string;
  title?: string;
  experience?: string;
  tags?: string;
  permissions?: SportPermissions;
  isCreator?: boolean;
};

export default function AdminStaff({ slug, team, permissions, canAssignPermissions, onSaved, onRemoved }: {
  slug: string; team: StaffMember[]; onSaved: (member: StaffMember) => void; onRemoved: (member: StaffMember) => void;
  permissions: SportPermissions; canAssignPermissions: boolean;
}) {
  const [editor, setEditor] = useState<StaffMember | "new" | null>(null);
  const [accessEditor, setAccessEditor] = useState<StaffMember | null>(null);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState("");
  const orderedTeam = [...team.filter((member) => member.role === "trainer"), ...team.filter((member) => member.role !== "trainer")];
  const assignableRoles = (["trainer", "admin", "manager"] as const).filter((role) => permissions[ROLE_PERMISSIONS[role]]);
  const busy = editor !== null || accessEditor !== null || removing;

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
      onSave={(member) => { onSaved(member); setEditor(null); }} />}
    {accessEditor && <AccessEditor slug={slug} member={accessEditor} onCancel={() => setAccessEditor(null)}
      onSave={(member) => { onSaved(member); setAccessEditor(null); }} />}
    <div className="admin-staff-grid">
      {orderedTeam.map((member) => <article className="admin-staff-card" key={`${member.role}-${member.id}`}>
        <div className="admin-staff-identity">
          {member.photo ? <img src={member.photo} alt="" /> : <span className="admin-staff-placeholder" aria-hidden="true">{member.name.charAt(0)}</span>}
          <div><h2>{member.name}</h2><p>{member.title || ROLE_LABELS[member.role]}</p></div>
        </div>
        {member.phone && <a href={`tel:${member.phone}`}>{member.phone}</a>}
        {member.experience && <p>{member.experience}</p>}
        {member.tags && <p>{member.tags}</p>}
        {member.about && <p className="admin-staff-about">{member.about}</p>}
        <div className="admin-form-actions">
          {permissions[ROLE_PERMISSIONS[member.role]] && <button className="admin-secondary" disabled={busy} onClick={() => setEditor(member)}>Изменить</button>}
          {canAssignPermissions && (member.role === "admin" || member.role === "manager") && !member.isCreator &&
            <button className="admin-secondary" disabled={busy} onClick={() => setAccessEditor(member)}>Права доступа</button>}
          {member.role !== "owner" && permissions[ROLE_PERMISSIONS[member.role]] && <button className="admin-text-button" disabled={busy} onClick={() => void remove(member)}>Убрать из команды</button>}
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

function StaffEditor({ slug, member, assignableRoles, onCancel, onSave }: {
  slug: string; member: StaffMember | null; onCancel: () => void; onSave: (member: StaffMember) => void;
  assignableRoles: readonly StaffMember["role"][];
}) {
  const [role, setRole] = useState<StaffMember["role"]>(member?.role ?? assignableRoles[0] ?? "trainer");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [removePhoto, setRemovePhoto] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

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
    try {
      const path = member ? `/staff/${member.role}/${member.id}` : "/staff";
      const result = await sportRequest<{ member: StaffMember }>(slug, path, { method: member ? "PUT" : "POST", body });
      onSave(result.member);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось сохранить карточку");
    } finally {
      setSaving(false);
    }
  }

  const photo = preview || (!removePhoto && member?.photo);
  return <form className="admin-editor" onSubmit={save}>
    <h2 className="adm-sub">{member ? `Карточка сотрудника · ${member.name}` : "Новый сотрудник"}</h2>
    {error && <p className="sport-admin-alert" role="alert">{error}</p>}
    <fieldset disabled={saving}>
      <div className="admin-editor-grid">
        <label>Имя<input name="name" defaultValue={member?.name} required minLength={2} maxLength={160} autoFocus /></label>
        {member ? <label>Контактный телефон<input name="contact_phone" type="tel" maxLength={24} defaultValue={member.phone} /></label>
          : <label>Телефон для входа<input name="phone" type="tel" maxLength={24} placeholder="+7 900 000-00-00" required /></label>}
        {!member && <label>Роль<select name="role" value={role} onChange={(event) => setRole(event.target.value as StaffMember["role"])}>
          {assignableRoles.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}
        </select></label>}
        {role === "trainer" && <>
          <label>Должность<input name="title" maxLength={160} defaultValue={member?.title ?? "Тренер"} /></label>
          <label>Опыт и квалификация<input name="experience" maxLength={160} defaultValue={member?.experience} /></label>
          <label>Направления<input name="tags" maxLength={300} defaultValue={member?.tags} /></label>
        </>}
        <label className="admin-editor-wide">О сотруднике<textarea name="about" defaultValue={member?.about} maxLength={4000} rows={4} /></label>
        <div className="admin-editor-wide admin-staff-photo-row">
          {photo && <img src={photo} alt="Фото сотрудника" />}
          <label>{member?.photo ? "Заменить фото" : "Загрузить фото"}<input type="file" name="photo" accept="image/*,.heic,.heif" onChange={(event) => {
            setFile(event.currentTarget.files?.[0] ?? null);
            if (event.currentTarget.files?.length) setRemovePhoto(false);
          }} /></label>
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
