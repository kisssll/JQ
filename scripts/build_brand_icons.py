#!/usr/bin/env python
"""Пересборка логотипа и иконок из фирменного исходника.

Запуск:  .venv/bin/python scripts/build_brand_icons.py

Исходник — static/images/rumi-logo-source.png (прозрачный фон). Отсюда
получаются логотип для шапки, favicon и иконки приложения. Держим скриптом,
а не руками: при смене логотипа достаточно заменить исходник и перезапустить,
иначе набор из десяти файлов неизбежно разъедется.
"""
import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "static/images/rumi-logo-source.png"
IMG = ROOT / "static/images"
ICO = ROOT / "static/icons"

# Фон иконок приложения — из фирменной тёмной версии логотипа.
DARK = (30, 30, 30)


def _fit(logo: Image.Image, canvas: int, occupy: float, background=None) -> Image.Image:
    """Логотип по центру квадрата; occupy — доля ширины, которую он занимает."""
    scaled = logo.copy()
    scaled.thumbnail((int(canvas * occupy), canvas), Image.LANCZOS)
    base = Image.new(
        "RGBA", (canvas, canvas), (*background, 255) if background else (0, 0, 0, 0)
    )
    base.paste(scaled, ((canvas - scaled.width) // 2, (canvas - scaled.height) // 2), scaled)
    return base


def main() -> None:
    logo = Image.open(SRC).convert("RGBA")
    logo = logo.crop(logo.split()[-1].getbbox())      # снимаем прозрачные поля

    # Логотип шапки — с запасом под экраны высокой плотности
    head = logo.copy()
    head.thumbnail((480, 480), Image.LANCZOS)
    head.save(IMG / "rumi-logo.png", optimize=True)
    head.save(IMG / "rumi-logo.webp", "WEBP", quality=90, method=6)

    # Favicon — прозрачный, знак во всю ширину
    for px in (16, 32, 48, 96):
        _fit(logo, px, 1.0).save(ICO / f"favicon-{px}.png", optimize=True)

    # Иконки приложения — на тёмном фоне
    for px, name in ((192, "icon-192.png"), (512, "icon-512.png"),
                     (180, "apple-touch-icon.png")):
        _fit(logo, px, 0.82, DARK).convert("RGB").save(ICO / name, optimize=True)

    # maskable: система обрезает края, безопасная зона — центральные 80%
    _fit(logo, 512, 0.60, DARK).convert("RGB").save(
        ICO / "icon-maskable-512.png", optimize=True
    )
    print("готово")


if __name__ == "__main__":
    main()
