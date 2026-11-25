import { useEffect, useMemo, useRef, useState } from "react";
import AdminClients from "./AdminClients";
import AdminSchedule from "./AdminSchedule";
import AdminStaff, { type SportPermissions, type StaffMember } from "./AdminStaff";
import { ClubReviews, ClubSettings, CoachPayroll, type ClubProfile } from "./AdminClubTabs";
import { sportRequest } from "./admin-api";

/* ---------------- data ---------------- */

type Page = "/" | "/gyms" | "/coaches" | "/disciplines" | "/schedule" | "/prices" | "/gallery" | "/account" | "/admin";
type BookingStatus = "new" | "confirmed" | "came" | "cancelled";
export type Booking = {
  id: string;
  name: string;
  phone: string;
  email?: string;
  experience?: string;
  discipline: string;
  gym: string;
  date: string;
  time: string;
  status: BookingStatus;
  kind?: "Пробное" | "Обычное";
  participant?: "self" | "child";
  childName?: string;
  childAge?: string;
  coach?: string;
  sessionId?: string;
};
type Payment = {
  id: string;
  name: string;
  plan: string;
  amount: number;
  date: string;
  month?: string;
  paidAt?: string;
  status: "paid" | "pending";
  method: string;
};
type Plan = {
  id: string;
  name: string;
  price: number;
  unit: string;
  items: string[];
  featured?: boolean;
};

export type Gym = { id: string; address: string; name: string; note: string; disciplines: string[]; hours: string; photo?: string | null };
export type Coach = { id: number; name: string; role: string; tags: string; exp: string; about: string; photo?: string | null };
export type Discipline = { key: string; name: string; text: string; level: string };
type GalleryPhoto = { src: string; alt: string; credit?: string };
export type Training = { id: string; days: number[]; time: string; end: string; coach: string; coachId?: number | null; gym: string; discipline: string; active: boolean };
const localDate = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const upcomingSlots = (trainings: Training[] = []) => Array.from({ length: 14 }, (_, offset) => {
  const date = new Date(); date.setDate(date.getDate() + offset);
  return trainings.filter((item) => item.active && item.days.includes(date.getDay())).map((item) => ({ ...item, date: localDate(date) }));
}).flat();
const today = () => localDate(new Date());
const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;
const fmtDate = (d: string) => new Date(d).toLocaleDateString("ru-RU");
const shortCoach = (name: string) => {
  const [surname, first] = name.split(" ");
  return `${surname} ${first}`;
};

/* ---------------- ui atoms ---------------- */

function Arrow() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="square"
    >
      <path d="M4 12h15M13 6l6 6-6 6" />
    </svg>
  );
}
function Close() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
    >
      <path d="M5 5l14 14M19 5L5 19" />
    </svg>
  );
}

function Chevron({ previous = false }: { previous?: boolean }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={previous ? "m14 5-7 7 7 7" : "m10 5 7 7-7 7"} /></svg>;
}

function SlidingImage({ src, alt, className = "", onError, lazy = false }: { src: string; alt: string; className?: string; onError?: () => void; lazy?: boolean }) {
  const [shown, setShown] = useState(src);
  const [loaded, setLoaded] = useState("");
  const changing = shown !== src;
  return <>
    {changing && <img className={`${className} photo-previous`} src={shown} alt="" aria-hidden="true" />}
    <img key={src} className={`${className} ${changing ? "photo-next" : ""} ${changing && loaded === src ? "photo-enter" : ""}`} src={src} alt={alt} loading={lazy ? "lazy" : undefined} decoding="async" onLoad={() => setLoaded(src)} onError={onError} onAnimationEnd={() => setShown(src)} />
  </>;
}

/**
 * ФОТОГРАФИИ САЙТА — вставляйте сюда ссылки или импорты.
 * Пример: hero: '/photos/hero.jpg'  (файл положить в папку public/photos)
 * Пока значение пустое, на сайте показывается тёмная заглушка с подписью.
 */
const PHOTOS: Record<string, string> = {
  hero: "/photos/club/hero.jpg", // Главный экран: команда / спарринг
  story: "/photos/club/story.jpg",
  cta: "", // Баннер «Первая тренировка»: зал / ковёр, 2400×1000
  gymsHead: "", // Шапка страницы «Залы», 2400×1000
  coachesHead: "/photos/club/hero.jpg", // Команда клуба
  disciplinesHead: "", // Шапка страницы «Направления», 2400×1000
  pricesHead: "", // Шапка страницы «Цены», 2400×1000
  gym_irk: "/photos/gyms/irk-03.png",
  gym_fr: "/photos/gyms/fr.jpg",
  gym_ssmu: "/photos/gyms/ssmu.jpg",
  coach_0: "/photos/coaches/dmitry-club.jpg",
  coach_1: "/photos/coaches/akim.png",
  coach_2: "/photos/coaches/bogdan.png",
  coach_3: "",
  disc_0: "/photos/disciplines/bjj.png",
  disc_1: "/photos/disciplines/grappling.png",
  disc_2: "/photos/disciplines/mma.png",
  disc_3: "/photos/disciplines/self-defense-02.png",
  disc_4: "/photos/disciplines/bjj.png",
  gallery_1: "/photos/gallery/01.jpg", gallery_2: "/photos/gallery/02.jpg", gallery_3: "/photos/gallery/03.jpg", gallery_4: "/photos/gallery/04.jpg", gallery_5: "/photos/gallery/05.jpg", gallery_6: "/photos/gallery/06.jpg",
};

/** Фото-область. Если в PHOTOS есть ссылка — показывается фото, иначе заглушка с подписью. */
function Photo({
  id,
  label,
  size,
  className = "",
  srcOverride,
  ignoreDefault = false,
  children,
}: {
  id: string;
  label: string;
  size: string;
  className?: string;
  srcOverride?: string;
  ignoreDefault?: boolean;
  children?: React.ReactNode;
}) {
  const src = ignoreDefault ? srcOverride : srcOverride || PHOTOS[id];
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return (
    <div className={`ph ${className}`} data-photo={id}>
      {src && !failed ? (
        <SlidingImage className="ph-img" src={src} alt={label} lazy={id !== "hero"} onError={() => setFailed(true)} />
      ) : (
        <div className="ph-meta">
          <span>ФОТО</span>
          {label}
          <em>{size}</em>
        </div>
      )}
      {children && <div className="ph-over">{children}</div>}
    </div>
  );
}

const NAV: [string, Page][] = [
  ["Клуб", "/"],
  ["Залы", "/gyms"],
  ["Тренеры", "/coaches"],
  ["Направления", "/disciplines"],
  ["Расписание", "/schedule"],
  ["Галерея", "/gallery"],
  ["Цены", "/prices"],
];
const PAGES: Page[] = ["/", "/gyms", "/coaches", "/disciplines", "/schedule", "/prices", "/gallery", "/account", "/admin"];
const APP_ROOT = document.getElementById("root");
const GYM_SLUG = APP_ROOT?.dataset.gymSlug ?? "sparta";
const IS_SPARTA = GYM_SLUG === "sparta";
const SPARTA_HOME_PHOTOS = "/photos/home";
const GYM_NAME = IS_SPARTA ? "СПАРТА" : APP_ROOT?.dataset.gymName ?? "Спортивный клуб";
const GYM_CITY = APP_ROOT?.dataset.gymCity ?? "";
const GYM_LOGO = IS_SPARTA ? `${SPARTA_HOME_PHOTOS}/logo.webp` : APP_ROOT?.dataset.gymLogo || "";
const APP_BASE_PATH = `/sport/${GYM_SLUG}`;
const currentPage = (): Page =>
  PAGES.includes((location.pathname.slice(APP_BASE_PATH.length) || "/") as Page)
    ? ((location.pathname.slice(APP_BASE_PATH.length) || "/") as Page)
    : "/";

/* ---------------- app ---------------- */

