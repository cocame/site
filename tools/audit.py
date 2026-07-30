#!/usr/bin/env python3
"""
Аудит сайта. Ищет ПОЛОМКИ, а не отклонения размеров (это делает check.py).

Пять групп проверок — каждая закрывает целый класс ошибок, которые раньше
находились случайно:

  1. CSS-здоровье   — лишние скобки, съеденные медиазапросы, дубли свойств
                      внутри одного правила (последнее молча побеждает).
  2. Структура      — однотипные блоки должны иметь одинаковый набор элементов.
                      Так ловится «у одной карточки нет затемнения».
  3. Контраст       — весь текст на всех блоках и ширинах против реального фона.
                      Так ловится «белая кнопка на белой плитке».
  4. Геометрия      — вылет за контейнер, отрицательные смещения, наложение
                      текста на фото там, где его быть не должно, гориз. скролл.
  5. Изображения    — не загрузилось, растянуто, апскейл больше 1.5x.

Запуск: python3 tools/audit.py
"""
import asyncio, re, sys
from playwright.async_api import async_playwright

ROOT = "/Users/cocame/Downloads/site"
PAGES = [f"file://{ROOT}/index.html", f"file://{ROOT}/tour.html"]
SITE = PAGES[0]
VIEWPORTS = [(390, 844), (768, 1024), (1440, 900), (2880, 1700)]

problems = []

# ─── Объявленные исключения. Каждое с причиной, молчком ничего не гасится ──
# Файлы сняты в исходном разрешении, которого не хватает на ретину 2880px.
# Кодом не лечится: нужен исходник большего размера от владелицы.
IGNORE = [
    "bana-illustration.webp: растягивается",
    "danang-hero.jpg: растягивается",
    "danang-mockup-desktop.webp: растягивается",
]


def bug(group, msg):
    if any(ig in msg for ig in IGNORE):
        return
    problems.append((group, msg))


# ─────────────────────────── 1. CSS-здоровье ────────────────────────────
def audit_css(html):
    css = html[html.index("<style>") + 7: html.index("</style>")]

    depth, line, extra = 0, 1, []
    for ch in css:
        if ch == "\n":
            line += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                extra.append(line)
                depth = 0
    for ln in extra:
        bug("CSS", f"лишняя закрывающая скобка (съедает следующее правило целиком)")
    if depth:
        bug("CSS", f"не закрыто скобок: {depth}")

    # дубли свойств внутри одного правила — последнее молча побеждает
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel, body = m.group(1).strip().splitlines()[-1].strip(), m.group(2)
        props = [p.split(":")[0].strip() for p in body.split(";") if ":" in p]
        dupes = {p for p in props if props.count(p) > 1 and not p.startswith("--")}
        for d in dupes:
            bug("CSS", f"свойство «{d}» задано дважды в правиле «{sel[:60]}» — "
                       f"побеждает последнее, первое можно потерять при правке")
    return css


async def audit_cssom(page, source_css):
    """Медиазапросы, которые есть в файле, но не дошли до браузера."""
    live = await page.evaluate("""() => {
      const out=[];
      for (const sh of document.styleSheets) {
        try { for (const r of sh.cssRules) if (r.type===4) out.push(r.conditionText||r.media.mediaText); }
        catch(e){}
      }
      return out;
    }""")
    in_file = re.findall(r"@media ([^{]+)\{", source_css)
    norm = lambda s: re.sub(r"\s+", "", s).lower()
    live_n = {norm(x) for x in live}
    for q in in_file:
        if norm(q) not in live_n:
            bug("CSS", f"медиазапрос @media {q.strip()} есть в файле, но браузер его не видит — "
                       f"правило проглочено синтаксической ошибкой выше")


