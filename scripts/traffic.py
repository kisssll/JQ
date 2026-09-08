#!/usr/bin/env python3
"""Отчёт по журналу запросов Caddy: кто заходил на сайт и куда.

Запускать НА СЕРВЕРЕ:

    python3 /opt/rumi/be/scripts/traffic.py            # за сегодня
    python3 /opt/rumi/be/scripts/traffic.py --days 7   # за неделю
    python3 /opt/rumi/be/scripts/traffic.py --days 3 --bots

Журнал пишет edge-Caddy (см. Caddyfile, блок log). Скрипт сам достаёт его из
контейнера, включая уже провёрнутые файлы. Ничего не меняет — только читает.

Чем отличается от Яндекс.Метрики: Метрика видит только тех, кто согласился на
аналитические cookie и у кого работает JavaScript. Журнал видит ВСЕХ, включая
поисковых роботов и сканеры уязвимостей, — поэтому цифры здесь всегда больше,
и одно другое не заменяет.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import subprocess
import sys

CONTAINER = "rumi-edge-caddy"
LOG_GLOB = "/var/log/caddy"

# Не страницы: статика, служебное, вызовы из браузера уже открытой страницы.
NOT_A_PAGE = re.compile(
    r"^/(static/|uploads/|api/|health$|sw\.js$|offline$|manifest\.webmanifest$|robots\.txt$|favicon)"
)
BOT_UA = re.compile(
    r"bot|spider|crawler|curl|wget|python-requests|go-http|scrapy|headless|"
    r"facebookexternalhit|telegram|slackbot|whatsapp|preview",
    re.I,
)
# Сканеры уязвимостей ходят с обычным браузерным User-Agent — по подписи их не
# отличить. Зато они выдают себя адресами: ищут чужие движки, которых у нас
# отродясь не было. Без этого 76 заходов на /wp-admin/install.php попадали в
# «живые посетители» и раздували статистику вдвое.
SCAN_PATH = re.compile(
    r"^/(wp-|wordpress|xmlrpc|phpmyadmin|administrator|components/|vendor/|cgi-bin/|"
    r"autodiscover|owa/|boaform|\.git|\.env|\.aws|\.vscode|\.well-known/traffic)"
    r"|\.(php|aspx?|jsp|cgi|bak|sql|ini)$",
    re.I,
)
# Роботы поисковиков — их присутствие показывает, идёт ли индексация.
SEARCH_BOTS = {
    "YandexBot": "Яндекс", "YandexMobileBot": "Яндекс (моб.)",
    "Googlebot": "Google", "bingbot": "Bing", "Mail.RU_Bot": "Mail.ru",
}


def read_log(path: str | None) -> list[dict]:
    if path:
        raw = open(path, encoding="utf-8", errors="replace").read()
    else:
        # *.log — текущий и провёрнутые; *.gz — сжатые старые.
        cmd = ["docker", "exec", CONTAINER, "sh", "-c",
               f"cat {LOG_GLOB}/*.log 2>/dev/null; zcat {LOG_GLOB}/*.gz 2>/dev/null"]
        try:
            raw = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        except FileNotFoundError:
            sys.exit("docker не найден — скрипт запускают на сервере")
        except subprocess.CalledProcessError as exc:
            sys.exit(f"не смог прочитать журнал: {exc.stderr.strip() or exc}")

    out = []
    for line in raw.splitlines():
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if "request" in rec and "ts" in rec:
            out.append(rec)
    return out


def ua_of(rec: dict) -> str:
    return (rec["request"].get("headers", {}).get("User-Agent") or ["—"])[0]


def bar(n: int, top: int, width: int = 24) -> str:
    return "▇" * max(1, round(n / top * width)) if top else ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Отчёт по журналу запросов Caddy")
    ap.add_argument("--days", type=int, default=1, help="за сколько последних суток (по умолчанию 1)")
    ap.add_argument("--bots", action="store_true", help="показать роботов и сканеры подробно")
    ap.add_argument("--file", help="читать журнал из файла, а не из контейнера")
    args = ap.parse_args()

    records = read_log(args.file)
    if not records:
        sys.exit("журнал пуст — проверьте, что контейнер запущен и логи включены")

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    rows = [r for r in records
            if dt.datetime.fromtimestamp(r["ts"], dt.timezone.utc) >= since]
    if not rows:
        print(f"За последние {args.days} сут. запросов нет.")
        return

    # Третий признак — поведение адреса. Сканер за один заход перебирает
    # десятки несуществующих путей: если у адреса почти всё в 404, это не
    # человек, чем бы он ни представлялся.
    per_ip = collections.defaultdict(list)
    for r in rows:
        per_ip[r["request"].get("client_ip")].append(r)
    scanner_ips = {
        ip for ip, reqs in per_ip.items()
        if len(reqs) >= 3
        and sum(1 for r in reqs if r["status"] == 404 or SCAN_PATH.search(r["request"]["uri"])) / len(reqs) >= 0.6
    }

    def is_bot(r) -> bool:
        return (BOT_UA.search(ua_of(r)) is not None
                or SCAN_PATH.search(r["request"]["uri"]) is not None
                or r["request"].get("client_ip") in scanner_ips)

    people, bots = [], []
    for r in rows:
        (bots if is_bot(r) else people).append(r)

    # Просмотр страницы — только успешно отданная страница: 404 и редиректы
    # просмотром не являются, иначе перебор чужих адресов выглядит трафиком.
    human_pages = [r for r in people
                   if r["status"] == 200
                   and not NOT_A_PAGE.match(r["request"]["uri"].split("?")[0])]
    ips = {r["request"].get("client_ip") for r in human_pages}

    first = dt.datetime.fromtimestamp(min(r["ts"] for r in rows), dt.timezone.utc)
    print(f"\nПериод: с {first:%d.%m %H:%M} UTC, {args.days} сут.")
    print("─" * 52)
    print(f"  Живые посетители   {len(ips):>6} адресов, {len(human_pages)} просмотров страниц")
    print(f"  Роботы и сканеры   {len(bots):>6} запросов")
    print(f"  Всего запросов     {len(rows):>6} (со статикой и картинками)")

    # По дням
    by_day = collections.Counter(
        dt.datetime.fromtimestamp(r["ts"], dt.timezone.utc).date() for r in human_pages)
    if len(by_day) > 1:
        print("\nПросмотры страниц по дням")
        top = max(by_day.values())
        for day in sorted(by_day):
            print(f"  {day:%d.%m}  {by_day[day]:>4}  {bar(by_day[day], top)}")

    print("\nСамые посещаемые страницы")
    paths = collections.Counter(r["request"]["uri"].split("?")[0] for r in human_pages)
    for path, n in paths.most_common(10):
        print(f"  {n:>4}  {path}")

    # Откуда пришли — только внешние источники, свои переходы не считаем.
    refs = collections.Counter()
    for r in human_pages:
        ref = (r["request"].get("headers", {}).get("Referer") or [""])[0]
        if ref and "rrumi.ru" not in ref.lower():
            refs[re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", ref.lower())] += 1
    print("\nОткуда пришли" if refs else "\nОткуда пришли: внешних переходов нет")
    for src, n in refs.most_common(8):
        print(f"  {n:>4}  {src}")

    # Поисковые роботы: идёт ли индексация
    crawlers = collections.Counter()
    for r in bots:
        ua = ua_of(r)
        for needle, name in SEARCH_BOTS.items():
            if needle.lower() in ua.lower():
                crawlers[name] += 1
    print("\nПоисковые роботы" if crawlers
          else "\nПоисковые роботы: не заходили — сайт ещё не индексируется")
    for name, n in crawlers.most_common():
        print(f"  {n:>4}  {name}")

    # Ошибки
    errors = collections.Counter(r["status"] for r in rows if r["status"] >= 400)
    if errors:
        print("\nОтветы с ошибкой")
        for code, n in sorted(errors.items()):
            note = ""
            if code == 404:
                scans = sum(1 for r in bots if r["status"] == 404)
                note = f"  (из них {scans} — роботы и сканеры, это шум)"
            if code >= 500:
                note = "  ← ЭТО НАДО СМОТРЕТЬ"
            print(f"  {n:>4}  {code}{note}")

    if args.bots:
        print("\nРоботы и сканеры подробно")
        for ua, n in collections.Counter(ua_of(r) for r in bots).most_common(15):
            print(f"  {n:>4}  {ua[:78]}")

    print()


if __name__ == "__main__":
    main()
