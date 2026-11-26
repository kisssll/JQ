import { useEffect, useState, type FormEvent } from "react";
import { sportRequest } from "./admin-api";

export type ClubDocument = { id: string; title: string; url: string };
type Agreement = { title: string; text: string; version: string };
export type TrainingAgreements = Record<"adult" | "minor", Agreement>;
type DocumentData = { documents: ClubDocument[]; agreements: TrainingAgreements };

export default function AdminDocuments({ slug, onSaved }: { slug: string; onSaved: (agreements: TrainingAgreements) => void }) {
  const [data, setData] = useState<DocumentData | null>(null);
  const [editing, setEditing] = useState<ClubDocument | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    sportRequest<DocumentData>(slug, "/manage/documents", { signal: controller.signal })
      .then(setData)
      .catch((error) => { if (!controller.signal.aborted) setStatus(error.message); });
    return () => controller.abort();
  }, [slug]);

  async function save(path: string, method: string, body?: FormData) {
    setBusy(true);
    setStatus("");
    try {
      const updated = await sportRequest<DocumentData>(slug, path, { method, body });
      setData(updated);
      onSaved(updated.agreements);
      setEditing(null);
      setStatus("Изменения сохранены.");
      return true;
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Не удалось сохранить изменения.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function saveDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const body = new FormData(form);
    const file = body.get("file");
    if (file instanceof File && !file.size && editing) body.delete("file");
    if (await save(editing ? `/manage/documents/${editing.id}` : "/manage/documents", editing ? "PUT" : "POST", body)) form.reset();
  }

  return <section>
    <h1 className="adm-h">Документы</h1>
    {status && <p role="status" className="admin-hint">{status}</p>}
    {!data ? <p>Загружаем документы…</p> : <>
      <form className="admin-editor" onSubmit={saveDocument} key={editing?.id ?? "new"}>
        <h2 className="adm-sub">{editing ? "Изменить документ" : "Добавить документ"}</h2>
        <fieldset disabled={busy}>
          <div className="admin-editor-grid">
            <label>Название документа<input name="title" defaultValue={editing?.title ?? ""} maxLength={200} required /></label>
            <label>{editing ? "Заменить файл" : "Файл документа"}<input name="file" type="file" accept=".pdf,image/*" required={!editing} /></label>
          </div>
          <p className="admin-hint">PDF или изображение до 5 МБ.</p>
          <div className="admin-form-actions">
            <button className="btn btn-black" type="submit">Сохранить</button>
            {editing && <button className="admin-secondary" type="button" onClick={() => setEditing(null)}>Отмена</button>}
          </div>
        </fieldset>
      </form>
      <div className="admin-editor">
        <h2 className="adm-sub">На сайте</h2>
        {!data.documents.length && <p>Файлы пока не добавлены.</p>}
        {data.documents.map((document) => <div className="admin-site-item" key={document.id}>
          <a href={document.url} target="_blank" rel="noreferrer">{document.title}</a>
          <div className="admin-form-actions">
            <button className="admin-secondary" disabled={busy} onClick={() => setEditing(document)}>Изменить</button>
            <button className="admin-text-button" disabled={busy} onClick={() => {
              if (window.confirm("Удалить документ с сайта?")) void save(`/manage/documents/${document.id}`, "DELETE");
            }}>Удалить</button>
          </div>
        </div>)}
      </div>
      <h2 className="adm-sub">Согласия при записи</h2>
      {(["adult", "minor"] as const).map((audience) => {
        const agreement = data.agreements[audience];
        return <form className="admin-editor" key={audience + agreement.version} onSubmit={(event) => {
          event.preventDefault();
          void save(`/manage/agreements/${audience}`, "PUT", new FormData(event.currentTarget));
        }}>
          <h3 className="adm-sub">{audience === "adult" ? "Совершеннолетний участник" : "Законный представитель"}</h3>
          <fieldset disabled={busy} className="admin-editor-grid">
            <label className="admin-editor-wide">Название<input name="title" required maxLength={200} defaultValue={agreement.title} /></label>
            <label className="admin-editor-wide">Полный текст<textarea name="text" rows={12} required maxLength={20000} defaultValue={agreement.text} /></label>
            <button className="btn btn-black" type="submit">Сохранить согласие</button>
          </fieldset>
        </form>;
      })}
    </>}
  </section>;
}