export default function App() {
  const [page, setPage] = useState<Page>(currentPage);
  const isAdmin = page === "/admin";
  const [menu, setMenu] = useState(false);
  const [solid, setSolid] = useState(false);
  useEffect(() => {
    if (!menu) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeMenu = (event: KeyboardEvent) => { if (event.key === "Escape") setMenu(false); };
    addEventListener("keydown", closeMenu);
    return () => { document.body.style.overflow = previous; removeEventListener("keydown", closeMenu); };
  }, [menu]);
  useEffect(() => {
    const f = () => setSolid(scrollY > 40);
    f();
    addEventListener("scroll", f, { passive: true });
    return () => removeEventListener("scroll", f);
  }, []);
  const [bookingFor, setBookingFor] = useState<Partial<Booking> | null>(null);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [trainings, setTrainings] = useState<Training[]>([]);
  const [gyms, setGyms] = useState<Gym[]>([]);
  const [coaches, setCoaches] = useState<Coach[]>([]);
  const [disciplines, setDisciplines] = useState<Discipline[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [gallery, setGallery] = useState<GalleryPhoto[]>([]);
  const [organization, setOrganization] = useState<ClubProfile>({ name: GYM_NAME, city: "", description: "", phone: "" });
  const [accountLoginRequired, setAccountLoginRequired] = useState(false);
  const [exceptions, setExceptions] = useState<Record<string, boolean>>({});
  const [scheduleLoading, setScheduleLoading] = useState(true);
  const [scheduleError, setScheduleError] = useState("");
  const [managementState, setManagementState] = useState<"loading" | "ready" | "error">("loading");
  const [managementError, setManagementError] = useState("");
  const [managementNeedsLogin, setManagementNeedsLogin] = useState(false);
  const [managementRetry, setManagementRetry] = useState(0);
  const [managementDate, setManagementDate] = useState(today);
  useEffect(() => {
    if (isAdmin) return;
    const controller = new AbortController();
    setScheduleError("");
    setScheduleLoading(true);
    const loadCatalog = async () => {
      try {
        const response = await fetch(`/api/v1/sport/organizations/${encodeURIComponent(GYM_SLUG)}/catalog`, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Не удалось загрузить данные клуба");
        const data = await response.json();
        if (controller.signal.aborted) return;
        setOrganization(data.organization);
        setGyms(data.venues.map((item: Gym) => ({ ...item, disciplines: data.disciplines.map((d: Discipline) => d.key) })));
        setCoaches(data.coaches);
        setDisciplines(data.disciplines);
        setPlans(data.plans);
        setGallery(data.gallery);
        setTrainings(data.trainings);
        setExceptions(data.exceptions);
      } catch (error) {
        if (!controller.signal.aborted) {
          setScheduleError(error instanceof Error ? error.message : "Не удалось загрузить данные клуба");
        }
      } finally {
        if (!controller.signal.aborted) setScheduleLoading(false);
      }
    };
    void loadCatalog();
    return () => controller.abort();
  }, [isAdmin]);
  useEffect(() => {
    if (page !== "/account") return;
    const controller = new AbortController();
    const loadAccount = async () => {
      try {
        const response = await fetch(`/api/v1/sport/organizations/${encodeURIComponent(GYM_SLUG)}/account`, { signal: controller.signal });
        if (response.status === 401) {
          setAccountLoginRequired(true);
          return;
        }
        if (!response.ok) throw new Error("Не удалось загрузить историю заявок");
        const data = await response.json();
        if (controller.signal.aborted) return;
        setBookings(data.bookings);
        setAccountLoginRequired(false);
      } catch (error) {
        if (!controller.signal.aborted) setScheduleError(error instanceof Error ? error.message : "Не удалось загрузить историю заявок");
      }
    };
    void loadAccount();
    return () => controller.abort();
  }, [page]);
  useEffect(() => {
    if (page !== "/admin") return;
    const controller = new AbortController();
    const loadManagement = async () => {
      setManagementState("loading");
      setManagementError("");
      setManagementNeedsLogin(false);
      try {
        const response = await fetch(
          `/api/v1/sport/organizations/${encodeURIComponent(GYM_SLUG)}/manage`,
          { signal: controller.signal },
        );
        if (response.status === 401) {
          setManagementNeedsLogin(true);
          throw new Error("Сессия завершилась. Войдите, чтобы открыть панель клуба.");
        }
        if (response.status === 403) {
          throw new Error("У вашего аккаунта нет доступа к панели этого клуба.");
        }
        if (!response.ok) {
          const requestId = response.headers.get("X-Request-ID");
          throw new Error(requestId ? `Не удалось загрузить панель клуба. Код запроса: ${requestId}` : "Не удалось загрузить панель клуба. Попробуйте ещё раз.");
        }
        const data = await response.json() as {
          bookings: Booking[]; payments: Payment[]; trainings: Training[]; exceptions: Record<string, boolean>;
          today: string; role: string; permissions: SportPermissions; canAssignPermissions: boolean;
          team: StaffMember[]; coaches: Coach[]; organization: typeof organization;
          venues: { id: number; name: string; address: string; description: string; hours: string; photo_url?: string | null }[];
          disciplines: { name: string; description: string; level: string }[];
          plans: (Omit<Plan, "id"> & { code: string })[];
        };
        if (controller.signal.aborted) return;
        setBookings(data.bookings);
        setPayments(data.payments);
        setTrainings(data.trainings);
        setExceptions(data.exceptions);
        setManagementRole(data.role);
        setManagementPermissions(data.permissions);
        setCanAssignPermissions(data.canAssignPermissions);
        setManagementTeam(data.team ?? []);
        setManagementDate(data.today ?? today());
        setOrganization(data.organization);
        setCoaches(data.coaches ?? []);
        const disciplines = data.disciplines.map((item) => ({ key: item.name, name: item.name, text: item.description, level: item.level }));
        setDisciplines(disciplines);
        setGyms(data.venues.map((item) => ({ ...item, id: String(item.id), note: item.description,
          photo: item.photo_url, disciplines: disciplines.map((discipline) => discipline.key) })));
        setPlans(data.plans.map((item) => ({ ...item, id: item.code })));
        setManagementState("ready");
      } catch (error) {
        if (!controller.signal.aborted) {
          setManagementError(error instanceof Error
            ? error.message
            : "Не удалось загрузить панель клуба. Попробуйте ещё раз.");
          setManagementState("error");
        }
      }
    };
    void loadManagement();
    return () => controller.abort();
  }, [page, managementRetry]);
  const [managementRole, setManagementRole] = useState("");
  const [managementPermissions, setManagementPermissions] = useState<SportPermissions>({});
  const [canAssignPermissions, setCanAssignPermissions] = useState(false);
  const [managementTeam, setManagementTeam] = useState<StaffMember[]>([]);

  const go = (p: Page) => {
    history.pushState({}, "", `${APP_BASE_PATH}${p === "/" ? "" : p}`);
    setPage(p);
    setMenu(false);
    scrollTo(0, 0);
  };
  useEffect(() => {
    const f = () => setPage(currentPage());
    addEventListener("popstate", f);
    return () => removeEventListener("popstate", f);
  }, []);

  const book = (b: Partial<Booking> = {}) => setBookingFor(b);
  const choosePlan = (plan: Plan) => book({ kind: plan.id === "trial" ? "Пробное" : "Обычное" });
  const publicOrganization = GYM_SLUG === "sparta" ? { ...organization, name: GYM_NAME } : organization;
  const publicGallery = GYM_SLUG === "sparta" ? gallery.map((photo) => photo.src === "/photos/disciplines/self-defense-01.png"
    ? { ...photo, src: "/photos/disciplines/self-defense-02.png" } : photo) : gallery;

  if (page === "/admin") {
    if (managementState !== "ready" || !managementRole) {
      const loginHref = `/sport/login?redirect=${encodeURIComponent(`${APP_BASE_PATH}/admin`)}`;
      return <main className="sport-admin-state">
        <section className="sport-admin-state__card">
          <p className="sport-admin-state__eyebrow">Руми Спорт · панель клуба</p>
          <h1>{managementState === "error" ? "Не удалось открыть кабинет" : "Загружаем кабинет"}</h1>
          {managementState === "loading"
            ? <p className="sport-admin-state__message" role="status">Загружаем данные клуба…</p>
            : <p className="sport-admin-state__message" role="alert">{managementError}</p>}
          <div className="sport-admin-state__actions">
            {managementState === "error" && (
              <button
                type="button"
                className="btn btn-red"
                onClick={() => setManagementRetry((attempt) => attempt + 1)}
              >
                Повторить
              </button>
            )}
            {managementNeedsLogin && <a className="btn btn-black" href={loginHref}>Войти</a>}
            <a className="sport-admin-state__link" href={APP_BASE_PATH}>На страницу клуба</a>
          </div>
        </section>
      </main>;
    }
    return <Admin
      bookings={bookings} setBookings={setBookings}
      payments={payments} setPayments={setPayments}
      trainings={trainings} setTrainings={setTrainings}
      exceptions={exceptions} setExceptions={setExceptions}
      gyms={gyms} coaches={coaches} disciplines={disciplines} plans={plans}
      setCoaches={setCoaches}
      role={managementRole} slug={GYM_SLUG} team={managementTeam}
      permissions={managementPermissions} canAssignPermissions={canAssignPermissions}
      setTeam={setManagementTeam} organization={organization} onProfileSaved={setOrganization} current={managementDate} onExit={() => go("/")}
    />;
  }

  return (
    <>
      <header className={`hdr${solid || menu || page !== "/" ? " solid" : ""}${IS_SPARTA ? " sparta-header" : ""}`}>
        <div className="hdr-brand">
          <button className="hdr-logo" onClick={() => go("/")}>
            {GYM_LOGO && <img src={GYM_LOGO} alt="" />}
            <span>{publicOrganization.name}</span>
          </button>
          <nav className="direction-switch" aria-label="Направление Руми">
            <a href="/directions/beauty">Красота</a>
            <a href="/sport/" aria-current="true">Спорт</a>
          </nav>
        </div>
        <nav id="site-navigation" aria-label="Основная навигация" className={menu ? "hdr-nav open" : "hdr-nav"}>
          {NAV.map(([t, p]) => (
            <button key={p} className={page === p ? "on" : ""} aria-current={page === p ? "page" : undefined} onClick={() => go(p)}>
              {t}
            </button>
          ))}
          <button className="hdr-staff-m" onClick={() => go("/account")}>
            Мой кабинет
          </button>
        </nav>
        <div className="hdr-right">
          <button className="hdr-staff" onClick={() => go("/account")}>
            Мой кабинет
          </button>
          <button className="btn btn-red hdr-cta" onClick={() => book()}>
            Записаться
          </button>
          <button className="hdr-burger" onClick={() => setMenu(!menu)} aria-label={menu ? "Закрыть меню" : "Открыть меню"} aria-expanded={menu} aria-controls="site-navigation">
            {menu ? <Close /> : <span />}
          </button>
        </div>
      </header>

      {page === "/" && <Home go={go} book={book} organization={publicOrganization} gyms={gyms} gallery={gallery} />}
      {page === "/gyms" && <Gyms book={book} go={go} gyms={gyms} city={organization.city} />}
      {page === "/coaches" && <Coaches book={book} coaches={coaches} trainings={trainings} exceptions={exceptions} scheduleLoading={scheduleLoading} scheduleError={scheduleError} />}
      {page === "/disciplines" && <Disciplines book={book} disciplines={disciplines} />}
      {page === "/schedule" && <Schedule book={book} gyms={gyms} coaches={coaches} trainings={trainings} exceptions={exceptions} scheduleLoading={scheduleLoading} scheduleError={scheduleError} />}
      {page === "/gallery" && <Gallery gallery={publicGallery} organization={publicOrganization.name} />}
      {page === "/prices" && <Prices choose={choosePlan} plans={plans} />}
      {page === "/account" && <Account bookings={bookings} book={book} loginRequired={accountLoginRequired} error={scheduleError} />}

      <footer className="ftr">
        <div className="ftr-top">
          <div className="ftr-big">
            {IS_SPARTA && <img src={GYM_LOGO} alt="" loading="lazy" />}
            {publicOrganization.name}
          </div>
          <button className="btn btn-red" onClick={() => book()}>
            Записаться на пробное <Arrow />
          </button>
        </div>
        <div className="ftr-cols">
          <div>
            <b>Залы</b>
            {gyms.map((g) => (
              <p key={g.id}>{g.address}</p>
            ))}
          </div>
          <div>
            <b>Разделы</b>
            {NAV.map(([t, p]) => (
              <button key={p} onClick={() => go(p)}>
                {t}
              </button>
            ))}
          </div>
          <div>
            <b>Связь</b>
            {organization.phone && <p><a href={`tel:${organization.phone}`}>{organization.phone}</a></p>}
            {GYM_SLUG === "sparta" && <p><a href="https://vk.ru/spartaplus" target="_blank" rel="noreferrer">Сообщество VK</a></p>}
          </div>
          <div>
            <b>Клуб</b>
            <p>{organization.city} · спортивный клуб</p>
            <button onClick={() => go("/account")}>Мой кабинет</button>
          </div>
        </div>
      </footer>

      {!bookingFor && !menu && page !== "/account" && <div className="mobile-book"><span>Первое занятие<b>Бесплатно</b></span><button className="btn btn-red" onClick={() => book()}>Записаться <Arrow /></button></div>}

      {bookingFor && (
        <BookingModal
          initial={bookingFor}
          trainings={trainings}
          gyms={gyms}
          exceptions={exceptions}
          onClose={() => setBookingFor(null)}
          onSubmit={async (b) => {
            const consentVersion = document.querySelector<HTMLMetaElement>('meta[name="consent-version"]')?.content ?? "";
            const response = await fetch(`/api/v1/sport/organizations/${encodeURIComponent(GYM_SLUG)}/bookings`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                name: b.name,
                phone: b.phone,
                email: b.email || null,
                experience: b.experience || null,
                kind: b.kind,
                participant: b.participant,
                child_name: b.childName || null,
                child_age: b.participant === "child" ? Number(b.childAge) : null,
                training_id: b.sessionId || null,
                booking_date: b.sessionId ? b.date : null,
                gym: b.gym,
                discipline: b.discipline,
                pd_consent: b.pdConsent,
                consent_version: consentVersion,
              }),
            });
            const result = await response.json().catch(() => null) as {
              booking_id?: unknown;
              detail?: unknown;
            } | null;
            if (!response.ok) {
              const detail = typeof result?.detail === "string"
                ? result.detail
                : Array.isArray(result?.detail)
                  ? result.detail.map((item) => item?.msg).filter(Boolean).join(" ")
                  : "";
              throw new Error(detail || "Не удалось отправить заявку");
            }
            if (typeof result?.booking_id !== "number") {
              throw new Error("Сервер не подтвердил сохранение заявки");
            }
            setBookings((items) => [
              { ...b, id: String(result.booking_id), status: "new" },
              ...items,
            ]);
          }}
        />
      )}
    </>
  );
}

