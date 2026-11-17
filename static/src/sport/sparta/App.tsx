import { useEffect, useMemo, useRef, useState } from "react";
import logo from "./sparta-logo.png";

/* ---------------- data ---------------- */

type Page = "/" | "/gyms" | "/coaches" | "/disciplines" | "/schedule" | "/prices" | "/gallery" | "/account" | "/admin";
type BookingStatus = "new" | "confirmed" | "came" | "cancelled";
type Booking = {
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

const GYMS = [
  {
    id: "irk",
    address: "Иркутский тракт, 68",
    name: "Основной зал",
    note: "Зал для тренировок на Иркутском тракте.",
    disciplines: ["БЖЖ", "Грэпплинг", "ММА", "Самооборона"],
    hours: "По расписанию групп",
  },
  { id: "fr", address: "пр. Фрунзе, 115/3", name: "ЦНПК", note: "Фотографии зала добавим после отбора.", disciplines: ["БЖЖ", "Грэпплинг", "ММА", "Самооборона"], hours: "По расписанию групп" },
  { id: "ssmu", address: "ул. Учебная, 40 · корпус СибГМУ", name: "Зал СибГМУ", note: "Фотографии зала добавим после отбора.", disciplines: ["БЖЖ", "Грэпплинг", "ММА", "Самооборона"], hours: "По расписанию групп" },
];

const COACHES = [
  {
    name: "Давыдов Дмитрий Михайлович",
    role: "Руководитель клуба · тренер",
    tags: "Иркутский тракт · СибГМУ",
    exp: "6 дан CJJIF",
  },
  { name: "Давыдов Аким Дмитриевич", role: "Тренер", tags: "ЦНПК · пр. Фрунзе, 115/3", exp: "Пн · Ср · Пт" },
  { name: "Дмитриев Богдан Дмитриевич", role: "Тренер", tags: "Основной зал · Иркутский тракт, 68", exp: "Вт · Чт · Сб" },
];

const DISCIPLINES = [
  {
    key: "БЖЖ", name: "Бразильское джиу-джитсу", text: "Борьба, контроль и техника в партере. Группу и возраст уточнит тренер.", level: "Для детей и взрослых",
  },
  {
    key: "Грэпплинг", name: "Грэпплинг", text: "Борьба без кимоно: захваты, броски и работа в партере.", level: "Группу уточнит тренер",
  },
  {
    key: "ММА", name: "Смешанные единоборства", text: "Ударная техника и борьба в одной программе.", level: "Группу уточнит тренер",
  },
  {
    key: "Самооборона", name: "Самооборона", text: "Прикладные навыки для уверенного поведения в сложных ситуациях.", level: "По заявке",
  },
  {
    key: "Самбо", name: "Самбо", text: "Техника бросков, захватов и борьбы в партере.", level: "Группу уточнит тренер",
  },
];

const PLANS: Plan[] = [
  {
    id: "trial",
    name: "Пробное",
    price: 0,
    unit: "первое занятие",
    items: ["Ознакомительная тренировка", "Знакомство с тренером и залом"],
  },
  {
    id: "base",
    name: "Абонемент",
    price: 5000,
    unit: "в месяц",
    items: ["Безлимит на календарный месяц", "Можно посещать занятия по расписанию"],
  },
];

type Training = { id: string; days: number[]; time: string; end: string; coach: string; gym: string; discipline: string; active: boolean };
const localDate = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const upcomingSlots = (trainings: Training[] = []) => Array.from({ length: 14 }, (_, offset) => {
  const date = new Date(); date.setDate(date.getDate() + offset);
  return trainings.filter((item) => item.active && item.days.includes(date.getDay())).map((item) => ({ ...item, date: localDate(date) }));
}).flat();
const today = () => localDate(new Date());
const rub = (n: number) => `${n.toLocaleString("ru-RU")} ₽`;
const uid = () => Math.random().toString(36).slice(2, 9);
const fmtDate = (d: string) => new Date(d).toLocaleDateString("ru-RU");
const shortCoach = (name: string) => {
  const [surname, first] = name.split(" ");
  return `${surname} ${first}`;
};
const shortGym = (address: string) => address.includes("Иркутский") ? "Иркутский, 68" : address.includes("Фрунзе") ? "Фрунзе, 115/3" : "СибГМУ";

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
  coach_0: "/photos/coaches/dmitry.png",
  coach_1: "/photos/coaches/akim.png",
  coach_2: "/photos/coaches/bogdan.png",
  coach_3: "",
  disc_0: "/photos/disciplines/bjj.png",
  disc_1: "/photos/disciplines/grappling.png",
  disc_2: "/photos/disciplines/mma.png",
  disc_3: "/photos/disciplines/self-defense-01.png",
  disc_4: "/photos/disciplines/bjj.png",
  gallery_1: "/photos/gallery/01.jpg", gallery_2: "/photos/gallery/02.jpg", gallery_3: "/photos/gallery/03.jpg", gallery_4: "/photos/gallery/04.jpg", gallery_5: "/photos/gallery/05.jpg", gallery_6: "/photos/gallery/06.jpg",
};

