# Site — Apple-style

## Проект
Сайт в стиле apple.com. Репозиторий: cocame/site.
Главный файл: index.html

## Дизайн-стандарты (обязательно)
- Шрифт: SF Pro / -apple-system / BlinkMacSystemFont, sans-serif ТОЛЬКО
- Цвета: белый #ffffff, чёрный #1d1d1f, серый #6e6e73, акцент #0071e3
- border-radius: 12px (карточки), 980px (кнопки-пилюли как у Apple)
- Отступы: секции padding 120px 0, контент max-width 980px, центр
- Анимации: плавные, cubic-bezier(0.25, 0.1, 0.25, 1), 0.3-0.6s
- Изображения: всегда на всю ширину секции, без рамок
- Навигация: фиксированная, backdrop-filter blur(20px), полупрозрачная
- НЕТ: теням box-shadow с большим spread, ярким цветам, serif шрифтам

## Мобильная адаптивность
- Breakpoint: 768px
- Навигация сворачивается в бургер
- Текст масштабируется: h1 56px → 32px, h2 48px → 28px

## Агент-ревьюер
После каждого изменения index.html запускать apple-reviewer.