/* ---------------- pages ---------------- */

type Book = (b?: Partial<Booking>) => void;

function Home({ go, book, organization, gyms, gallery }: { go: (p: Page) => void; book: Book; organization: { name: string; city: string; description: string; phone: string }; gyms: Gym[]; gallery: GalleryPhoto[] }) {
  const reasonPhotos = IS_SPARTA
    ? ["beginners", "age-groups", "self-defense"].map((name) => `${SPARTA_HOME_PHOTOS}/${name}.webp`)
    : gallery.slice(0, 3).map((photo) => photo.src);
  const reasons = GYM_SLUG === "sparta"
    ? [
        ["01", "Начать можно с нуля", "Новички занимаются в отдельных группах, без давления.", reasonPhotos[0] ?? ""],
        ["02", "Группы по возрасту", "Занятия для детей, подростков и взрослых.", reasonPhotos[1] ?? ""],
        ["03", "Самооборона", "Учимся защищать себя и близких.", reasonPhotos[2] ?? ""],
      ]
    : [
        ["01", "Начать можно с нуля", "Тренер поможет выбрать подходящую группу и нагрузку.", reasonPhotos[0] ?? ""],
        ["02", "Группы для разных возрастов", "Уточните подходящее расписание у клуба.", reasonPhotos[1] ?? ""],
        ["03", "Техника и физическая подготовка", "Развивайте навыки и уверенность на тренировках.", reasonPhotos[2] ?? ""],
      ];
  return (
    <main className={IS_SPARTA ? "sparta-home" : undefined}>
      <Photo
        id="hero"
        label={IS_SPARTA ? "Команда клуба «Спарта»" : `Фото клуба ${organization.name}`}
        size="2400 × 1400"
        className="cover cover-hero"
        srcOverride={IS_SPARTA ? `${SPARTA_HOME_PHOTOS}/team.webp` : gallery[0]?.src}
        ignoreDefault
      >
        {IS_SPARTA ? (
          <h1 className="cover-title">Здесь куют <span>характер</span></h1>
        ) : (
          <>
            <p className="tag tag-light">{organization.city}</p>
            <h1 className="cover-title">{organization.name}</h1>
          </>
        )}
        <div className="cover-foot">
          <p>{organization.description || (IS_SPARTA ? "Клуб единоборств в Томске для детей, подростков и взрослых." : "")}</p>
          <div className="row">
            <button className="btn btn-red" onClick={() => book()}>
              Пробная тренировка <Arrow />
            </button>
            <button className="btn btn-white-line" onClick={() => go("/schedule")}>
              Расписание
            </button>
          </div>
        </div>
      </Photo>

      <section className="club-overview" aria-labelledby="club-overview-title">
        <div className="club-overview-copy">
          <p className="tag">О клубе / {organization.city || GYM_CITY}</p>
          <h2 id="club-overview-title">{GYM_SLUG === "sparta" ? "Томский клуб единоборств с 2002 года" : "О клубе"}</h2>
          {GYM_SLUG === "sparta" && <p>В «Спарте» тренируются дети с пяти лет, подростки и взрослые. В 2007 году клуб помог открыть в ТУСУРе школу дзю-дзютцу и студенческую специализацию «Самооборона». Спортсмены клуба выступают за сборную Томской области по грэпплингу и боевому дзю-дзютцу.</p>}
          <p>Можно прийти без опыта. На первой тренировке познакомитесь с тренером, попробуете занятия и вместе подберёте группу.</p>
          <button className="link" onClick={() => go("/coaches")}>Познакомиться с тренерами <Arrow /></button>
        </div>
        <div className="club-start">
          <p className="tag">Первая тренировка</p>
          <h3>Начать проще,<br />чем кажется.</h3>
          <ol>
            <li><span>01</span><div><b>Выберите удобный зал</b><p>{GYM_SLUG === "sparta" ? "Три площадки и вечерние занятия по расписанию." : `${gyms.length} ${gyms.length === 1 ? "площадка клуба" : "площадок клуба"} с расписанием занятий.`}</p></div></li>
            <li><span>02</span><div><b>Оставьте имя и телефон</b><p>Администратор свяжется с вами и подтвердит запись.</p></div></li>
            <li><span>03</span><div><b>Приходите попробовать</b><p>Спортивная форма, вода и желание начать. Пробное занятие бесплатно.</p></div></li>
          </ol>
          <button className="btn btn-red" onClick={() => book()}>Выбрать тренировку <Arrow /></button>
        </div>
      </section>

      <section className="why-sparta" aria-labelledby="why-gym-title">
        <div className="why-gallery" aria-hidden="true">
          {reasonPhotos.map((photo) => <img key={photo} src={photo} alt="" loading="lazy" decoding="async" />)}
        </div>
        <div className="why-content">
          <h2 className="tag tag-light why-title" id="why-gym-title">{IS_SPARTA ? "Почему же Спарта?" : `Почему ${GYM_NAME}`}</h2>
          <div className="reasons-over">
            {reasons.map(([n, h, p, photo]) => (
              <article className="why-reason" key={n}>
                {photo && <img className="why-mobile-photo" src={photo} alt="" loading="lazy" decoding="async" />}
                <div className="why-reason-copy">
                  <b>{n}</b>
                  <h3>{h}</h3>
                  <p>{p}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="tiles">
        {(
          [
            ["Залы", `${gyms.length} ${gyms.length === 1 ? "площадка" : "площадок"}`, "/gyms", "gym_irk", "gyms"],
            ["Тренеры", "Команда клуба", "/coaches", "coach_0", "coaches"],
            ["Направления", "Чему мы учим", "/disciplines", "disc_0", "disciplines"],
          ] as [string, string, Page, string, string][]
        ).map(([t, s, p, id, photo]) => (
          <button key={p} className="tile" onClick={() => go(p)}>
            <Photo id={id} label={t} size="1200 × 1500" className="tile-ph" srcOverride={IS_SPARTA ? `${SPARTA_HOME_PHOTOS}/${photo}.webp` : undefined} ignoreDefault={!IS_SPARTA}>
              {!IS_SPARTA && <p className="tag tag-light">{s}</p>}
              <div className="tile-cap">
                <h3>{t}</h3>
                <span className="round">
                  <Arrow />
                </span>
              </div>
            </Photo>
          </button>
        ))}
      </section>

      <section className="club-booking">
        <h2>{IS_SPARTA ? "Запишитесь на пробную тренировку" : "Первая тренировка"}</h2>
        <button className="btn btn-red" onClick={() => book()}>
          Записаться <Arrow />
        </button>
      </section>
    </main>
  );
}

function PageHead({ title, text }: { id: string; title: string; text: string }) {
  return <header className="section-heading public-page-heading"><h1>{title}</h1><p>{text}</p></header>;
}

function spartaVenuePhotos(address: string): GalleryPhoto[] {
  const location = address.includes("Иркутский") ? { prefix: "irk", shots: 5 }
    : address.includes("Фрунзе") ? { prefix: "fr", shots: 4 }
    : address.includes("Учебная") ? { prefix: "ssmu", shots: 5 } : null;
  if (!location) return [];
  const photos = Array.from({ length: location.shots }, (_, index) => ({
    src: `/photos/gyms/${location.prefix}-club-${index + 1}.jpg`,
    alt: `Интерьер зала · ${address}`,
  }));
  return [...photos, { src: `/photos/gyms/${location.prefix}-club-exterior.jpg`, alt: `Вход в здание · ${address}` }];
}

function Gyms({ book, go, gyms, city }: { book: Book; go: (page: Page) => void; gyms: Gym[]; city: string }) {
  const [openGym, setOpenGym] = useState<Gym | null>(null);
  const [selected, setSelected] = useState(0);
  const photosFor = (gym: Gym) => {
    const photos = GYM_SLUG === "sparta" ? spartaVenuePhotos(gym.address) : [];
    return photos.length ? photos : gym.photo ? [{ src: gym.photo, alt: gym.name }] : [];
  };
  const photos = openGym ? photosFor(openGym) : [];
  return (
    <main className="venue-page">
      <PageHead id="gymsHead" title="Залы" text={city ? `Адреса тренировочных площадок · ${city}` : "Адреса тренировочных площадок"} />
      <section className="venue-list" aria-label="Площадки клуба">
        {gyms.map((gym) => {
          const venuePhotos = photosFor(gym);
          return (
            <article className="venue-card" key={gym.id}>
              {venuePhotos[0] && (
                <button className="venue-photo" type="button" onClick={() => { setSelected(0); setOpenGym(gym); }} aria-label={`Открыть фотографии: ${gym.address}`}>
                  <img src={venuePhotos[0].src} alt={venuePhotos[0].alt} loading="lazy" decoding="async" />
                  <span>Фото зала <Arrow /></span>
                </button>
              )}
              <div className="venue-copy">
                <p className="tag">{gym.name}</p>
                <h2>{gym.address}</h2>
                {gym.note && <p>{gym.note}</p>}
                <div className="venue-actions">
                  <button className="btn btn-red" onClick={() => book({ gym: gym.address })}>Записаться <Arrow /></button>
                  <a className="link" href={`https://2gis.ru/search/${encodeURIComponent(`${city}, ${gym.address}`)}`} target="_blank" rel="noreferrer">Маршрут в 2ГИС <Arrow /></a>
                </div>
              </div>
            </article>
          );
        })}
      </section>
      <div className="venue-schedule"><button className="btn btn-black" onClick={() => go("/schedule")}>Расписание всех залов <Arrow /></button></div>
      {openGym && photos.length > 0 && (
        <Modal centered className="gym-modal" label="Фотографии зала" onClose={() => setOpenGym(null)}>
          <h2 className="m-title">{openGym.name}</h2>
          <PhotoGallery photos={photos} caption={openGym.address} selected={selected} setSelected={setSelected}
            movePhoto={(step) => setSelected((index) => (index + step + photos.length) % photos.length)} />
        </Modal>
      )}
    </main>
  );
}
function PhotoGallery({ selected, setSelected, movePhoto, photos, caption }: { selected: number; setSelected: (index: number) => void; movePhoto: (step: number) => void; photos: GalleryPhoto[]; caption: string }) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") movePhoto(-1);
      if (event.key === "ArrowRight") movePhoto(1);
    };
    addEventListener("keydown", onKeyDown);
    return () => removeEventListener("keydown", onKeyDown);
  }, [movePhoto]);
  const current = photos[selected];
  return (
    <div className="gym-gallery">
      <p className="m-note">{caption}</p>
      <div className="gym-gallery-main">
        <SlidingImage src={current.src} alt={current.alt} />
        <button className="gym-photo-arrow gym-photo-prev" type="button" onClick={() => movePhoto(-1)} aria-label="Предыдущее фото"><Chevron previous /></button>
        <button className="gym-photo-arrow gym-photo-next" type="button" onClick={() => movePhoto(1)} aria-label="Следующее фото"><Chevron /></button>
      </div>
      <div className="gym-gallery-thumbs" aria-label="Выбор фотографии">
        {photos.map((photo, index) => (
          <button
            type="button"
            key={photo.src}
            aria-label={`Открыть фото ${index + 1}: ${photo.alt}`}
            aria-pressed={selected === index}
            onClick={() => setSelected(index)}
          >
            <img src={photo.src} alt="" loading="lazy" decoding="async" />
          </button>
        ))}
      </div>
      <p className="gym-gallery-count" aria-live="polite">Фото {selected + 1} из {photos.length}</p>
    </div>
  );
}