/** Фото-область. Если в PHOTOS есть ссылка — показывается фото, иначе заглушка с подписью. */
function Photo({
  id,
  label,
  size,
  className = "",
  secondarySrc,
  srcOverride,
  children,
}: {
  id: string;
  label: string;
  size: string;
  className?: string;
  secondarySrc?: string;
  srcOverride?: string;
  children?: React.ReactNode;
}) {
  const src = srcOverride || PHOTOS[id];
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
      {src && !failed && secondarySrc && (
        <img className="ph-img ph-img-secondary" src={secondarySrc} alt="" loading="lazy" decoding="async" />
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
const APP_BASE_PATH = "/sport/sparta";
const currentPage = (): Page =>
  PAGES.includes((location.pathname.slice(APP_BASE_PATH.length) || "/") as Page)
    ? ((location.pathname.slice(APP_BASE_PATH.length) || "/") as Page)
    : "/";

/* ---------------- app ---------------- */

export default function App() {
  const [page, setPage] = useState<Page>(currentPage);
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
  const [trainings, setTrainings] = useState<Training[]>([]);
  const [exceptions, setExceptions] = useState<Record<string, boolean>>({});
  const [scheduleLoading, setScheduleLoading] = useState(true);
  const [scheduleError, setScheduleError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const loadSchedule = async () => {
      try {
        const response = await fetch("/api/v1/sport/organizations/sparta/schedule", {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Не удалось загрузить расписание");
        const data = await response.json();
        setTrainings(data.trainings);
        setExceptions(data.exceptions);
      } catch (error) {
        if (!controller.signal.aborted) {
          setScheduleError(error instanceof Error ? error.message : "Не удалось загрузить расписание");
        }
      } finally {
        if (!controller.signal.aborted) setScheduleLoading(false);
      }
    };
    void loadSchedule();
    return () => controller.abort();
  }, []);

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

  if (page === "/admin")
    return <main className="account-page"><div className="account-card">
      <p className="tag">Доступ для сотрудников</p>
      <h1>Панель подключается</h1>
      <p>Демо-панель отключена. Управление расписанием и заявками появится после настройки защищённых ролей сотрудников.</p>
      <button className="btn btn-black" onClick={() => go("/")}>На главную</button>
    </div></main>;

  return (
    <>
      <header className={solid || menu || page !== "/" ? "hdr solid" : "hdr"}>
        <button className="hdr-logo" onClick={() => go("/")}>
          <img src={logo} alt="Спарта" />
          <span>СПАРТА</span>
        </button>
        <nav id="site-navigation" aria-label="Основная навигация" className={menu ? "hdr-nav open" : "hdr-nav"}>
          {NAV.map(([t, p]) => (
            <button key={p} className={page === p ? "on" : ""} aria-current={page === p ? "page" : undefined} onClick={() => go(p)}>
              {t}
            </button>
          ))}
          <button className="hdr-staff-m" onClick={() => go("/account")}>
            Войти / зарегистрироваться
          </button>
        </nav>
        <div className="hdr-right">
          <button className="hdr-staff" onClick={() => go("/account")}>
            Войти / регистрация
          </button>
          <button className="btn btn-red hdr-cta" onClick={() => book()}>
            Записаться
          </button>
          <button className="hdr-burger" onClick={() => setMenu(!menu)} aria-label={menu ? "Закрыть меню" : "Открыть меню"} aria-expanded={menu} aria-controls="site-navigation">
            {menu ? <Close /> : <span />}
          </button>
        </div>
      </header>

      {page === "/" && <Home go={go} book={book} />}
      {page === "/gyms" && <Gyms book={book} />}
      {page === "/coaches" && <Coaches book={book} trainings={trainings} exceptions={exceptions} scheduleLoading={scheduleLoading} scheduleError={scheduleError} />}
      {page === "/disciplines" && <Disciplines book={book} />}
      {page === "/schedule" && <Schedule book={book} trainings={trainings} exceptions={exceptions} scheduleLoading={scheduleLoading} scheduleError={scheduleError} />}
      {page === "/gallery" && <Gallery />}
      {page === "/prices" && <Prices choose={choosePlan} />}
      {page === "/account" && <Account bookings={bookings} book={book} />}

      <footer className="ftr">
        <div className="ftr-top">
          <div className="ftr-big">СПАРТА</div>
          <button className="btn btn-red" onClick={() => book()}>
            Записаться на пробное <Arrow />
          </button>
        </div>
        <div className="ftr-cols">
          <div>
            <b>Залы</b>
            {GYMS.map((g) => (
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
            <p><a href="tel:+79234013788">+7 923 401-37-88</a></p>
            <p><a href="https://vk.ru/spartaplus" target="_blank" rel="noreferrer">Сообщество VK</a></p>
          </div>
          <div>
            <b>Клуб</b>
            <p>Томск · клуб работает с 2002 года</p>
            <button onClick={() => go("/account")}>Войти / зарегистрироваться</button>
          </div>
        </div>
      </footer>

      {!bookingFor && !menu && page !== "/account" && <div className="mobile-book"><span>Первое занятие<b>Бесплатно</b></span><button className="btn btn-red" onClick={() => book()}>Записаться <Arrow /></button></div>}

      {bookingFor && (
        <BookingModal
          initial={bookingFor}
          trainings={trainings}
          exceptions={exceptions}
          onClose={() => setBookingFor(null)}
          onSubmit={async (b) => {
            const consentVersion = document.querySelector<HTMLMetaElement>('meta[name="consent-version"]')?.content ?? "";
            const response = await fetch("/api/v1/sport/organizations/sparta/bookings", {
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

function Home({ go, book }: { go: (p: Page) => void; book: Book }) {
  return (
    <main>
      <Photo
        id="hero"
        label="Главное фото: команда / спарринг"
        size="2400 × 1400"
        className="cover cover-hero"
      >
        <p className="tag tag-light">Спарта · боевое дзю-дзютцу · Томск</p>
        <h1 className="cover-title">
          Здесь куют
          <br />
          <span className="red">характер</span>
        </h1>
        <div className="cover-foot">
          <p>БЖЖ, грэпплинг, ММА, самбо и самооборона для детей и взрослых.</p>
          <div className="row">
            <button className="btn btn-red" onClick={() => book()}>
              Пробная тренировка <Arrow />
            </button>
            <button className="btn btn-white-line" onClick={() => go("/prices")}>
              Цены
            </button>
          </div>
        </div>
      </Photo>

      <section className="club-overview" aria-labelledby="club-overview-title">
        <div className="club-overview-copy">
          <p className="tag">О клубе / Томск</p>
          <h2 id="club-overview-title">Твоя команда.<br />Твой характер.</h2>
          <p>«Спарта Плюс» — клуб боевого дзю-дзютцу. С 2002 года здесь тренируются дети и взрослые: осваивают борьбу, ударную технику и навыки самообороны.</p>
          <p>Можно прийти без опыта. На первой тренировке познакомитесь с тренером, попробуете занятия и вместе подберёте группу.</p>
          <div className="club-facts"><span><b>2002</b>год основания</span><span><b>3</b>зала в Томске</span><span><b>5+</b>младшая группа</span></div>
          <button className="link" onClick={() => go("/coaches")}>Познакомиться с тренерами <Arrow /></button>
        </div>
        <div className="club-start">
          <p className="tag">Первая тренировка</p>
          <h3>Начать проще,<br />чем кажется.</h3>
          <ol>
            <li><span>01</span><div><b>Выберите удобный зал</b><p>Три площадки и вечерние занятия по расписанию.</p></div></li>
            <li><span>02</span><div><b>Оставьте имя и телефон</b><p>Администратор свяжется с вами и подтвердит запись.</p></div></li>
            <li><span>03</span><div><b>Приходите попробовать</b><p>Спортивная форма, вода и желание начать. Пробное занятие бесплатно.</p></div></li>
          </ol>
          <button className="btn btn-red" onClick={() => book()}>Выбрать тренировку <Arrow /></button>
        </div>
      </section>

      <section className="why-sparta" aria-labelledby="why-sparta-title">
        <div className="why-gallery" aria-hidden="true">
          <img src="/photos/club/why-beginner.png" alt="" loading="lazy" decoding="async" />
          <img src="/photos/club/why-kids.png" alt="" loading="lazy" decoding="async" />
          <img src="/photos/disciplines/self-defense-01.png" alt="" loading="lazy" decoding="async" />
        </div>
        <div className="why-content">
          <h2 className="tag tag-light why-title" id="why-sparta-title">Почему Спарта</h2>
          <div className="reasons-over">
            {[
              ["01", "Начать можно с нуля", "Новички занимаются в отдельных группах, без давления.", "/photos/club/why-beginner.png"],
              ["02", "Группы по возрасту", "Занятия для детей, подростков и взрослых.", "/photos/club/why-kids.png"],
              ["03", "Техника самообороны", "Учимся защищать себя и близких.", "/photos/disciplines/self-defense-01.png"],
            ].map(([n, h, p, photo]) => (
              <article className="why-reason" key={n}>
                <img className="why-mobile-photo" src={photo} alt="" loading="lazy" decoding="async" />
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
            ["Залы", "Три площадки", "/gyms", "gym_irk"],
            ["Тренеры", "Команда клуба", "/coaches", "coach_0"],
            ["Направления", "Чему мы учим", "/disciplines", "disc_0"],
          ] as [string, string, Page, string][]
        ).map(([t, s, p, id]) => (
          <button key={p} className="tile" onClick={() => go(p)}>
            <Photo id={id} label={t} size="1200 × 1500" className="tile-ph">
              <p className="tag tag-light">{s}</p>
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

      <Photo id="cta" label="Баннер: ковёр / зал" size="2400 × 1000" className="cover cover-cta">
        <h2 className="cover-title cover-title-md">
          Первая тренировка —<br />
          <span className="red">начало пути</span>
        </h2>
        <button className="btn btn-red" onClick={() => book()}>
          Записаться <Arrow />
        </button>
      </Photo>
    </main>
  );
}

function PageHead({ title }: { id: string; title: string; text: string }) {
  return <h1 className="page-title-sr">{title}</h1>;
}

function Gyms({ book }: { book: Book }) {
  const [openPhoto, setOpenPhoto] = useState<string | null>(null);
  const [gymPhoto, setGymPhoto] = useState(2);
  const movePhoto = (step: number) => setGymPhoto((current) => (current + step + IRKUTSK_GYM_PHOTOS.length) % IRKUTSK_GYM_PHOTOS.length);
  return (
    <main>
      <PageHead
        id="gymsHead"
        title="Залы"
        text="Три площадки клуба в Томске."
      />
      <section className="gyms">
        {GYMS.map((g, i) => (
          <Photo
            key={g.id}
            id={`gym_${g.id}`}
            label={`${g.name} — фото зала`}
            size="2000 × 1200"
            className="cover gym-cover"
            srcOverride={g.id === "irk" ? IRKUTSK_GYM_PHOTOS[gymPhoto].src : undefined}
          >
            <span className="gym-n">0{i + 1} / 0{GYMS.length}</span>
            {g.id === "irk" && <div className="gym-cover-arrows" aria-label="Листать фото зала">
              <button type="button" onClick={() => movePhoto(-1)} aria-label="Предыдущее фото зала"><Chevron previous /></button>
              <button type="button" onClick={() => movePhoto(1)} aria-label="Следующее фото зала"><Chevron /></button>
            </div>}
            <div className="gym-over">
              <div>
                <p className="tag tag-light">{g.name}</p>
                <h2>{g.address}</h2>
                <p className="gym-note">{g.note}</p>
              </div>
              <div className="gym-side">
                <dl>
                  <div>
                    <dt>Режим</dt>
                    <dd>{g.hours}</dd>
                  </div>
                  <div>
                    <dt>Направления</dt>
                    <dd>{g.disciplines.join(" · ")}</dd>
                  </div>
                </dl>
                <div className="row">
                  <button className="btn btn-red" onClick={() => book({ gym: g.address })}>
                    Записаться <Arrow />
                  </button>
                  <a
                    className="btn btn-white-line"
                    href={`https://2gis.ru/tomsk/search/${encodeURIComponent("Томск, " + g.address)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    В 2ГИС
                  </a>
                  <button className="btn btn-white-line" onClick={() => setOpenPhoto(g.id)}>Фото зала</button>
                </div>
              </div>
            </div>
          </Photo>
        ))}
      </section>
      {openPhoto && (
        <Modal centered className="gym-modal" onClose={() => setOpenPhoto(null)}>
          <h2 className="m-title">{GYMS.find((g) => g.id === openPhoto)?.name}</h2>
          {openPhoto === "irk" ? (
            <PhotoGallery selected={gymPhoto} setSelected={setGymPhoto} movePhoto={movePhoto} />
          ) : (
            <>
              <Photo id={`gym_${openPhoto}`} label="Фотография зала" size="2000 × 1200" className="gym-photo-large" />
              <p className="m-note">Фотографии этого зала пока не добавлены.</p>
            </>
          )}
        </Modal>
      )}
    </main>
  );
}

const IRKUTSK_GYM_PHOTOS = [
  { src: "/photos/gyms/irk-01.png", alt: "Вид на входную зону зала на Иркутском тракте" },
  { src: "/photos/gyms/irk-02.png", alt: "Гардероб зала на Иркутском тракте" },
  { src: "/photos/gyms/irk-03.png", alt: "Тренировочная зона с татами и грушами" },
  { src: "/photos/gyms/irk-04.png", alt: "Борцовский зал с жёлто-синим покрытием" },
];

function PhotoGallery({ selected, setSelected, movePhoto, photos = IRKUTSK_GYM_PHOTOS, caption = "Иркутский тракт, 68" }: { selected: number; setSelected: (index: number) => void; movePhoto: (step: number) => void; photos?: { src: string; alt: string }[]; caption?: string }) {
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

type CoachProfile = { rank?: string; startedYear?: number; referee?: string; about: string };
const COACH_PROFILES: CoachProfile[] = [
  { rank: "6 дан CJJIF", about: "Руководитель клуба «Спарта Плюс». Проводит тренировки в основном зале на Иркутском тракте и в корпусе СибГМУ." },
  { about: "Тренер клуба «Спарта Плюс». Проводит занятия на проспекте Фрунзе, 115/3." },
  { about: "Тренер клуба «Спарта Плюс». Проводит занятия в основном зале на Иркутском тракте, 68." },
];

function Coaches({ book, trainings, exceptions, scheduleLoading, scheduleError }: { book: Book; trainings: Training[]; exceptions: Record<string, boolean>; scheduleLoading: boolean; scheduleError: string }) {
  const [selected, setSelected] = useState<number | null>(null);
  const coach = selected !== null ? COACHES[selected] : null;
  const profile = selected !== null ? COACH_PROFILES[selected] : null;
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
      <section className="coaches">
        {COACHES.map((c, i) => (
          <Photo
            key={c.name}
            id={`coach_${i}`}
            label={`Портрет: ${c.name}`}
            size="1200 × 1600"
            className={`coach-ph coach-ph--${i}`}
          >
            <p className="coach-role">{c.role}</p>
            <h2>{c.name}</h2>
            <p className="coach-tags">
              {c.tags}
            </p>
            <button className="coach-discover" onClick={() => setSelected(i)} aria-label={`Узнать больше: ${c.name}`}>
              <span><small>{COACH_PROFILES[i].rank ?? "Тренер клуба"}</small><b>Ознакомиться</b></span><span className="coach-discover-arrow"><Arrow /></span>
            </button>
          </Photo>
        ))}
      </section>
      {coach && profile && selected !== null && <Modal centered className="coach-modal" onClose={() => setSelected(null)}>
        <div className="coach-profile-photo"><Photo id={`coach_${selected}`} label={coach.name} size="1200 × 1600" className={`coach-profile-image coach-ph--${selected}`} /></div>
        <div className="coach-profile-copy"><p className="tag">Команда Спарты</p><h2>{coach.name}</h2><p className="coach-profile-role">{coach.role}</p><p>{profile.about}</p>
          <dl className="coach-credentials">{profile.rank && <div><dt>Дан / квалификация</dt><dd>{profile.rank}</dd></div>}{profile.startedYear && <div><dt>Тренерский стаж</dt><dd>С {profile.startedYear} года</dd></div>}{profile.referee && <div><dt>Судейская категория</dt><dd>{profile.referee}</dd></div>}</dl>
          <p className="coach-details-note">{profile.rank ? "Сведения о тренерском стаже и судейской категории добавим после уточнения у клуба." : "Стаж, звания, дан и судейскую категорию добавим после уточнения у клуба."}</p>
          <h3>Где и когда тренирует</h3><div className="coach-profile-schedule">{regular.length ? regular.map((item) => <div key={item.id}><b>{item.days.slice().sort((a,b) => ((a + 6) % 7) - ((b + 6) % 7)).map((day) => ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][day]).join(" · ")}<span>{item.time}–{item.end}</span></b><p>{item.gym}</p></div>) : <p>Время занятий уточнит администратор.</p>}</div>
          <button className="btn btn-red" onClick={() => { const slot = upcomingSlots(trainings).find((item) => item.coach === coach.name && exceptions[`${item.date}:${item.id}`] !== false); setSelected(null); book(slot ? { coach: coach.name, sessionId: slot.id, gym: slot.gym, date: slot.date, time: slot.time } : { coach: coach.name }); }}>Записаться к тренеру <Arrow /></button>
        </div>
      </Modal>}
    </main>
  );
}

function Disciplines({ book }: { book: Book }) {
  return (
    <main>
      <PageHead
        id="disciplinesHead"
        title="Направления"
        text="Чему мы обучаем. Не знаете, что выбрать — приходите на пробное, тренер подскажет."
      />
      <section className="disc">
        {DISCIPLINES.map((d, i) => (
          <article className="discipline-row" key={d.key}>
          <Photo
            id={`disc_${i}`}
            label={d.name}
            size="1600 × 1200"
            className={`disc-ph${i === 0 ? " disc-bjj" : ""}${d.key === "Самооборона" ? " disc-self-defense" : ""}${d.key === "Грэпплинг" ? " disc-grappling" : ""}`}
            secondarySrc={d.key === "Самооборона" ? "/photos/disciplines/self-defense-02.png" : undefined}
          >
            <div className="disc-top">
              <span>0{i + 1}</span>
              <span>{d.level}</span>
            </div>
            <h2>{d.name}</h2>
          </Photo>
            <div className="discipline-copy">
              <span className="discipline-copy-number">0{i + 1} / 0{DISCIPLINES.length}</span>
              <p>{d.text}</p>
              {d.key === "Грэпплинг" && <p className="disc-credit">Фото: s.efimov70 · @Officer1Pupsik</p>}
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

function Prices({ choose }: { choose: (p: Plan) => void }) {
  return (
    <main className="membership-page">
      <div className="section-heading"><p className="tag">Занятия в Спарте</p><h1>Сначала попробуй.<br />Потом выбирай.</h1><p>Первая тренировка — знакомство с клубом. Для регулярных занятий — один абонемент на месяц.</p></div>
      <section className="membership-options" aria-label="Варианты занятий">
        <article className="membership-option membership-trial">
          <div className="membership-label"><span>01 / Знакомство</span><b>Для первого визита</b></div>
          <h2>Пробная<br />тренировка</h2><p className="membership-value">Бесплатно</p>
          <p>Познакомьтесь с тренером и почувствуйте, как проходят занятия.</p>
          <ul><li>Для себя или ребёнка</li><li>Подойдёт без опыта</li><li>Поможем выбрать группу</li></ul>
          <button className="btn btn-red" onClick={() => choose(PLANS[0])}>Записаться на пробное <Arrow /></button>
        </article>
        <article className="membership-option">
          <div className="membership-label"><span>02 / Регулярные занятия</span><b>Безлимит</b></div>
          <h2>Месяц<br />тренировок</h2><p className="membership-value membership-value-pending">Стоимость уточняется</p>
          <p>Тренируйтесь в своём ритме. Абонемент действует в течение календарного месяца.</p>
          <ul><li>Занятия по расписанию клуба</li><li>Без ограничения числа посещений</li><li>Учёт оплаты у администратора</li></ul>
          <button className="btn btn-black" onClick={() => choose(PLANS[1])}>Обсудить абонемент <Arrow /></button>
        </article>
      </section>
      <div className="membership-help"><span>Не знаете, с чего начать?</span><p>Оставьте заявку на пробное. Администратор поможет выбрать зал и подходящую тренировку.</p><button className="link" onClick={() => choose(PLANS[0])}>Помогите выбрать <Arrow /></button></div>
      <section className="membership-faq"><div><p className="tag">Перед первым визитом</p><h2>Ещё пара<br />вопросов.</h2></div><div>{[
        ["Что взять с собой?", "Удобную спортивную форму и воду. Если понадобится специальная экипировка, тренер расскажет о ней заранее."],
        ["Можно записать ребёнка?", "Да. Выберите «Мой ребёнок» в форме, укажите его имя и возраст, а также свой телефон для связи."],
        ["Можно ли заниматься без подготовки?", "Да, можно начать с нуля. Расскажите администратору о своём опыте — он поможет подобрать группу."],
        ["Как оплатить абонемент?", "Стоимость и способ оплаты уточнит администратор клуба. После оплаты он отметит ваш абонемент за выбранный месяц."],
      ].map(([q, a]) => <details key={q}><summary>{q}<span aria-hidden="true">+</span></summary><p>{a}</p></details>)}</div></section>
    </main>
  );
}

function weekDates(offset: number) {
  const start = new Date();
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7) + offset * 7);
  return Array.from({ length: 7 }, (_, i) => { const date = new Date(start); date.setDate(start.getDate() + i); return date; });
}

function Schedule({ book, trainings, exceptions, scheduleLoading, scheduleError }: { book: Book; trainings: Training[]; exceptions: Record<string, boolean>; scheduleLoading: boolean; scheduleError: string }) {
  const [week, setWeek] = useState(0);
  const [gym, setGym] = useState("all");
  const [coach, setCoach] = useState("all");
  const dates = weekDates(week);
  const gyms = GYMS.filter((item) => gym === "all" || item.address === gym);
  const slotsFor = (date: Date, address: string) => trainings.filter((item) => item.active && item.days.includes(date.getDay()) && item.gym === address && (coach === "all" || item.coach === coach)).sort((a, b) => a.time.localeCompare(b.time));
  const hasResults = dates.some((date) => gyms.some((item) => slotsFor(date, item.address).length > 0));
  return (
    <main className="timetable-page">
      <div className="section-heading timetable-heading"><div><p className="tag">Расписание / Томск</p><h1>Найди время<br />для себя.</h1><p>Выберите зал и тренировку. Записаться можно прямо из расписания.</p></div><div className="timetable-offer"><span>Первый раз?</span><b>Попробуйте бесплатно.</b><button className="link" onClick={() => book()}>Помогите выбрать <Arrow /></button></div></div>
      <section className="timetable-section" aria-label="Расписание тренировок">
        <div className="timetable-toolbar"><div className="gym-tabs" aria-label="Выбор зала"><button aria-pressed={gym === "all"} onClick={() => setGym("all")}>Все залы</button>{GYMS.map((g) => <button key={g.id} aria-pressed={gym === g.address} onClick={() => setGym(g.address)}>{shortGym(g.address)}</button>)}</div><label className="timetable-coach"><span>Тренер</span><select value={coach} onChange={(e) => setCoach(e.target.value)}><option value="all">Все тренеры</option>{COACHES.map((c) => <option key={c.name} value={c.name}>{shortCoach(c.name)}</option>)}</select></label></div>
        <div className="timetable-week"><div><h2>Неделя тренировок</h2><p>Регулярное расписание · время Томска</p></div><div className="week-switch"><button aria-label="Предыдущая неделя" onClick={() => setWeek(Math.max(0, week - 1))} disabled={week === 0}><Chevron previous /></button><strong>{dates[0].toLocaleDateString("ru-RU", { day: "numeric", month: "short" })} — {dates[6].toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}</strong><button aria-label="Следующая неделя" onClick={() => setWeek(week + 1)}><Chevron /></button>{week > 0 && <button className="week-reset" onClick={() => setWeek(0)}>Эта неделя</button>}</div></div>
        {scheduleLoading && <p className="timetable-no-results" role="status">Загружаем расписание…</p>}
        {scheduleError && <p className="timetable-no-results" role="alert">{scheduleError}</p>}
        {!scheduleLoading && !scheduleError && !hasResults && <p className="timetable-no-results">По этим фильтрам занятий нет. Выберите другой зал или тренера.</p>}
        <table className="timetable">
          <caption className="page-title-sr">Тренировки по дням недели и залам</caption>
          <thead><tr><th scope="col">День</th>{gyms.map((g) => <th key={g.id} scope="col"><b>{g.name}</b><span>{g.address}</span></th>)}</tr></thead><tbody>
          {dates.map((date) => {
            const key = localDate(date);
            const dayEmpty = gyms.every((g) => slotsFor(date, g.address).length === 0);
            return <tr className={`${key === today() ? "is-today" : ""} ${dayEmpty ? "is-empty-day" : ""}`} key={key}><th scope="row"><b>{date.toLocaleDateString("ru-RU", { weekday: "long" })}</b><span>{date.toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}{key === today() && <em>Сегодня</em>}</span></th>{gyms.map((g) => { const slots = slotsFor(date, g.address); return <td key={g.id} className={!slots.length ? "is-empty-cell" : ""}><span className="timetable-mobile-gym">{g.name} · {shortGym(g.address)}</span>{slots.length ? slots.map((slot) => {
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

const CLUB_GALLERY = [
  { src: "/photos/club/hero.jpg", alt: "Команда клуба" },
  { src: "/photos/club/why-kids.png", alt: "Детские тренировки" },
  { src: "/photos/club/why-beginner.png", alt: "На тренировке" },
  { src: "/photos/disciplines/bjj.png", alt: "Бразильское джиу-джитсу" },
  { src: "/photos/disciplines/grappling.png", alt: "Грэпплинг", credit: "Фото: s.efimov70 · @Officer1Pupsik" },
  { src: "/photos/disciplines/self-defense-01.png", alt: "Самооборона" },
];
function Gallery() {
  const [selected, setSelected] = useState<number | null>(null);
  const movePhoto = (step: number) => setSelected((current) => ((current ?? 0) + step + CLUB_GALLERY.length) % CLUB_GALLERY.length);
  return <main><PageHead id="story" title="Галерея" text="Моменты тренировок и жизнь клуба." /><section className="gallery-page"><div className="gallery-heading"><p className="tag">Клуб в кадре</p><h2>Люди. Тренировки.<br />Характер.</h2><p>Знакомимся, учимся и растём вместе. Нажмите на фото, чтобы рассмотреть его ближе.</p></div><div className="gallery-grid">{CLUB_GALLERY.map((photo, i) => <button className="gallery-open" key={photo.src} onClick={() => setSelected(i)} aria-label={`Открыть фото: ${photo.alt}`}><Photo id={`club_gallery_${i}`} srcOverride={photo.src} label={photo.alt} size="1600 × 1200" className="gallery-tile"><span>{photo.alt}</span><span className="gallery-expand" aria-hidden="true">↗</span></Photo></button>)}</div></section>{selected !== null && <Modal centered className="gym-modal" label="Фотографии клуба" onClose={() => setSelected(null)}><h2 className="m-title">{CLUB_GALLERY[selected].alt}</h2><PhotoGallery photos={CLUB_GALLERY} caption={CLUB_GALLERY[selected].credit ?? "Спарта Плюс · Томск"} selected={selected} setSelected={setSelected} movePhoto={movePhoto} /></Modal>}</main>;
}

function Account({ bookings, book }: { bookings: Booking[]; book: Book }) {
  return <main>
    <PageHead id="story" title="Личный кабинет" text="Заявки на тренировку сохраняются в общей базе клуба." />
    <section className="account-page">
      <div className="account-card">
        <p className="tag">Участник или родитель</p>
        <h2>Ваши заявки</h2>
        <p>Запись работает без регистрации. История заявок и вход в аккаунт будут подключены отдельным этапом.</p>
        {bookings.length > 0 && <div className="account-records">
          <p>Заявки, отправленные в этой вкладке:</p>
          {bookings.map((item) => <div key={item.id}>
            <b>{item.sessionId ? `${fmtDate(item.date)} · ${item.time}` : "Время уточняется"}</b>
            <span>{item.gym}</span><small>Ожидает подтверждения</small>
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
  exceptions,
  onClose,
  onSubmit,
  centered = false,
}: {
  initial: Partial<Booking>;
  trainings: Training[];
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
    gym: initial.gym ?? suggested?.gym ?? GYMS[0].address,
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
            {GYMS.map((gym) => <option key={gym.id} value={gym.address}>{gym.address}</option>)}
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
          <span>Я даю согласие на обработку персональных данных на условиях <a href="/consent" target="_blank" rel="noopener noreferrer">Согласия</a>.</span>
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
  setTrainings,
  exceptions,
  setExceptions,
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
  onExit: () => void;
}) {
  const [tab, setTab] = useState<"overview" | "bookings" | "schedule" | "payments">("overview");
  const [gym, setGym] = useState("all");
  const [status, setStatus] = useState<"all" | BookingStatus>("all");
  const [search, setSearch] = useState("");
  const [payFilter, setPayFilter] = useState<"all" | "paid" | "pending">("all");
  const [payMonth, setPayMonth] = useState(today().slice(0, 7));
  const [newMember, setNewMember] = useState("");
  const [adding, setAdding] = useState(false);
  const [adminWeek, setAdminWeek] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);

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

  const setB = (id: string, s: BookingStatus) =>
    setBookings((l) => l.map((b) => (b.id === id ? { ...b, status: s } : b)));
  const markPaid = (id: string, method: string) =>
    setPayments((l) =>
      l.map((p) => (p.id === id ? { ...p, status: "paid", method, paidAt: today() } : p)),
    );
  const undoPaid = (id: string) => setPayments((l) => l.map((p) => p.id === id ? { ...p, status: "pending", method: "", paidAt: "" } : p));

  return (
    <div className="adm">
      <div className="demo-ribbon">Демо-панель · записи сохраняются только в этом браузере</div>
      <aside className="adm-side">
        <div className="adm-logo">
          <img src={logo} alt="" />
          <div>
            СПАРТА<small>Панель клуба</small>
          </div>
        </div>
        <nav>
          <button className={tab === "overview" ? "on" : ""} onClick={() => setTab("overview")}>
            Сводка
          </button>
          <button className={tab === "bookings" ? "on" : ""} onClick={() => setTab("bookings")}>
            Записи {newCount > 0 && <i>{newCount}</i>}
          </button>
          <button className={tab === "schedule" ? "on" : ""} onClick={() => setTab("schedule")}>Тренировки и расписание</button>
          <button className={tab === "payments" ? "on" : ""} onClick={() => setTab("payments")}>
            Оплаты {pending.length > 0 && <i>{pending.length}</i>}
          </button>
        </nav>
        <button className="adm-exit" onClick={onExit}>
          ← На сайт
        </button>
      </aside>

      <main className="adm-main">
        {tab === "overview" && (
          <>
            <h1 className="adm-h">Сводка</h1>
            <div className="kpis">
              <button
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
                  {bookings.filter((b) => b.date === today() && b.status !== "cancelled").length}
                </b>
              </div>
              <div className="kpi">
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
              </button>
            </div>
            <div className="admin-insights"><div><b>{bookings.filter((b) => b.kind === "Пробное").length}</b><span>пробных заявок</span></div><div><b>{bookings.filter((b) => b.status === "came").length}</b><span>отмечено посещений</span></div><div><b>{trainings.filter((item) => item.active).length}</b><span>активных шаблонов тренировок</span></div></div>
            <h2 className="adm-sub">Сегодня по залам</h2>
            <div className="by-gym">
              {GYMS.map((g) => {
                const n = bookings.filter(
                  (b) => b.gym === g.address && b.date === today() && b.status !== "cancelled",
                ).length;
                return (
                  <div key={g.id}>
                    <b>{n}</b>
                    <span>{g.address}</span>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {tab === "schedule" && <>
          <div className="adm-top"><div><h1 className="adm-h">Тренировки</h1><p className="admin-hint">Редактирование регулярных занятий и отмена конкретной даты.</p></div><button className="btn btn-black" onClick={() => setTrainings((list) => [...list, { id: uid(), days: [1], time: "18:00", end: "19:00", coach: COACHES[0].name, gym: GYMS[0].address, discipline: "Направление уточняется", active: false }])}>+ Добавить тренировку</button></div>
          <div className="admin-training-list">{trainings.map((item) => <article className="admin-training" key={item.id}><div><b>{item.time}–{item.end}</b><strong>{item.coach}</strong><span>{item.gym} · {item.days.map((day) => ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][day]).join(", ")}</span><small>{item.discipline}</small></div><div className="admin-training-actions"><button onClick={() => setEditing(editing === item.id ? null : item.id)}>Изменить</button><button onClick={() => setTrainings((list) => list.map((row) => row.id === item.id ? { ...row, active: !row.active } : row))}>{item.active ? "Приостановить" : "Включить"}</button></div>{editing === item.id && <div className="training-editor"><label>Тренер<select value={item.coach} onChange={(e) => setTrainings((list) => list.map((row) => row.id === item.id ? { ...row, coach: e.target.value } : row))}>{COACHES.map((c) => <option key={c.name}>{c.name}</option>)}</select></label><label>Зал<select value={item.gym} onChange={(e) => setTrainings((list) => list.map((row) => row.id === item.id ? { ...row, gym: e.target.value } : row))}>{GYMS.map((g) => <option key={g.id}>{g.address}</option>)}</select></label><label>Направление<select value={item.discipline} onChange={(e) => setTrainings((list) => list.map((row) => row.id === item.id ? { ...row, discipline: e.target.value } : row))}><option>Направление уточняется</option>{DISCIPLINES.map((d) => <option key={d.key}>{d.key}</option>)}</select></label><label>Начало<input type="time" value={item.time} onChange={(e) => setTrainings((list) => list.map((row) => row.id === item.id ? { ...row, time: e.target.value } : row))} /></label><label>Конец<input type="time" value={item.end} onChange={(e) => setTrainings((list) => list.map((row) => row.id === item.id ? { ...row, end: e.target.value } : row))} /></label><div className="day-checks">{[1,2,3,4,5,6,0].map((day) => <label key={day}><input type="checkbox" checked={item.days.includes(day)} onChange={() => setTrainings((list) => list.map((row) => row.id === item.id ? { ...row, days: row.days.includes(day) ? row.days.filter((d) => d !== day) : [...row.days, day] } : row))} />{["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][day]}</label>)}</div></div>}</article>)}</div>
          <div className="adm-top admin-calendar-head"><h2 className="adm-sub">Календарь недели</h2><div className="calendar-controls"><button disabled={adminWeek === 0} onClick={() => setAdminWeek(Math.max(0, adminWeek - 1))}>←</button><span>{weekDates(adminWeek)[0].toLocaleDateString("ru-RU")} — {weekDates(adminWeek)[6].toLocaleDateString("ru-RU")}</span><button onClick={() => setAdminWeek(adminWeek + 1)}>→</button></div></div>
          <div className="week-scroll"><div className="week-grid admin-week">{weekDates(adminWeek).map((date) => { const dateKey = localDate(date); return <div className="week-day" key={dateKey}><div className="week-day-head"><b>{date.toLocaleDateString("ru-RU", { weekday: "short" })}</b><strong>{date.getDate()}</strong></div>{trainings.filter((item) => item.active && item.days.includes(date.getDay())).sort((a,b) => a.time.localeCompare(b.time)).map((item) => { const held = exceptions[`${dateKey}:${item.id}`] !== false; const n = bookings.filter((booking) => booking.sessionId === item.id && booking.date === dateKey && booking.status !== "cancelled").length; return <article className={`week-class ${held ? "" : "week-class-off"}`} key={item.id}><b>{item.time}–{item.end}</b><strong>{item.coach}</strong><span>{item.gym}</span><small>{n} записей · {held ? item.discipline : "отменена"}</small>{!held && n > 0 && <small>Свяжитесь с записанными людьми</small>}<button onClick={() => setExceptions((old) => ({ ...old, [`${dateKey}:${item.id}`]: !held }))}>{held ? "Отменить дату" : "Вернуть занятие"}</button></article>; })}</div>; })}</div></div>
        </>}

        {tab === "bookings" && (
          <>
            <div className="adm-top">
              <h1 className="adm-h">Записи</h1>
              <button className="btn btn-black" onClick={() => setAdding(true)}>
                + Новая запись
              </button>
            </div>
            <div className="filters">
              <input className="record-search" aria-label="Поиск записи" placeholder="Имя, ребёнок или телефон" value={search} onChange={(e) => setSearch(e.target.value)} />
              <select value={gym} onChange={(e) => setGym(e.target.value)}>
                <option value="all">Все залы</option>
                {GYMS.map((g) => (
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
                    {b.status === "new" && <button className="ghost" onClick={() => navigator.clipboard.writeText(`Здравствуйте! Вы записаны на ${b.kind?.toLowerCase() ?? ""} занятие клуба «Спарта» ${fmtDate(b.date)} в ${b.time}, зал: ${b.gym}. Подтвердите, пожалуйста, что сможете прийти.`)}>Скопировать сообщение</button>}
                    {(b.status === "new" || b.status === "confirmed") && (
                      <button className="ghost" onClick={() => setB(b.id, "cancelled")}>
                        Отменить
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {tab === "payments" && (
          <>
            <div className="adm-top"><div><h1 className="adm-h">Абонементы</h1><p className="admin-hint">Безлимит на месяц. Оплата отмечается отдельно за каждый месяц.</p></div><label className="month-picker">Месяц <input type="month" value={payMonth} onChange={(e) => setPayMonth(e.target.value)} /></label></div>
            <form className="member-add" onSubmit={(e) => { e.preventDefault(); if (!newMember.trim()) return; setPayments((list) => [{ id: uid(), name: newMember.trim(), plan: "Безлимит на месяц", amount: 5000, date: today(), month: payMonth, status: "pending", method: "" }, ...list]); setNewMember(""); }}><input aria-label="Имя участника" placeholder="ФИО участника" value={newMember} onChange={(e) => setNewMember(e.target.value)} required /><button className="btn btn-black">+ Добавить участника на месяц</button></form>
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
          exceptions={exceptions}
          onClose={() => setAdding(false)}
          onSubmit={(b) => setBookings((l) => [{ ...b, id: uid(), status: "confirmed" }, ...l])}
        />
      )}
    </div>
  );
}