# ─────────────────────── 2–5. проверки в браузере ───────────────────────
BROWSER_AUDIT = """() => {
  const res = {structure: [], geometry: [], images: [], texts: []};

  // ── структура: однотипные блоки должны быть одинаково устроены ──
  const groups = {'.water-card': [], '.tour-section': [], '.carousel__card': []};
  for (const sel of Object.keys(groups)) {
    const nodes = [...document.querySelectorAll(sel)].filter(n => !n.className.includes('placeholder'));
    const sets = nodes.map(n => [...n.children].map(c => c.className.split(' ')[0]).sort().join('|'));
    const counts = {};
    sets.forEach(s => counts[s] = (counts[s]||0)+1);
    const common = Object.entries(counts).sort((a,b)=>b[1]-a[1])[0];
    if (common) sets.forEach((s,i) => {
      if (s !== common[0]) {
        const name = (nodes[i].querySelector('h2,h3,p') || {}).textContent || sel;
        res.structure.push(`${sel} «${name.trim().slice(0,24)}» устроен иначе остальных: `
          + `[${s}] вместо [${common[0]}]`);
      }
    });
  }

  // ── геометрия ──
  document.querySelectorAll('.water-card, .tour-section, .carousel__card').forEach(el => {
    const r = el.getBoundingClientRect();
    const name = (el.querySelector('h2,h3,p') || {}).textContent?.trim().slice(0,24) || el.className.split(' ')[0];
    [...el.children].forEach(ch => {
      const cr = ch.getBoundingClientRect();
      if (cr.width === 0 || cr.height === 0) return;
      const out = Math.max(0, r.top - cr.top) + Math.max(0, cr.bottom - r.bottom)
                + Math.max(0, r.left - cr.left) + Math.max(0, cr.right - r.right);
      if (out > 24 && getComputedStyle(el).overflow === 'visible')
        res.geometry.push(`«${name}»: элемент .${ch.className.split(' ')[0]} вылезает на ${Math.round(out)}px`);
    });
    // в карточках сетки текст не должен пересекаться с фотографией
    if (el.matches('.water-card')) {
      const body = el.querySelector('.water-card__body'), img = el.querySelector('img');
      if (body && img) {
        const b = body.getBoundingClientRect(), i = img.getBoundingClientRect();
        const overlap = Math.min(b.bottom, i.bottom) - Math.max(b.top, i.top);
        if (overlap > 4) res.geometry.push(`«${name}»: текст заходит на фото на ${Math.round(overlap)}px `
          + `— по архитектуре они пересекаться не должны`);
      }
    }
  });
  if (document.documentElement.scrollWidth > innerWidth + 1)
    res.geometry.push(`горизонтальный скролл: ${document.documentElement.scrollWidth} > ${innerWidth}`);

  // ── изображения ──
  document.querySelectorAll('img').forEach(img => {
    const r = img.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    /* Ленивые картинки ниже экрана ещё не начали грузиться — это не поломка */
    if (!img.complete || !img.naturalWidth) {
      const far = r.top > innerHeight * 1.5 || r.bottom < -innerHeight * 0.5;
      if (!(img.loading === 'lazy' && far))
        res.images.push(`не загрузилось: ${img.getAttribute('src')}`);
      return;
    }
    const need = r.width * (window.devicePixelRatio || 1);
    if (need / img.naturalWidth > 1.5)
      res.images.push(`${img.getAttribute('src').split('/').pop()}: растягивается в `
        + `${(need/img.naturalWidth).toFixed(1)}x — будет мылко`);
  });

  // ── тексты для замера контраста ──
  document.querySelectorAll('.water-card__title, .water-card__sub, .water-card__btn, '
    + '.tour-section__title, .tour-section__subtitle, .btn-tour, .carousel__card-title').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 10 || r.height < 6) return;
    if (r.bottom < 0 || r.top > document.documentElement.scrollHeight) return;
    const cs = getComputedStyle(el);
    res.texts.push({sel: el.className.split(' ')[0], text: el.textContent.trim().slice(0,22),
                    color: cs.color, x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height,
                    size: parseFloat(cs.fontSize), weight: cs.fontWeight});
  });
  return res;
}"""