function coachPhoto(coach: Coach) {
  return GYM_SLUG === "sparta" && coach.photo === "/photos/coaches/dmitry.png"
    ? PHOTOS.coach_0 : coach.photo ?? undefined;
}

function Coaches({ book, coaches, trainings, exceptions, scheduleLoading, scheduleError }: { book: Book; coaches: Coach[]; trainings: Training[]; exceptions: Record<string, boolean>; scheduleLoading: boolean; scheduleError: string }) {
  const [selected, setSelected] = useState<number | null>(null);
  const coach = selected !== null ? coaches[selected] : null;
  const profile = coach ? { rank: coach.exp, about: coach.about } : null;
  const regular = coach ? trainings.filter((item) => item.active && item.coach === coach.name) : [];
  return (
    <main>
      <PageHead
        id="coachesHead"
        title="Тренеры"
        text="Тренеры клуба и их регулярное расписание."
      />
      {scheduleLoading && <p className="schedule-note" role="status">Загружаем расписание…</p>}
      {scheduleError && <p className="schedule-note" role="alert">{scheduleError}</p>}
      <section className="coach-roster" aria-label="Тренеры клуба">
        {coaches.map((c, i) => (
          <article className={`coach-card${GYM_SLUG === "sparta" && /руководитель клуба/i.test(c.role) ? " coach-card-lead" : ""}`} key={c.id}>
            <Photo id={`coach_${i}`} label={`Портрет: ${c.name}`} size="Квадратный портрет"
              className="coach-square" srcOverride={coachPhoto(c)} ignoreDefault />
            <div className="coach-card-copy">
              <p>{c.role}</p>
              <h2>{c.name}</h2>
              {c.exp && <p>{c.exp}</p>}
              <button className="link" onClick={() => setSelected(i)} aria-label={`Профиль тренера: ${c.name}`}>Профиль тренера <Arrow /></button>
            </div>
          </article>
        ))}
      </section>
      {coach && profile && selected !== null && <Modal centered className="coach-modal" onClose={() => setSelected(null)}>
        <div className="coach-profile-photo"><Photo id={`coach_${selected}`} label={coach.name} size="Квадратный портрет" className="coach-profile-image" srcOverride={coachPhoto(coach)} ignoreDefault /></div>
        <div className="coach-profile-copy"><p className="tag">Команда клуба</p><h2>{coach.name}</h2><p className="coach-profile-role">{coach.role}</p><p>{profile.about}</p>
          {profile.rank && <dl className="coach-credentials"><div><dt>Квалификация / опыт</dt><dd>{profile.rank}</dd></div></dl>}
          <h3>Где и когда тренирует</h3><div className="coach-profile-schedule">{regular.length ? regular.map((item) => <div key={item.id}><b>{item.days.slice().sort((a,b) => ((a + 6) % 7) - ((b + 6) % 7)).map((day) => ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][day]).join(" · ")}<span>{item.time}–{item.end}</span></b><p>{item.gym}</p></div>) : <p>Время занятий уточнит администратор.</p>}</div>
          <button className="btn btn-red" onClick={() => { const slot = upcomingSlots(trainings).find((item) => item.coach === coach.name && exceptions[`${item.date}:${item.id}`] !== false); setSelected(null); book(slot ? { coach: coach.name, sessionId: slot.id, gym: slot.gym, date: slot.date, time: slot.time } : { coach: coach.name }); }}>Записаться к тренеру <Arrow /></button>
        </div>
      </Modal>}
    </main>
  );
}

