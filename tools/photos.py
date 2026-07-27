#!/usr/bin/env python3
"""
Подгоняет карточки сетки под фотографии — без вуалей и затемнений.

У Apple текст в плитке лежит прямо на изображении: никаких полупрозрачных
шторок поверх кадра нет. Работает это потому, что кадр подготовлен — под
надписью спокойное место нужной яркости.

Скрипт делает ту же подготовку автоматически. Для каждой фотографии он:

  1. Считает, какая часть кадра видна в карточке (обрезка cover).
  2. Перебирает вертикальное положение кадра с шагом 2%.
  3. Для каждого положения смотрит верхнюю полосу — ту, где лежит текст:
     насколько она ровная и какой контраст даст белый или тёмный текст.
  4. Выбирает положение с лучшим сочетанием и записывает в разметку
     object-position, а также цвет текста (класс --on-light для светлых мест).

Если ни одно положение не даёт нормы 4.5 — печатает это отдельно: значит
фотография не годится для надписи поверх, нужна другая.

Запуск: python3 tools/photos.py
"""
import os, re, sys, tempfile
import numpy as np
from PIL import Image

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")

CARD_AR   = 714 / 580     # пропорция карточки на 1440
TEXT_ZONE = 0.38          # верхняя доля карточки, занятая текстом
NORM      = 4.5           # норма контраста для мелкого текста

CARD_RE = re.compile(r'<div class="(water-card[^"]*)">\s*\n\s*<img src="([^"]+)"', re.M)


def srgb(c):
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def load(path):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (0, 0, 0))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    return im.convert("RGB")


def analyse(path):
    """Лучшее положение кадра, цвет текста и достижимый контраст."""
    im = load(path)
    W, H = im.size
    a = np.asarray(im).astype(float)
    lin = 0.2126 * a[:, :, 0] + 0.7152 * a[:, :, 1] + 0.0722 * a[:, :, 2]

    vis_h = min(H, W / CARD_AR)          # высота видимой части при cover
    band_h = max(4, int(vis_h * TEXT_ZONE))
    best = None

    for pos in range(0, 101, 2):
        top = int((H - vis_h) * pos / 100)
        band = lin[top: top + band_h]
        if band.size == 0:
            continue
        mean = band.mean() / 255
        L = srgb(mean * 255)
        c_white = 1.05 / (L + 0.05)                 # белый текст
        c_dark  = (L + 0.05) / (srgb(29) + 0.05)    # текст #1d1d1f
        light = c_dark > c_white
        contrast = max(c_white, c_dark)
        spread = band.std() / 255                    # ровность фона
        score = contrast - 4.0 * spread              # ровное место важнее яркого
        if best is None or score > best["score"]:
            best = {"score": score, "pos": pos, "light": light,
                    "contrast": contrast, "spread": spread}
    return best


def main():
    html = open(INDEX, encoding="utf-8").read()
    out = html
    changed = 0
    bad = []

    print(f"{'фото':<40} {'кадр':>6} {'текст':>8} {'контраст':>9}")
    for classes, src in CARD_RE.findall(html):
        path = os.path.join(ROOT, src.split("?")[0])
        if not os.path.exists(path):
            print(f"{src:<40} файл не найден")
            continue

        r = analyse(path)
        if r is None:
            continue

        light = r["light"]
        has = "water-card--on-light" in classes
        new_classes = classes
        if light and not has:
            new_classes = classes + " water-card--on-light"
        elif not light and has:
            new_classes = classes.replace(" water-card--on-light", "")
        if new_classes != classes:
            out = out.replace(f'<div class="{classes}">', f'<div class="{new_classes}">', 1)
            changed += 1

        # положение кадра пишем инлайном — оно привязано к конкретному файлу
        marker = f'<img src="{src}"'
        pos_style = f'style="object-position: 50% {r["pos"]}%"'
        idx = out.find(marker)
        if idx != -1:
            end = out.find(">", idx)
            tag = out[idx:end]
            tag_new = re.sub(r'\s*style="object-position:[^"]*"', "", tag) + " " + pos_style
            out = out[:idx] + tag_new + out[end:]

        mark = "" if r["contrast"] >= NORM else "   ← мало, нужна другая фотография"
        if r["contrast"] < NORM:
            bad.append(os.path.basename(src))
        print(f"{os.path.basename(src):<40} {str(r['pos'])+'%':>6} "
              f"{'тёмный' if light else 'белый':>8} {r['contrast']:>9.1f}{mark}")

    if out != html:
        fd, tmp = tempfile.mkstemp(dir=ROOT, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(out)
        os.replace(tmp, INDEX)

    print(f"\nОбновлено карточек: {changed}")
    if bad:
        print("Фотографии, на которых надпись не читается ни при каком кадре:")
        for b in bad:
            print(f"  • {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