def lum(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


async def audit_viewport(browser, w, h, source_css, first):
    ctx = await browser.new_context(viewport={"width": w, "height": h})
    page = await ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(SITE)
    await page.wait_for_timeout(2500)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight); ")
    await page.wait_for_timeout(1200)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(600)

    # Останавливаем таймеры: карусель автолистается и уезжает между замером
    # координат и снимком экрана — иначе контраст меряется не по тем пикселям.
    await page.evaluate("for (let i = 1; i < 99999; i++) clearInterval(i)")
    await page.wait_for_timeout(300)

    if first:
        await audit_cssom(page, source_css)

    r = await page.evaluate(BROWSER_AUDIT)
    for m in r["structure"]:  bug("Структура", f"[{w}px] {m}")
    for m in r["geometry"]:   bug("Геометрия", f"[{w}px] {m}")
    for m in set(r["images"]):bug("Изображения", f"[{w}px] {m}")
    for e in errors:          bug("JS", f"[{w}px] {e[:110]}")

    # контраст: снимаем страницу без текста и меряем фон под каждой надписью
    full = await page.screenshot(full_page=True)
    # Прячем ТОЛЬКО буквы: подложки кнопок и плашки должны остаться,
    # иначе меряем фон под ними, а не реальный фон текста.
    await page.evaluate("""() => document.querySelectorAll(
        '.water-card__title, .water-card__sub, .water-card__btn, .tour-section__title,'
        + '.tour-section__subtitle, .btn-tour, .carousel__card-title')
        .forEach(e => {
          // вложенный текст тоже гасим, иначе он считается «фоном»
          const hide = n => { n.style.color = 'transparent'; n.style.textShadow = 'none'; };
          hide(e);
          e.querySelectorAll('*').forEach(hide);
        })""")
    await page.wait_for_timeout(400)
    shot = "/tmp/_audit_bg.png"
    await page.screenshot(path=shot, full_page=True)
    await ctx.close()

    from PIL import Image
    px = Image.open(shot).convert("RGB")
    W, H = px.size
    px = px.load()
    for t in r["texts"]:
        cr = re.findall(r"[\d.]+", t["color"])
        text_l = 0.2126*lum(float(cr[0])) + 0.7152*lum(float(cr[1])) + 0.0722*lum(float(cr[2]))
        vals = []
        for y in range(int(t["y"]), int(t["y"] + t["h"]), 2):
            for x in range(int(t["x"]), int(t["x"] + t["w"]), 2):
                if 0 <= x < W and 0 <= y < H:
                    rr, gg, bb = px[x, y]
                    vals.append(0.2126*lum(rr) + 0.7152*lum(gg) + 0.0722*lum(bb))
        if len(vals) < 8:
            continue
        vals.sort()
        worst = vals[int(len(vals)*0.95)] if text_l < 0.35 else vals[int(len(vals)*0.05)]
        c = (max(text_l, worst) + 0.05) / (min(text_l, worst) + 0.05)
        big = t["size"] >= 24 or (t["size"] >= 18.66 and int(t["weight"]) >= 600)
        need = 3.0 if big else 4.5
        if c < need:
            bug("Контраст", f"[{w}px] «{t['text']}» ({t['sel']}, {t['size']:.0f}px): "
                            f"{c:.1f} при норме {need}")


async def main():
    # у каждой страницы свой CSS: проверяем его против CSSOM именно этой страницы
    css_by_page = {}
    for page in ("index.html", "tour.html"):
        css_by_page[f"file://{ROOT}/{page}"] = audit_css(open(f"{ROOT}/{page}").read())
    async with async_playwright() as pw:
        b = await pw.webkit.launch()
        # обе страницы: главная и внутренняя
        global SITE
        for page_url in PAGES:
            SITE = page_url
            name = page_url.rsplit("/", 1)[-1]
            print(f"\nПроверяю {name} …")
            for i, (w, h) in enumerate(VIEWPORTS):
                await audit_viewport(b, w, h, css_by_page[page_url], first=(i == 0))
        await b.close()

    if not problems:
        print("Поломок не найдено.")
        if IGNORE:
            print("\nОбъявленные исключения (нужен исходник большего размера):")
            for i in IGNORE:
                print(f"  • {i}")
        return 0
    groups = {}
    for g, m in problems:
        groups.setdefault(g, []).append(m)
    for g in ("CSS", "Структура", "Геометрия", "Контраст", "Изображения", "JS"):
        if g not in groups:
            continue
        print(f"\n{'─'*70}\n{g}  ({len(groups[g])})\n{'─'*70}")
        for m in sorted(set(groups[g])):
            print(f"  • {m}")
    print(f"\nВСЕГО: {len(problems)}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