function Disciplines({ book, disciplines }: { book: Book; disciplines: Discipline[] }) {
  return (
    <main>
      <PageHead
        id="disciplinesHead"
        title="Направления"
        text="Чему мы обучаем. Не знаете, что выбрать — приходите на пробное, тренер подскажет."
      />
      <section className="disc">
        {disciplines.map((d, i) => (
          <article className="discipline-row" key={d.key}>
          <Photo
            id={`disc_${i}`}
            label={d.name}
            size="1600 × 1200"
            className="discipline-image"
            srcOverride={GYM_SLUG === "sparta" && d.key === "Самооборона" ? PHOTOS.disc_3 : undefined}
            ignoreDefault={GYM_SLUG !== "sparta"}
          />
            <div className="discipline-copy">
              <p className="tag">{d.level}</p>
              <h2>{d.name}</h2>
              <p>{d.text}</p>
              {GYM_SLUG === "sparta" && d.key === "Грэпплинг" && <p className="disc-credit">Фото: s.efimov70 · @Officer1Pupsik</p>}
              <button className="btn btn-red" onClick={() => book({ discipline: d.key })}>
                Записаться <Arrow />
              </button>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}

function Prices({ choose, plans }: { choose: (p: Plan) => void; plans: Plan[] }) {
  return (
    <main className="membership-page">
      <div className="section-heading"><p className="tag">{GYM_SLUG === "sparta" ? "Занятия в Спарте" : `Занятия в ${GYM_NAME}`}</p><h1>Цены и абонементы</h1><p>Стоимость пробной, групповых и индивидуальных тренировок.</p></div>
      <section className="membership-options" aria-label="Варианты занятий">
        {plans.map((plan) => <article className={`membership-option ${plan.id === "trial" ? "membership-trial" : ""}`} key={plan.id}>
          <div className="membership-label"><span>{plan.unit}</span>{plan.featured && <b>Популярное</b>}</div>
          <h2>{plan.name}</h2><p className="membership-value">{plan.price ? rub(plan.price) : /уточня/i.test(plan.unit) ? "Стоимость уточняется" : "Бесплатно"}</p>

          <ul>{plan.items.map((item) => <li key={item}>{item}</li>)}</ul>
          <button className={plan.id === "trial" ? "btn btn-red" : "btn btn-black"} onClick={() => choose(plan)}>
            {plan.id === "trial" ? "Записаться" : "Выбрать тариф"} <Arrow />
          </button>
        </article>)}
      </section>
      <div className="membership-help"><span>Не знаете, с чего начать?</span><p>Оставьте заявку на пробное. Администратор поможет выбрать зал и подходящую тренировку.</p>{plans[0] && <button className="link" onClick={() => choose(plans[0])}>Помогите выбрать <Arrow /></button>}</div>
      <section className="membership-faq"><div><p className="tag">Перед первым визитом</p><h2>Ещё пара<br />вопросов.</h2></div><div>{[
        ["Что взять с собой?", "Удобную спортивную форму и воду. Если понадобится специальная экипировка, тренер расскажет о ней заранее."],
        ["Можно записать ребёнка?", "Да. Выберите «Мой ребёнок» в форме, укажите его имя и возраст, а также свой телефон для связи."],
        ["Можно ли заниматься без подготовки?", "Да, можно начать с нуля. Расскажите администратору о своём опыте — он поможет подобрать группу."],
        ["Как оплатить абонемент?", "Стоимость и способ оплаты уточнит администратор клуба. У него можно уточнить срок действия и условия выбранного варианта."],
      ].map(([q, a]) => <details key={q}><summary>{q}<span aria-hidden="true">+</span></summary><p>{a}</p></details>)}</div></section>
    </main>
  );
}

function weekDates(offset: number) {
  const start = new Date();
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7) + offset * 7);
  return Array.from({ length: 7 }, (_, i) => { const date = new Date(start); date.setDate(start.getDate() + i); return date; });
}

function Schedule({ book, gyms, coaches, trainings, exceptions, scheduleLoading, scheduleError }: { book: Book; gyms: Gym[]; coaches: Coach[]; trainings: Training[]; exceptions: Record<string, boolean>; scheduleLoading: boolean; scheduleError: string }) {
  const [week, setWeek] = useState(0);
  const [gym, setGym] = useState("all");
  const [coach, setCoach] = useState("all");
  const dates = weekDates(week);
  const visibleGyms = gyms.filter((item) => gym === "all" || item.address === gym);
  const slotsFor = (date: Date, address: string) => trainings.filter((item) => item.active && item.days.includes(date.getDay()) && item.gym === address && (coach === "all" || item.coach === coach)).sort((a, b) => a.time.localeCompare(b.time));
  const hasResults = dates.some((date) => visibleGyms.some((item) => slotsFor(date, item.address).length > 0));
  return (
    <main className="timetable-page">
      <div className="section-heading timetable-heading"><div><p className="tag">Расписание{GYM_CITY ? ` / ${GYM_CITY}` : ""}</p><h1>Групповые тренировки</h1><p>Выберите зал и тренировку. Записаться можно прямо из расписания.</p></div><div className="timetable-offer"><span>Первый раз?</span><b>Попробуйте бесплатно.</b><button className="link" onClick={() => book()}>Помогите выбрать <Arrow /></button></div></div>
      <section className="timetable-section" aria-label="Расписание тренировок">
        <div className="timetable-toolbar"><div className="gym-tabs" aria-label="Выбор зала"><button aria-pressed={gym === "all"} onClick={() => setGym("all")}>Все залы</button>{gyms.map((g) => <button key={g.id} aria-pressed={gym === g.address} onClick={() => setGym(g.address)}>{g.name}</button>)}</div><label className="timetable-coach"><span>Тренер</span><select value={coach} onChange={(e) => setCoach(e.target.value)}><option value="all">Все тренеры</option>{coaches.map((c) => <option key={c.id} value={c.name}>{shortCoach(c.name)}</option>)}</select></label></div>
        <div className="timetable-week"><div><h2>Неделя тренировок</h2><p>Занятия по залам</p></div><div className="week-switch"><button aria-label="Предыдущая неделя" onClick={() => setWeek(Math.max(0, week - 1))} disabled={week === 0}><Chevron previous /></button><strong>{dates[0].toLocaleDateString("ru-RU", { day: "numeric", month: "short" })} — {dates[6].toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}</strong><button aria-label="Следующая неделя" onClick={() => setWeek(week + 1)}><Chevron /></button>{week > 0 && <button className="week-reset" onClick={() => setWeek(0)}>Эта неделя</button>}</div></div>
        {scheduleLoading && <p className="timetable-no-results" role="status">Загружаем расписание…</p>}
        {scheduleError && <p className="timetable-no-results" role="alert">{scheduleError}</p>}
        {!scheduleLoading && !scheduleError && !hasResults && <p className="timetable-no-results">По этим фильтрам занятий нет. Выберите другой зал или тренера.</p>}
        <table className="timetable">
          <caption className="page-title-sr">Тренировки по дням недели и залам</caption>
          <thead><tr><th scope="col">День</th>{visibleGyms.map((g) => <th key={g.id} scope="col"><b>{g.name}</b><span>{g.address}</span></th>)}</tr></thead><tbody>
          {dates.map((date) => {
            const key = localDate(date);
            const dayEmpty = visibleGyms.every((g) => slotsFor(date, g.address).length === 0);
            return <tr className={`${key === today() ? "is-today" : ""} ${dayEmpty ? "is-empty-day" : ""}`} key={key}><th scope="row"><b>{date.toLocaleDateString("ru-RU", { weekday: "long" })}</b><span>{date.toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}{key === today() && <em>Сегодня</em>}</span></th>{visibleGyms.map((g) => { const slots = slotsFor(date, g.address); return <td key={g.id} className={!slots.length ? "is-empty-cell" : ""}><span className="timetable-mobile-gym">{g.address}</span>{slots.length ? slots.map((slot) => {
              const held = exceptions[`${key}:${slot.id}`] !== false;
              const past = key < today();
              return <article className={`timetable-session ${!held ? "is-cancelled" : ""} ${past ? "is-past" : ""}`} key={slot.id}><div><b>{slot.time}<span>–{slot.end}</span></b><p>{shortCoach(slot.coach)}</p>{slot.discipline !== "Направление уточняется" && <small>{slot.discipline}</small>}</div>{!held ? <span className="session-status">Отменена</span> : past ? <span className="session-status">Завершена</span> : <button aria-label={`Записаться: ${fmtDate(key)}, ${slot.time}, ${shortCoach(slot.coach)}, ${g.address}`} onClick={() => book({ sessionId: slot.id, coach: slot.coach, discipline: slot.discipline, gym: slot.gym, date: key, time: slot.time })}>Записаться <Arrow /></button>}</article>;
            }) : <span className="timetable-dash" aria-label="Нет занятий">—</span>}</td>; })}</tr>;
          })}
          </tbody>
        </table>
        <div className="timetable-footnote"><span>Расписание повторяется каждую неделю. Отмены отмечаем на конкретную дату.</span><span>Запись подтвердит администратор.</span></div>
      </section>
    </main>
  );
}

function Gallery({ gallery, organization }: { gallery: GalleryPhoto[]; organization: string }) {
  const [selected, setSelected] = useState<number | null>(null);
  const movePhoto = (step: number) => setSelected((current) => ((current ?? 0) + step + gallery.length) % gallery.length);
  const photo = selected === null ? null : gallery[selected];
  return <main><PageHead id="story" title="Галерея" text={`Фотографии ${organization}.`} /><section className="gallery-page"><div className="gallery-heading"><p className="tag">Клуб в кадре</p><h2>Тренировки и жизнь клуба.</h2><p>Нажмите на фото, чтобы рассмотреть его ближе.</p></div><div className="gallery-grid">{gallery.map((item, i) => <button className="gallery-open" key={item.src} onClick={() => setSelected(i)} aria-label={`Открыть фото: ${item.alt}`}><Photo id={`club_gallery_${i}`} srcOverride={item.src} label={item.alt} size="1600 × 1200" className="gallery-tile"><span>{item.alt}</span><span className="gallery-expand" aria-hidden="true">↗</span></Photo></button>)}</div>{gallery.length === 0 && <p>Фотографии пока не добавлены.</p>}</section>{photo && <Modal centered className="gym-modal" label="Фотографии клуба" onClose={() => setSelected(null)}><h2 className="m-title">{photo.alt}</h2><PhotoGallery photos={gallery} caption={organization} selected={selected!} setSelected={setSelected} movePhoto={movePhoto} /></Modal>}</main>;
}

function Account({ bookings, book, loginRequired, error }: { bookings: Booking[]; book: Book; loginRequired: boolean; error: string }) {
  return <main>
    <PageHead id="story" title="Личный кабинет" text="История заявок в клубе." />
    <section className="account-page">
      <div className="account-card">
        <p className="tag">Участник или родитель</p>
        <h2>Ваши заявки</h2>
        <p>Можно записаться без регистрации. Чтобы видеть историю заявок, войдите с тем же номером телефона, который указали при записи.</p>
        {error && <p className="sport-app-alert" role="alert">{error}</p>}
        {loginRequired && <a className="btn btn-black" href={`/sport/login?redirect=${encodeURIComponent(`${APP_BASE_PATH}/account`)}`}>Войти или зарегистрироваться</a>}
        {bookings.length > 0 && <div className="account-records">
          <p>Заявки клуба:</p>
          {bookings.map((item) => <div key={item.id}>
            <b>{item.sessionId ? `${fmtDate(item.date)} · ${item.time}` : "Время уточняется"}</b>
            <span>{item.gym}</span><small>{item.status === "new" ? "Ожидает подтверждения" : STATUS[item.status]}</small>
          </div>)}
        </div>}
        <button className="btn btn-red" onClick={() => book()}>Записаться на тренировку <Arrow /></button>
      </div>
    </section>
  </main>;
}

/* ---------------- modals ---------------- */

function Modal({ onClose, children, centered = false, className = "", label = "Информация клуба" }: { onClose: () => void; children: React.ReactNode; centered?: boolean; className?: string; label?: string }) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]') ?? []);
    panel.current?.focus();
    const f = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); close.current(); }
      if (e.key !== "Tab") return;
      const items = focusable();
      const first = items[0], last = items[items.length - 1];
      if (!first) { e.preventDefault(); return; }
      if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || document.activeElement === panel.current)) { e.preventDefault(); first.focus(); }
    };
    addEventListener("keydown", f);
    return () => { removeEventListener("keydown", f); document.body.style.overflow = previousOverflow; if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true }); };
  }, []);
  return (
    <div className={`modal ${centered ? "modal-centered" : ""} ${className}`} onMouseDown={onClose}>
      <div ref={panel} className="modal-box" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} onMouseDown={(e) => e.stopPropagation()}>
        <button className="modal-x" onClick={onClose} aria-label="Закрыть">
          <Close />
        </button>
        {children}
      </div>
    </div>
  );
}

