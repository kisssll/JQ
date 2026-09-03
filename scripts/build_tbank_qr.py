#!/usr/bin/env python
"""Пересборка QR-кода на партнёрскую страницу Т-Банка.

Запуск:  .venv/bin/python scripts/build_tbank_qr.py

Код собирается из той же константы, что и ссылки в разметке
(app.web.components.tbank.referral_url), поэтому не может разойтись с ней.
Запускать после любой правки ссылки — в том числе когда появится токен erid:
гайд Т-Банка требует добавлять его и в реферальную ссылку.
"""
import pathlib
import re
import sys

import qrcode
import qrcode.image.svg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.web.components.tbank import referral_url  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "static/images/tbank-qr.svg"


def main() -> None:
    url = referral_url()
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    assert qr.data_list[0].data.decode() == url, "в код попала не та ссылка"

    qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(OUT)

    svg = OUT.read_text()
    svg = svg.replace("<?xml version='1.0' encoding='UTF-8'?>\n", "")
    # Размер в миллиметрах не нужен: картинка тянется по контейнеру,
    # пропорции держит viewBox.
    svg = re.sub(r'width="[^"]*" height="[^"]*" ', "", svg, count=1)
    svg = svg.replace(
        "<svg ", '<svg role="img" aria-label="QR-код на страницу продуктов Т-Банка" ', 1
    )
    OUT.write_text(svg)
    print(f"готово: версия {qr.version}, {qr.modules_count} модулей, {len(url)} символов")


if __name__ == "__main__":
    main()
