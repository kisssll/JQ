# app/services/email_templates.py
"""Брендированные письма Руми: HTML + текстовый fallback.
Без внешних зависимостей — inline-стили (почтовые клиенты не любят <style>)."""
from typing import Optional, Tuple

ACCENT = "#c081b8"
_BG = "#faf9fb"
_MUTED = "#9a93a8"


def booking_status_email(
    *,
    title: str,
    intro: str,
    salon_name: str,
    service_name: str,
    when: str,
    track_url: Optional[str] = None,
    cta_label: str = "Отслеживать запись",
) -> Tuple[str, str]:
    """Возвращает (plain_text, html) для письма гостю о его брони."""
    # --- текстовый fallback ---
    lines = [title, "", intro, "",
             f"Салон:  {salon_name}", f"Услуга: {service_name}", f"Время:  {when}"]
    if track_url:
        lines += ["", f"Статус записи: {track_url}"]
    lines += ["", "— Руми · онлайн-запись в салоны красоты · rrumi.ru"]
    plain = "\n".join(lines)

    # --- HTML ---
    button = ""
    if track_url:
        button = (
            f'<tr><td align="center" style="padding:22px 28px 4px">'
            f'<a href="{track_url}" style="display:inline-block;background:{ACCENT};color:#fff;'
            f'text-decoration:none;font-weight:600;padding:13px 30px;border-radius:11px;'
            f'font-size:15px">{cta_label} →</a></td></tr>'
        )

    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:{_BG};font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;color:#1a1523">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};padding:28px 12px">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 6px 28px rgba(20,10,40,.07)">
        <tr><td style="background:{ACCENT};padding:20px 28px">
          <span style="color:#fff;font-size:22px;font-weight:800;letter-spacing:-.5px">руми<span style="opacity:.65">.</span></span>
        </td></tr>
        <tr><td style="padding:28px 28px 6px">
          <h1 style="margin:0 0 10px;font-size:21px;line-height:1.25">{title}</h1>
          <p style="margin:0;color:#6b6577;font-size:15px;line-height:1.55">{intro}</p>
        </td></tr>
        <tr><td style="padding:18px 28px 0">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};border-radius:12px">
            <tr><td style="padding:14px 16px 4px;color:{_MUTED};font-size:13px;width:72px">Салон</td><td style="padding:14px 16px 4px;font-size:14px;font-weight:600">{salon_name}</td></tr>
            <tr><td style="padding:4px 16px;color:{_MUTED};font-size:13px">Услуга</td><td style="padding:4px 16px;font-size:14px;font-weight:600">{service_name}</td></tr>
            <tr><td style="padding:4px 16px 14px;color:{_MUTED};font-size:13px">Время</td><td style="padding:4px 16px 14px;font-size:14px;font-weight:600">{when}</td></tr>
          </table>
        </td></tr>
        {button}
        <tr><td style="padding:24px 28px 26px;color:{_MUTED};font-size:12px;line-height:1.5;border-top:1px solid #f0eef4">
          Письмо от сервиса онлайн-записи Руми · <a href="https://rrumi.ru" style="color:{ACCENT};text-decoration:none">rrumi.ru</a><br>
          Если запись оформляли не вы — просто проигнорируйте это письмо.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return plain, html
