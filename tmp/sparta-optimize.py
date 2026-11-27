from pathlib import Path
from PIL import Image, ImageOps
source = Path("C:/Users/HONOR/Desktop/спарта/данные")
for name, dest in [("самбо.jfif","sambo-club.webp"),("джиу джитсу.jfif","jiu-jitsu-club.webp")]:
    image = ImageOps.exif_transpose(Image.open(source / name)).convert("RGB")
    image.thumbnail((1450,1450), Image.Resampling.LANCZOS)
    image.save(Path("static/sport/sparta/photos/disciplines")/dest, quality=87, method=6)
dmitry = ImageOps.exif_transpose(Image.open(source / "тренера" / "Дмитрий михайлович Давыдов.png"))
print(dmitry.size)
dmitry.thumbnail((380,380))
dmitry.save("tmp/sparta-dmitry-source.png")