function BookingModal({
  initial,
  trainings,
  gyms,
  exceptions,
  onClose,
  onSubmit,
  centered = false,
}: {
  initial: Partial<Booking>;
  trainings: Training[];
  gyms: Gym[];
  exceptions: Record<string, boolean>;
  onClose: () => void;
  onSubmit: (b: Omit<Booking, "id" | "status"> & { pdConsent: boolean }) => void | Promise<void>;
  centered?: boolean;
}) {
  const slots = upcomingSlots(trainings).filter((slot) => exceptions[`${slot.date}:${slot.id}`] !== false);
  const selectedInitial = initial.sessionId && initial.date && initial.date >= today() && !slots.some((slot) => slot.id === initial.sessionId && slot.date === initial.date)
    ? trainings.filter((slot) => slot.id === initial.sessionId && slot.active && exceptions[`${initial.date}:${slot.id}`] !== false).map((slot) => ({ ...slot, date: initial.date! }))
    : [];
  const options = [...selectedInitial, ...slots];
  const suggested = options.find((slot) => (!initial.gym || slot.gym === initial.gym) && (!initial.coach || slot.coach === initial.coach) && (!initial.discipline || slot.discipline === initial.discipline)) ?? options[0];
  const [f, setF] = useState({
    name: "",
    phone: "",
    email: "",
    experience: "",
    kind: initial.kind ?? "Пробное" as "Пробное" | "Обычное",
    participant: "self" as "self" | "child",
    childName: "",
    childAge: "",
    discipline: initial.discipline ?? suggested?.discipline ?? "Направление уточняется",
    gym: initial.gym ?? suggested?.gym ?? gyms[0]?.address ?? "",
    coach: initial.coach ?? suggested?.coach ?? "",
    sessionId: initial.sessionId ?? (initial.discipline ? "" : suggested?.id ?? ""),
    date: initial.date ?? suggested?.date ?? today(),
    time: initial.time ?? (initial.discipline ? "По согласованию" : suggested?.time ?? ""),
  });
  const [done, setDone] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [pdConsent, setPdConsent] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });
  if (done)
    return (
      <Modal centered={centered} label="Заявка принята" onClose={onClose}>
        <div className="booking-success-icon" aria-hidden="true">✓</div>
        <h2 className="m-title">Заявка принята</h2>
        <p className="m-text">
          {f.name}, {f.sessionId ? `заявка на ${f.kind.toLowerCase()} занятие ${fmtDate(f.date)} в ${f.time}` : "заявка на подбор тренировки"} сохранена. Администратор свяжется с вами для подтверждения.
        </p>
        <button className="btn btn-black" onClick={onClose}>
          Готово
        </button>
      </Modal>
    );
  return (
    <Modal centered={centered} label="Запись на тренировку" onClose={onClose}>
      <p className="tag booking-eyebrow">Первый шаг на татами</p>
      <h2 className="m-title">Запись на тренировку</h2>
      <p className="booking-intro">Выберите занятие и оставьте контакт для подтверждения. Можно записать себя или ребёнка.</p>
      <form
        className="form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (f.participant === "child" && (!f.childName.trim() || !f.childAge.trim())) return;
          if (!f.name.trim()) return;
          setSaving(true);
          setError("");
          try {
            await onSubmit({ ...f, name: f.name.trim(), phone: f.phone.trim(), email: f.email.trim(), pdConsent });
            setDone(true);
          } catch (submitError) {
            setError(submitError instanceof Error ? submitError.message : "Не удалось отправить заявку. Попробуйте ещё раз.");
          } finally {
            setSaving(false);
          }
        }}
      >
        <label>
          Тип занятия
          <select value={f.kind} onChange={set("kind")}>
            <option>Пробное</option><option>Обычное</option>
          </select>
        </label>
        <label>
          Участник
          <select value={f.participant} onChange={set("participant")}>
            <option value="self">Я сам(а)</option><option value="child">Мой ребёнок</option>
          </select>
        </label>
        <label>
          {f.participant === "child" ? "Имя родителя" : "Ваше имя"}
          <input required autoComplete="name" placeholder="Имя и фамилия" value={f.name} onChange={set("name")} />
        </label>
        {f.participant === "child" && <>
          <label>Имя ребёнка<input required value={f.childName} onChange={set("childName")} /></label>
          <label>Возраст ребёнка<input required type="number" min="5" max="17" value={f.childAge} onChange={set("childAge")} /></label>
        </>}
        <label>
          Телефон
          <input required type="tel" inputMode="tel" autoComplete="tel" minLength={10} maxLength={24} placeholder="+7 ___ ___-__-__" value={f.phone} onChange={set("phone")} />
        </label>
        <details className="booking-extra"><summary>Добавить почту и опыт занятий <span aria-hidden="true">+</span></summary><div>
          <label>Почта · необязательно<input type="email" autoComplete="email" placeholder="name@example.ru" value={f.email} onChange={set("email")} /></label>
          <label>Опыт занятий · необязательно<select value={f.experience} onChange={set("experience")}><option value="">Не указывать</option><option>Нет, начинаю с нуля</option><option>Да, раньше занимался(лась)</option><option>Да, занимаюсь сейчас</option></select></label>
        </div></details>
        <label className="full">Зал
          <select value={f.gym} onChange={(e) => { const gym = e.target.value; const slot = options.find((item) => item.gym === gym); setF({ ...f, gym, sessionId: slot?.id ?? "", coach: slot?.coach ?? "", date: slot?.date ?? today(), time: slot?.time ?? "По согласованию" }); }}>
            {gyms.map((gym) => <option key={gym.id} value={gym.address}>{gym.address}</option>)}
          </select>
        </label>
        <label className="full">Тренировка
          <select value={f.sessionId ? `${f.date}|${f.sessionId}` : "request"} onChange={(e) => {
            const selected = options.find((slot) => `${slot.date}|${slot.id}` === e.target.value);
            if (selected) setF({ ...f, sessionId: selected.id, date: selected.date, time: selected.time, coach: selected.coach, gym: selected.gym, discipline: selected.discipline });
            else setF({ ...f, sessionId: "", time: "По согласованию" });
          }}>
            <option value="request">Подобрать время с администратором</option>
            {options.filter((slot) => slot.gym === f.gym).map((slot) => <option key={`${slot.date}|${slot.id}`} value={`${slot.date}|${slot.id}`}>{fmtDate(slot.date)} · {slot.time} · {shortCoach(slot.coach)}</option>)}
          </select>
        </label>
        <div className="booking-selected"><b>{f.sessionId ? `${fmtDate(f.date)} · ${f.time}` : "Подберём удобное время"}</b><span>{f.sessionId ? shortCoach(f.coach) : "Администратор поможет выбрать тренера"}</span><span>{f.gym}</span>{f.discipline !== "Направление уточняется" && <span>{f.discipline}</span>}</div>
        <label className="booking-consent">
          <input type="checkbox" required checked={pdConsent} onChange={(event) => setPdConsent(event.target.checked)} />
          <span>Я даю согласие на обработку персональных данных на условиях <a href="/sport/legal/consent" target="_blank" rel="noopener noreferrer">Согласия</a>.</span>
        </label>
        {error && <p className="booking-error" role="alert">{error}</p>}
        <button className="btn btn-red wide" disabled={!f.time || saving}>
          {saving ? "Отправляем…" : "Отправить заявку"} <Arrow />
        </button>
        <p className="m-note">Заявка сохранится в базе Руми. Запись подтвердит администратор клуба.</p>
      </form>
    </Modal>
  );
}

