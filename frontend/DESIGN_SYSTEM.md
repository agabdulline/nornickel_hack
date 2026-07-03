# Дизайн-система «Фабрика гипотез»

Визуальный язык — в стиле **nornickel.ru**: сине-центричная корпоративная палитра,
крупные скруглённые карточки, кнопки-пилюли, мягкая моторика, шрифты Proxima Nova /
Roboto Mono. Всё живёт в CSS-переменных (`src/index.css`) и переключается между
светлой и тёмной темой атрибутом `data-theme` на `<html>`.

## Токены (CSS-переменные)

Использовать только эти токены — никаких «сырых» hex-цветов и палитры Tailwind
(`slate-*`, `teal-*`, `red-*` и т.п.) в экранах.

| Переменная | Смысл | Tailwind-утилита |
|---|---|---|
| `--c-brand` `#0077c8` | основной интерактив, ссылки, активные состояния | `bg-brand` `text-brand` `border-brand` |
| `--c-brand-strong` `#004c97` | заголовки, эмфаза, градиенты | `text-brand-strong` |
| `--c-brand-hover` | ховер кнопок | — |
| `--c-azure` `#0290f0` | подсветка, кольцо фокуса | `text-azure` |
| `--c-ink` | почти-чёрный корпоративный | `text-ink` |
| `--c-bg` | фон страницы | `bg-bg` |
| `--c-surface` | карточки | `bg-surface` |
| `--c-surface-2` | подложки, тихие заливки | `bg-surface-2` |
| `--c-line` / `--c-line-strong` | границы / контрастные границы | `border-line` `border-line-strong` |
| `--c-text` / `--c-muted` / `--c-faint` | текст / вторичный / третичный | `text-text` `text-muted` `text-faint` |
| `--c-brand-tint` | голубой тинт-фон (инфо) | `bg-brand-tint` |
| `--c-danger` `#d70c1e` + `--c-danger-tint` | потери, ошибки, «отклонить» | `text-danger` `bg-danger-tint` |
| `--c-warn` + `--c-warn-tint` | восстановленные данные, предупреждения | `text-warn` `bg-warn-tint` |
| `--c-ok` + `--c-ok-tint` | извлекаемо, «принять», подтверждено | `text-ok` `bg-ok-tint` |

Радиусы: `rounded-md`(12) `rounded-lg`(16, карточки) `rounded-xl`(22) `rounded-full`(пилюли).
Тени: `shadow-soft` `shadow-card` `shadow-pop`. Моторика: `--ease-brand` = `cubic-bezier(.23,1,.32,1)`, длительности 0.18–0.3s.
Шрифты: sans по умолчанию; `.num` — Roboto Mono с табличными цифрами (все числа: тонны, %, $, даты, id).

## CSS-классы (в `index.css`)

- **Карточки**: `.card` (поверхность+рамка+радиус16+тень), `.card-2` (тихая подложка), `.hover-lift` (подъём+тень на ховер).
- **Кнопки** (пилюли): `.btn` + модификатор `.btn-primary` `.btn-outline` `.btn-ghost` `.btn-danger` `.btn-ok`; размеры `.btn-sm` `.btn-lg`.
- **Бейджи**: `.badge` + `.badge-brand|-ok|-warn|-danger|-solid|-outline`.
- **Чипы** (фильтры/тумблеры): `.chip` / `.chip-active`.
- **Поля**: `.input` `.select` `.textarea`, подпись `.field-label`.
- **Сегмент-контрол**: `.seg` > `.seg-btn` / `.seg-btn-active`.
- **Таблицы**: `.tbl` (шапка uppercase-muted, ховер строк).
- **Прочее**: `.recovered-cell` (янтарный пунктир для #REF!), `.meter`>`i` (скоринг-бар), `.link`, `.skeleton`, `.animate-in`, `.animate-fade`, `.stagger`.

## React-компоненты (`src/components/common.tsx`)

- `<Icon name className strokeWidth />` — линейные SVG-иконки (currentColor). Имена: `sun moon chat upload download check x arrowRight spark flask book lock alert refresh doc search plus map factory chart target`. **Предпочитать иконки эмодзи** в шапке, кнопках, статусах.
- `<Logo compact? />` — брендовый знак (гексагон-градиент) + логотип.
- `<ThemeToggle />` — переключатель светлой/тёмной темы (в шапке).
- `<Badge tone children />` — tone: `default|brand|ok|warn|danger|solid|outline`.
- `<Chip active onClick children />` — кликабельный фильтр-чип.
- `<StatCard label value sub? tone? icon? />` — KPI-карточка; tone: `default|loss|ok|brand`.
- `<Segmented options value onChange />` — сегмент-переключатель (напр. Ni/Cu).
- `<Stepper pid steps />` — навигация по шагам проекта (в шапке).
- `<Panel title subtitle? actions? bodyClass? children />` — карточка с шапкой (заголовок + действия справа).
- `<SectionLabel>` — мелкая uppercase-подпись секции.
- `<Meter value title? />` — прогресс/скоринг-бар (0..1).
- `<Modal title onClose wide? children />` — модалка; `<ChunkModal chunkId quote? onClose />` — модалка цитаты.
- Состояния: `<Spinner label? />`, `<ErrorBox error />`, `<EmptyBox text hint? icon? />`, `<CapexBadge capex />`.

## Принципы

1. **Тема-независимость**: цвета только через токены/утилиты/классы — экран должен выглядеть корректно и в светлой, и в тёмной теме. Не хардкодить белый/чёрный/палитру Tailwind.
2. **Иерархия**: заголовок экрана — `text-xl font-extrabold`; подписи секций — `SectionLabel`; вторичный текст — `text-muted`.
3. **Плотность данных**: это B2B-инструмент технолога — таблицы и числа читаемы (`.num`), но обрамление воздушное (радиусы, отступы, `.card`).
4. **Моторика сдержанная**: `.hover-lift` на кликабельных карточках, `.animate-in`/`.stagger` для появления списков, плавные переходы — без «прыжков».
5. **Функциональность неприкосновенна**: при редизайне сохранять всю логику (запросы `api.*`, состояние, роутинг, пропсы, обработчики) — меняется только представление.
