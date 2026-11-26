export const ADMIN_PAGE_SIZE = 40;

export class SportRequestError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "SportRequestError";
  }
}

export async function sportRequest<T>(slug: string, path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/sport/organizations/${encodeURIComponent(slug)}${path}`, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const validation = Array.isArray(detail) ? detail[0]?.msg : undefined;
    const requestId = response.headers.get("X-Request-ID");
    const message = response.status >= 500 && requestId
      ? `Ошибка сервера. Код запроса: ${requestId}`
      : typeof detail === "string" ? detail : validation || "Не удалось выполнить запрос. Попробуйте ещё раз.";
    throw new SportRequestError(message, response.status);
  }
  return data;
}

export function dateKey(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function calendarDate(iso: string) {
  return new Date(`${iso}T12:00:00`);
}

export const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