/* ---------------- admin ---------------- */

const STATUS: Record<BookingStatus, string> = {
  new: "Связаться",
  confirmed: "Подтвердил приход",
  came: "Пришёл",
  cancelled: "Отменена",
};

function Admin({
  bookings,
  setBookings,
  payments,
  setPayments,
  trainings,
  setTrainings: setTrainingsState,
  exceptions,
  setExceptions: setExceptionsState,
  gyms,
  coaches,
  setCoaches,
  disciplines,
  plans,
  role,
  permissions,
  canAssignPermissions,
  slug,
  team,
  setTeam,
  organization,
  onProfileSaved,
  current,
  onExit,
}: {
  bookings: Booking[];
  setBookings: React.Dispatch<React.SetStateAction<Booking[]>>;
  payments: Payment[];
  setPayments: React.Dispatch<React.SetStateAction<Payment[]>>;
  trainings: Training[];
  setTrainings: React.Dispatch<React.SetStateAction<Training[]>>;
  exceptions: Record<string, boolean>;
  setExceptions: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  gyms: Gym[];
  coaches: Coach[];
  setCoaches: React.Dispatch<React.SetStateAction<Coach[]>>;
  disciplines: Discipline[];
  plans: Plan[];
  role: string;
  permissions: SportPermissions;
  canAssignPermissions: boolean;
  slug: string;
  team: StaffMember[];
  setTeam: React.Dispatch<React.SetStateAction<StaffMember[]>>;
  organization: ClubProfile;
  onProfileSaved: (profile: ClubProfile) => void;
  current: string;
  onExit: () => void;
}) {
  const trainer = role === "trainer";
  const canManagePayments = permissions.view_finances === true;
  const canManageBookings = permissions.manage_bookings === true;
  const canManageTeam = canAssignPermissions || permissions.manage_coaches || permissions.manage_admins || permissions.manage_managers || permissions.manage_owners;
  const canManageSchedule = permissions.manage_schedule === true;
  const canSeePayroll = permissions.manage_payroll === true || trainer;
  const [tab, setTab] = useState<"overview" | "bookings" | "schedule" | "payments" | "team" | "clients" | "settings" | "reviews" | "payroll">(trainer ? "schedule" : "overview");
  const [gym, setGym] = useState("all");
  const [status, setStatus] = useState<"all" | BookingStatus>("all");
  const [search, setSearch] = useState("");
  const [payFilter, setPayFilter] = useState<"all" | "paid" | "pending">("all");
  const [payMonth, setPayMonth] = useState(current.slice(0, 7));
  const [newMember, setNewMember] = useState("");
  const [adding, setAdding] = useState(false);
  const [actionError, setActionError] = useState("");
  const openTab = (next: typeof tab) => { setActionError(""); setTab(next); };

  const send = async <T,>(path: string, method: string, body: URLSearchParams | Record<string, unknown>) => {
    const form = body instanceof URLSearchParams;
    return sportRequest<T>(slug, path, {
      method,
      headers: form ? { "Content-Type": "application/x-www-form-urlencoded" } : { "Content-Type": "application/json" },
      body: form ? body : JSON.stringify(body),
    });
  };
  const saveTraining = async (item: Training) => {
    await send("/manage/schedule", "PUT", { trainings: [item], exceptions: {} });
    const saved = { ...item, coachId: coaches.find((coach) => coach.name === item.coach)?.id ?? item.coachId };
    setTrainingsState((previous) => previous.some((row) => row.id === saved.id)
      ? previous.map((row) => row.id === saved.id ? saved : row) : [...previous, saved]);
  };
  const saveException = async (key: string, enabled: boolean) => {
    await send("/manage/schedule", "PUT", { trainings: [], exceptions: { [key]: enabled } });
    setExceptionsState((previous) => ({ ...previous, [key]: enabled }));
  };

  const filtered = useMemo(
    () =>
      bookings.filter(
        (b) => (gym === "all" || b.gym === gym) && (status === "all" || b.status === status) && `${b.name} ${b.childName ?? ""} ${b.phone}`.toLowerCase().includes(search.toLowerCase()),
      ),
    [bookings, gym, status, search],
  );
  const monthPayments = payments.filter((p) => (p.month ?? p.date.slice(0, 7)) === payMonth);
  const paidSum = monthPayments.filter((p) => p.status === "paid").reduce((s, p) => s + p.amount, 0);
  const pending = monthPayments.filter((p) => p.status === "pending");
  const pendingSum = pending.reduce((s, p) => s + p.amount, 0);
  const newCount = bookings.filter((b) => b.status === "new").length;

  const setB = async (id: string, nextStatus: BookingStatus) => {
    try {
      const saved = await send<{ date: string; time: string }>(`/bookings/${encodeURIComponent(id)}/status`, "POST", new URLSearchParams({ status: nextStatus === "new" ? "pending" : nextStatus }));
      setBookings((list) => list.map((booking) => booking.id === id
        ? { ...booking, status: nextStatus, date: saved.date || booking.date, time: saved.time || booking.time } : booking));
      setActionError("");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось обновить заявку");
    }
  };
  const markPaid = async (id: string, method: string) => {
    try {
      await send(`/payments/${encodeURIComponent(id)}/status`, "POST", new URLSearchParams({ status: "paid", method }));
      setPayments((list) => list.map((payment) => payment.id === id ? { ...payment, status: "paid", method, paidAt: today() } : payment));
      setActionError("");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось отметить оплату");
    }
  };
  const undoPaid = async (id: string) => {
    if (!window.confirm("Вы точно хотите отменить отметку об оплате?")) return;
    try {
      await send(`/payments/${encodeURIComponent(id)}/status`, "POST", new URLSearchParams({ status: "pending" }));
      setPayments((list) => list.map((payment) => payment.id === id ? { ...payment, status: "pending", method: "", paidAt: "" } : payment));
      setActionError("");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось отменить отметку оплаты");
    }
  };
  const addPayment = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const plan = plans.find((item) => item.id === "base") ?? plans[0];
    if (!plan) {
      setActionError("Сначала добавьте тариф клуба.");
      return;
    }
    try {
      const { payment } = await send<{ payment: Payment }>("/payments", "POST", new URLSearchParams({ member_name: newMember, plan_code: plan.id, month: payMonth }));
      setPayments((previous) => [payment, ...previous]);
      setNewMember("");
      setActionError("");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Не удалось добавить оплату");
    }
  };
  const saveStaff = (member: StaffMember) => {
    setTeam((current) => current.some((item) => item.role === member.role && item.id === member.id)
      ? current.map((item) => item.role === member.role && item.id === member.id ? member : item)
      : [...current, member]);
    if (member.role === "trainer") {
      const coach = { id: member.id, name: member.name, role: member.title ?? "Тренер", tags: member.tags ?? "",
        exp: member.experience ?? "", about: member.about, photo: member.photo };
      setCoaches((current) => current.some((item) => item.id === member.id)
        ? current.map((item) => item.id === member.id ? coach : item) : [...current, coach]);
      setTrainingsState((current) => current.map((item) => item.coachId === member.id ? { ...item, coach: member.name } : item));
    }
  };
  const removeStaff = (member: StaffMember) => {
    setTeam((current) => current.filter((item) => item.role !== member.role || item.id !== member.id));
    if (member.role === "trainer") setCoaches((current) => current.filter((item) => item.id !== member.id));
  };

  return (
    <div className="adm">
      <aside className="adm-side">
        <div className="adm-logo">
          {GYM_LOGO && <img src={GYM_LOGO} alt="" />}
          <div>
            {organization.name}<small>Панель клуба</small>
          </div>
        </div>
        <nav>
          {!trainer && <button className={tab === "overview" ? "on" : ""} onClick={() => openTab("overview")}>
            Сводка
          </button>}
          {(canManageBookings || trainer) && <button className={tab === "bookings" ? "on" : ""} onClick={() => openTab("bookings")}>
            Записи {newCount > 0 && <i>{newCount}</i>}
          </button>}
          {(canManageSchedule || trainer) && <button className={tab === "schedule" ? "on" : ""} onClick={() => openTab("schedule")}>{trainer ? "Моё расписание" : "Расписание"}</button>}
          {canManageBookings && <button className={tab === "clients" ? "on" : ""} onClick={() => openTab("clients")}>Клиенты</button>}
          {canManagePayments && <button className={tab === "payments" ? "on" : ""} onClick={() => openTab("payments")}>
            Оплаты {pending.length > 0 && <i>{pending.length}</i>}
          </button>}
          {canManageTeam && <button className={tab === "team" ? "on" : ""} onClick={() => openTab("team")}>Сотрудники</button>}
          {permissions.manage_gym && <button className={tab === "settings" ? "on" : ""} onClick={() => openTab("settings")}>Мой клуб</button>}
          {permissions.manage_reviews && <button className={tab === "reviews" ? "on" : ""} onClick={() => openTab("reviews")}>Отзывы</button>}
          {canSeePayroll && <button className={tab === "payroll" ? "on" : ""} onClick={() => openTab("payroll")}>{trainer ? "Моё вознаграждение" : "Вознаграждения"}</button>}
        </nav>
        <button className="adm-exit" onClick={onExit}>
          ← На сайт
        </button>
      </aside>

      <main className="adm-main">
        {actionError && <p className="sport-admin-alert" role="alert">{actionError}</p>}
        {tab === "overview" && (
          <>
            <h1 className="adm-h">Сводка</h1>
            <div className="kpis">
              {canManageBookings && <><button
                className="kpi"
                onClick={() => {
                  setTab("bookings");
                  setStatus("new");
                }}
              >
                <span>Новые заявки</span>
                <b>{newCount}</b>
                <em>Обработать →</em>
              </button>
              <div className="kpi">
                <span>Записей на сегодня</span>
                <b>
                  {bookings.filter((b) => b.date === current && b.status !== "cancelled").length}
                </b>
              </div></>}
              {canManagePayments && <><div className="kpi">
                <span>Оплачено</span>
                <b>{rub(paidSum)}</b>
              </div>
              <button
                className="kpi kpi-red"
                onClick={() => {
                  setTab("payments");
                  setPayFilter("pending");
                }}
              >
                <span>Ждут оплаты</span>
                <b>{rub(pendingSum)}</b>
                <em>{pending.length} чел. →</em>
              </button></>}
            </div>
            <div className="admin-insights">{canManageBookings && <><div><b>{bookings.filter((b) => b.kind === "Пробное").length}</b><span>пробных заявок</span></div><div><b>{bookings.filter((b) => b.status === "came").length}</b><span>отмечено посещений</span></div></>}{canManageSchedule && <div><b>{trainings.filter((item) => item.active).length}</b><span>активных шаблонов тренировок</span></div>}</div>
            {canManageBookings && <>
            <h2 className="adm-sub">Сегодня по залам</h2>
            <div className="by-gym">
              {gyms.map((g) => {
                const n = bookings.filter(
                  (b) => b.gym === g.address && b.date === current && b.status !== "cancelled",
                ).length;
                return (
                  <div key={g.id}>
                    <b>{n}</b>
                    <span>{g.address}</span>
                  </div>
                );
              })}
            </div></>}
          </>
        )}

        {tab === "team" && canManageTeam && <AdminStaff slug={slug} team={team} permissions={permissions} canAssignPermissions={canAssignPermissions} onSaved={saveStaff} onRemoved={removeStaff} />}
        {tab === "settings" && permissions.manage_gym && <ClubSettings slug={slug} profile={organization} onSaved={onProfileSaved} />}
        {tab === "reviews" && permissions.manage_reviews && <ClubReviews slug={slug} />}
        {tab === "payroll" && canSeePayroll && <CoachPayroll slug={slug} coaches={coaches} canEdit={permissions.manage_payroll === true} />}

        {tab === "clients" && canManageBookings && <AdminClients slug={slug} current={current} />}

        {tab === "schedule" && (canManageSchedule || trainer) && <AdminSchedule current={current} role={role} gyms={gyms} coaches={coaches}
          disciplines={disciplines} bookings={bookings} trainings={trainings} exceptions={exceptions}
          onTraining={saveTraining} onException={saveException} />}

        {tab === "bookings" && (canManageBookings || trainer) && (
          <>
            <div className="adm-top">
              <h1 className="adm-h">Записи</h1>
              {canManageBookings && <button className="btn btn-black" onClick={() => setAdding(true)}>
                + Новая запись
              </button>}
            </div>
            <div className="filters">
              <input className="record-search" aria-label="Поиск записи" placeholder="Имя, ребёнок или телефон" value={search} onChange={(e) => setSearch(e.target.value)} />
              <select value={gym} onChange={(e) => setGym(e.target.value)}>
                <option value="all">Все залы</option>
                {gyms.map((g) => (
                  <option key={g.id} value={g.address}>
                    {g.address}
                  </option>
                ))}
              </select>
              <div className="seg">
                {(["all", "new", "confirmed", "came", "cancelled"] as const).map((s) => (
                  <button key={s} className={status === s ? "on" : ""} onClick={() => setStatus(s)}>
                    {s === "all" ? "Все" : STATUS[s]}
                  </button>
                ))}
              </div>
            </div>
            <div className="tbl">
              <div className="tr th">
                <span>Клиент</span>
                <span>Направление · зал</span>
                <span>Дата</span>
                <span>Статус</span>
                <span />
              </div>
              {filtered.length === 0 && <div className="empty">Нет записей по фильтру</div>}
              {filtered.map((b) => (
                <div className="tr" key={b.id}>
                  <span>
                    <b>{b.participant === "child" ? b.childName : b.name}</b>
                    <small>{b.participant === "child" ? `Родитель: ${b.name} · ` : ""}<a href={`tel:${b.phone.replace(/[^\d+]/g, "")}`}>{b.phone}</a></small>
                  </span>
                  <span>
                    {b.kind ? `${b.kind} · ${b.discipline}` : b.discipline}
                    <small>{b.gym}</small>
                  </span>
                  <span>
                    {fmtDate(b.date)}
                    <small>{b.time}</small>
                  </span>
                  <span>
                    <i className={`st st-${b.status}`}>{STATUS[b.status]}</i>
                  </span>
                  <span className="acts">
                    {b.status === "new" && (
                      <button onClick={() => setB(b.id, "confirmed")}>Подтвердил приход</button>
                    )}
                    {b.status === "confirmed" && (
                      <button onClick={() => setB(b.id, "came")}>Пришёл</button>
                    )}
                    {b.status === "new" && <button className="ghost" onClick={() => navigator.clipboard.writeText(`Здравствуйте! Вы записаны на ${b.kind?.toLowerCase() ?? ""} занятие клуба «${organizationName}» ${fmtDate(b.date)} в ${b.time}, зал: ${b.gym}. Подтвердите, пожалуйста, что сможете прийти.`)}>Скопировать сообщение</button>}
                    {(b.status === "new" || b.status === "confirmed") && (
                      <button className="ghost" onClick={() => {
                        if (window.confirm("Вы точно хотите отменить запись?")) void setB(b.id, "cancelled");
                      }}>
                        Отменить
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {tab === "payments" && canManagePayments && (
          <>
            <div className="adm-top"><div><h1 className="adm-h">Абонементы</h1><p className="admin-hint">Безлимит на месяц. Оплата отмечается отдельно за каждый месяц.</p></div><label className="month-picker">Месяц <input type="month" value={payMonth} onChange={(e) => setPayMonth(e.target.value)} /></label></div>
            <form className="member-add" onSubmit={addPayment}><input aria-label="Имя участника" placeholder="ФИО участника" value={newMember} onChange={(e) => setNewMember(e.target.value)} required /><button className="btn btn-black">+ Добавить участника на месяц</button></form>
            <div className="kpis kpis-3">
              <div className="kpi">
                <span>Получено</span>
                <b>{rub(paidSum)}</b>
              </div>
              <div className="kpi kpi-red">
                <span>Ожидается</span>
                <b>{rub(pendingSum)}</b>
              </div>
              <div className="kpi">
                <span>Платежей</span>
                <b>{monthPayments.length}</b>
              </div>
            </div>
            <div className="filters">
              <div className="seg">
                {(["all", "pending", "paid"] as const).map((s) => (
                  <button
                    key={s}
                    className={payFilter === s ? "on" : ""}
                    onClick={() => setPayFilter(s)}
                  >
                    {s === "all" ? "Все" : s === "paid" ? "Оплачено" : "Ждут оплаты"}
                  </button>
                ))}
              </div>
            </div>
            <div className="tbl">
              <div className="tr th">
                <span>Клиент</span>
                <span>Месяц · абонемент</span>
                <span>Сумма</span>
                <span>Статус</span>
                <span />
              </div>
              {monthPayments
                .filter((p) => payFilter === "all" || p.status === payFilter)
                .map((p) => (
                  <div className="tr" key={p.id}>
                    <span>
                      <b>{p.name}</b>
                      <small>Добавлен: {fmtDate(p.date)}</small>
                    </span>
                    <span>{new Date(`${p.month ?? p.date.slice(0, 7)}-01`).toLocaleDateString("ru-RU", { month: "long", year: "numeric" })}<small>{p.plan}</small></span>
                    <span>
                      <b>{rub(p.amount)}</b>
                    </span>
                    <span>
                      <i className={p.status === "paid" ? "st st-came" : "st st-new"}>
                        {p.status === "paid" ? "Оплачено" : "Ожидает"}
                      </i>
                      {p.method && <small>{p.method}</small>}
                      {p.status === "paid" && <small>Дата оплаты: {fmtDate(p.paidAt || p.date)}</small>}
                    </span>
                    <span className="acts">
                      {p.status === "pending" && (
                        <>
                          <button onClick={() => markPaid(p.id, "Наличные")}>Наличные</button>
                          <button onClick={() => markPaid(p.id, "Карта")}>Карта</button>
                        </>
                      )}
                      {p.status === "paid" && <button className="ghost" onClick={() => undoPaid(p.id)}>Отменить отметку</button>}
                    </span>
                  </div>
                ))}
            </div>
          </>
        )}
      </main>

      {adding && (
        <BookingModal
          initial={{}}
          centered
          trainings={trainings}
          gyms={gyms}
          exceptions={exceptions}
          onClose={() => setAdding(false)}
          onSubmit={async (b) => {
            const consentVersion = document.querySelector<HTMLMetaElement>('meta[name="consent-version"]')?.content ?? "";
            const result = await send<{ booking_id: number }>("/bookings", "POST", {
              name: b.name,
              phone: b.phone,
              email: b.email || null,
              experience: b.experience || null,
              kind: b.kind,
              participant: b.participant,
              child_name: b.childName || null,
              child_age: b.participant === "child" ? Number(b.childAge) : null,
              training_id: b.sessionId || null,
              booking_date: b.sessionId ? b.date : null,
              gym: b.gym,
              discipline: b.discipline,
              pd_consent: b.pdConsent,
              consent_version: consentVersion,
            });
            if (typeof result.booking_id !== "number") throw new Error("Сервер не подтвердил запись");
            setBookings((list) => [{ ...b, id: String(result.booking_id), status: "new" }, ...list]);
          }}
        />
      )}
    </div>
  );
}
