# План: отрисовка crop-селектора по спеке `pix-crop-selector`

| | |
|---|---|
| Ветка | `new_crop_tool` (текущая), HEAD `11e8e19` |
| Основной файл | `src/barbaros/widgets/image_crop/crop_selection.py`, класс `GimpStyleCropSelection` |
| Новый тест | `tests/test_crop_selection.py` |
| Спека | [`docs/specs/pix-crop-selector/README.md`](README.md), [`constants.yaml`](constants.yaml) |
| Оригинал Pix 3.4.10 | `pix/gth-image-selector.c`, `pix/cairo-utils.c`, `extensions/file_tools/gth-file-tool-crop.c` |
| Объём | только отрисовка рамки и необходимый для неё hit-test/hover; поведение драга/ресайза не переписывается |

---

## 1. Цель и результат

Заменить «GIMP-style» отрисовку виджета `GimpStyleCropSelection` на рамку из Pix:

1. у выделения **нет видимых ручек** (сейчас рисуются 8 оранжевых квадратов);
2. снаружи выделения изображение затемнено **чёрным alpha 0.5**, внутри — исходная яркость;
   затемнение покрывает **только область изображения**;
3. **во время драга** (кнопка мыши зажата) затемнение отсутствует, рамка остаётся;
4. рамка — **1 device px**, цвет = инверсия подложки (`CompositionMode_Difference` с белым);
5. при наведении на ручку рисуется **1-px «скобка»** (Difference) по внутренней границе
   невидимой зоны ручки: угол — 2 линии, сторона — 3 линии;
6. пустое выделение (`w <= 0` или `h <= 0`) — оверлей не рисуется вообще;
7. зоны ручек — по спеке: `b = 40`, при стороне `< 120` → `b = сторона / 3`, минимум 3 px;
   зоны считаются в **координатах selector'а** (пиксели виджета), а не изображения;
8. курсоры: crosshair вне выделения, move внутри, directional-resize на 8 зонах.

Главный визуальный ориентир — скриншоты `hover-corner.png` и `drag-mask-off.png` в этой папке.

---

## 2. Что есть сейчас и что должно стать

| Элемент | Сейчас (`crop_selection.py`) | Должно быть |
|---|---|---|
| Затемнение | 4 прямоугольника, `QColor(0,0,0,100)` (≈0.39), всегда | чёрный `alpha=128` (0.5), только по `display_rect`; при `is_selecting` не рисуется |
| Внутри выделения | просто не закрашивается | яркость восстанавливается перерисовкой `pixmap` с клипом по выделению |
| Рамка | `QPen(white, 2)`, antialiasing, рисуется по `_widget_rect_from_image` | 1 device px, Difference, `+0.5` выравнивание, без «толстой» линии |
| Ручки | 8 оранжевых квадратов 16×16 (`handle_size=8`, `handle_map`) | не рисуются; вместо них hover-«скобка» |
| Hover | нет состояния; курсор считается от 16×16 боксов | `hovered_handle`, зоны 40 px по спеке, скобка при наведении |
| Hit-test | `handle_map` в координатах **изображения**, боксы 16 px | зоны в координатах **виджета/selector'а**, приоритет: углы → стороны → interior |
| Пустое выделение | `isNull()` — только `w==0 and h==0` | `w <= 0 or h <= 0` |
| Пересчёт в экран | `_widget_rect_from_image` через `int()` и `QRect(tl, br)` — даёт +1 px и зависимость от `QRect.bottomRight()` | независимое округление `x, y, w, h` через `floor(v + 0.5)` (как `IROUND` в Pix) |

---

## 3. Границы задачи

### Входит

- `paintEvent` класса `GimpStyleCropSelection`;
- чистая геометрия зон/hover-скобки + её тесты;
- `get_handle_at`, `_update_cursor`, `mouseMoveEvent`/`mouseReleaseEvent`/`leaveEvent`
  в части hover-состояния (это необходимо для отрисовки скобки);
- удаление мёртвого кода старых ручек (`handle_size`, `handle_map`, `_widget_rect_from_image`);
- новый файл тестов.

### Не входит (не делать в этой задаче)

- начальное выделение `2/3` по центру (спека §3): сейчас `ImageManagerWidget.set_image`
  задаёт полный прямоугольник, а `CropDialog` — fallback `QRect(0,0,W,H)`. Это отдельная
  UX-задача; менять `image_manager.py` здесь **не нужно**;
- переворот ручки через противоположную сторону, autoscroll, drag-threshold, клампы,
  `MinSizePolicy`, создание `1×1` по клику — поведение остаётся текущим;
- сетка, панель параметров, пропорции, `Accept/Cancel` — вне спеки;
- `CropPreviewWidget` (`preview.py`) — у него своя, упрощённая отрисовка; трогать не нужно;
- зум/скролл (`QScrollArea`, `set_zoom`, `wheelEvent`) — не меняются;
- переименование класса `GimpStyleCropSelection` — не делать: завязан контекст переводов
  `GimpStyleCropSelection` в `src/barbaros/i18n/barbaros_ru.ts` и импорты. Достаточно
  поправить docstring.

> Если после реализации понадобится «как в Pix» начальное выделение — это отдельный
> маленький PR: `image_manager.set_image` задаёт `QRect(W*2//3, H*2//3)` по центру
> (`x=(W-w)//2`, `y=(H-h)//2`). Здесь не реализуем, чтобы не смешивать изменения.

---

## 4. Источник истины: формулы из оригинального C-кода

Ниже — выжимка из `linuxmint/pix@3.4.10`, на неё опираются все числа. Локальной модели
не нужно ходить в интернет: всё необходимое есть в этом разделе.

### 4.1 Зоны ручек (`update_event_areas`)

```c
#define DEFAULT_BORDER 40
#define MIN_BORDER 3

border = DEFAULT_BORDER;
if (selection_area.width  < DEFAULT_BORDER * 3) border = selection_area.width  / 3;
if (selection_area.height < DEFAULT_BORDER * 3) border = selection_area.height / 3;
if (border < MIN_BORDER) border = MIN_BORDER;
border2 = border * 2;

x = selection_area.x - 1;
y = selection_area.y - 1;
width  = selection_area.width  + 1;
height = selection_area.height + 1;
```

Дальше:

| Зона | x | y | width | height |
|---|---|---|---|---|
| interior | `x` | `y` | `width` | `height` |
| top | `x + border` | `y` | `width - border2` | `border` |
| bottom | `x + border` | `y + height - border` | `width - border2` | `border` |
| left | `x` | `y + border` | `border` | `height - border2` |
| right | `x + width - border` | `y + border` | `border` | `height - border2` |
| top-left | `x` | `y` | `border` | `border` |
| top-right | `x + width - border` | `y` | `border` | `border` |
| bottom-left | `x` | `y + height - border` | `border` | `border` |
| bottom-right | `x + width - border` | `y + height - border` | `border` | `border` |

Проверка попадания в оригинале **включает правую/нижнюю границу**:

```c
static gboolean point_in_rectangle (int x, int y, cairo_rectangle_int_t rect) {
    return ((x >= rect.x) && (x <= rect.x + rect.width)
         && (y >= rect.y) && (y <= rect.y + rect.height));
}
```

Порядок проверки (priority) — как в `constants.yaml`: `bottom_right, bottom_left,
top_right, top_left, right, left, bottom, top, interior`.

### 4.2 Рамка (`_cairo_paint_grid`, при `GTH_GRID_NONE`)

```c
ux = uy = 1.0;                       /* 1 device px в user space */
cairo_device_to_user_distance (cr, &ux, &uy);
cairo_set_line_width (cr, MAX (ux, uy));
cairo_set_operator (cr, CAIRO_OPERATOR_DIFFERENCE);
cairo_set_source_rgb (cr, 1.0, 1.0, 1.0);
cairo_rectangle (cr, rectangle->x + 0.5, rectangle->y + 0.5,
                     rectangle->width - 0.5, rectangle->height - 0.5);
cairo_stroke (cr);
```

Смысл: белая линия толщиной 1 device px в режиме Difference; на непрозрачном фоне
`out = 255 - in` по каждому каналу.

### 4.3 Hover-скобка (`event_area_paint`)

Для текущей зоны рисуется не весь прямоугольник, а только его внутренние стороны:

```c
_cairo_rectangle_partial (cr,
    image_area.x + event_area->area.x - visible_area.x + 0.5,
    image_area.y + event_area->area.y - visible_area.y + 0.5,
    event_area->area.width  - 1.0,
    event_area->area.height - 1.0,
    sides);
```

Где `sides`:

| Зона | Стороны |
|---|---|
| top | right, bottom, left |
| bottom | top, right, left |
| left | top, right, bottom |
| right | top, bottom, left |
| top-left | right, bottom |
| top-right | bottom, left |
| bottom-left | top, right |
| bottom-right | top, left |

То есть для угла — 2 линии, для стороны — 3 линии, всегда по **внутренней** границе зоны.

### 4.4 Порядок отрисовки (`gth_image_selector_draw` + `paint_selection`)

```text
draw_image_full()
if mask_visible:
    if dragging: draw_image_full()          # без затемнения
    else:        overlay_black(0.5)         # по image_area
                 draw_image_clipped(sel)    # вернуть яркость внутри
    draw_selection_overlay()                # рамка Difference + скобка hover
```

Маска: `cairo_set_source_rgba (cr, 0.0, 0.0, 0.0, 0.5)`.
Размер маски — `image_area` (у нас виджет всегда равен области изображения, см. `_update_layout`).

### 4.5 Маппинг на Qt/PySide6 (из спеки §9.2)

- `QPainter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)`;
- `QPen` цветом white, толщина `1/devicePixelRatioF()` logical px (1 device px);
- линии/прямоугольники — на координатах `+0.5`, чтобы линии были ровно 1 px;
- antialiasing включён (для скобки на концах линий это даёт половинное покрытие, как в
  Cairo); рамка при `+0.5` всё равно получается чёткой.

---

## 5. Решения по неоднозначностям (приняты заранее, не менять по ходу)

1. **Рамка: `w - 1`, `h - 1`, а не `w - 0.5`, `h - 0.5` из Cairo.**
   Cairo-формула `+0.5 / w-0.5` кладёт правую и нижнюю линии на границу пикселей и при
   antialiasing размазывает их на 2 полупрозрачных пикселя. Спека требует «1 device px,
   выровнена по пикселям», поэтому в Qt рисуем прямоугольник
   `QRectF(x + 0.5, y + 0.5, w - 1, h - 1)` — ровно по 1 px внутри выделения со всех
   сторон. Отличие от Cairo ±1 px спека допускает (§8.3).
2. **Клип для рамки/скобки:** `QRect(disp.x(), disp.y(), disp.width() + 1, disp.height() + 1)`
   (целочисленный, а не `QRectF` с `+0.5`). Причина: `QPainter` клипует по пикселям, и
   `QRectF(x + 0.5, ...)` в Qt отрежет левую/верхнюю линии рамки (проверено экспериментом).
   Cairo-клип `x+0.5` включает пиксель `x`, поэтому в Qt берём `x` без `+0.5`.
3. **Пустое выделение:** скрывать оверлей при `w <= 0 or h <= 0`. В спеке
   `mask_visible = sel.w > 0 && sel.h > 0`; в оригинальном crop-tool стоит `OR`, но
   спека — контракт, выполняем её.
4. **Размер зон:** строго формула Pix, включая «высота перекрывает ширину»:
   `border = 40`, затем `if w < 120: border = w // 3`, затем `if h < 120: border = h // 3`,
   затем `max(border, 3)`. Не заменять на «разумный clamp» из §8.1 — это изменило бы
   поведение, которое мы документируем.
5. **Округление selector-координат:** `floor(v + 0.5)` (как `IROUND` в Pix), а не
   `int(v)` и не `round(v)`. Каждая компонента (`x`, `y`, `w`, `h`) округляется независимо.
6. **Hover-скобка при драге:** если кнопка нажата, подсвечивается `active_handle`
   (так в Pix `current_area` остаётся активной); если нет — `hovered_handle`.
   Для `INSIDE`/`NONE` скобка не рисуется.
7. **Клип рамки/скобки от переполнения:** `disp` может на 1 px выйти за `display_rect`
   из-за независимого округления; при восстановлении яркости клип пересекаем с
   `display_rect`.

---

## 6. Пошаговая реализация

Все правки — в одном файле
`src/barbaros/widgets/image_crop/crop_selection.py` (класс `GimpStyleCropSelection`).
Класс `CropDialog` ниже по файлу **не меняется**.

### Шаг 1. Импорты, константы и чистые helper-функции

Добавить в начало файла (после существующих импортов, до класса):

```python
from math import floor

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
```

> `QBrush` больше не нужен — удалить из импорта. `QPen` остаётся.

Модульные константы и функции (до `class GimpStyleCropSelection`):

```python
# Геометрия рамки выделения — docs/specs/pix-crop-selector/constants.yaml.
DEFAULT_HIT_BORDER = 40
MIN_HIT_BORDER = 3
HIT_BORDER_THRESHOLD = DEFAULT_HIT_BORDER * 3  # 120
MASK_ALPHA = 128  # 0.5 * 255

SIDE_TOP = 1
SIDE_RIGHT = 2
SIDE_BOTTOM = 4
SIDE_LEFT = 8

# Какие внутренние стороны зоны подсвечиваются (event_area_paint в Pix).
BRACKET_SIDES = {
    HandlePos.TOP_CENTER: SIDE_RIGHT | SIDE_BOTTOM | SIDE_LEFT,
    HandlePos.BOTTOM_CENTER: SIDE_TOP | SIDE_RIGHT | SIDE_LEFT,
    HandlePos.LEFT_CENTER: SIDE_TOP | SIDE_RIGHT | SIDE_BOTTOM,
    HandlePos.RIGHT_CENTER: SIDE_TOP | SIDE_BOTTOM | SIDE_LEFT,
    HandlePos.TOP_LEFT: SIDE_RIGHT | SIDE_BOTTOM,
    HandlePos.TOP_RIGHT: SIDE_BOTTOM | SIDE_LEFT,
    HandlePos.BOTTOM_LEFT: SIDE_TOP | SIDE_RIGHT,
    HandlePos.BOTTOM_RIGHT: SIDE_TOP | SIDE_LEFT,
}

CURSOR_BY_HANDLE = {
    HandlePos.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    HandlePos.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    HandlePos.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    HandlePos.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
    HandlePos.TOP_CENTER: Qt.CursorShape.SizeVerCursor,
    HandlePos.BOTTOM_CENTER: Qt.CursorShape.SizeVerCursor,
    HandlePos.LEFT_CENTER: Qt.CursorShape.SizeHorCursor,
    HandlePos.RIGHT_CENTER: Qt.CursorShape.SizeHorCursor,
    HandlePos.INSIDE: Qt.CursorShape.SizeAllCursor,
}


def round_half_up(value: float) -> int:
    """IROUND из Pix: floor(x + 0.5)."""
    return floor(value + 0.5)


def point_in_zone(x: float, y: float, zone: tuple[int, int, int, int]) -> bool:
    """point_in_rectangle из Pix: правая/нижняя граница включительно."""
    zx, zy, zw, zh = zone
    return zx <= x <= zx + zw and zy <= y <= zy + zh


def hit_border(selection_w: int, selection_h: int) -> int:
    """Размер невидимой зоны ручки в selector-пикселях."""
    border = DEFAULT_HIT_BORDER
    if selection_w < HIT_BORDER_THRESHOLD:
        border = selection_w // 3
    if selection_h < HIT_BORDER_THRESHOLD:  # в Pix второе условие перекрывает первое
        border = selection_h // 3
    return max(border, MIN_HIT_BORDER)


def handle_zones(sx: int, sy: int, sw: int, sh: int):
    """Зоны хит-теста в порядке приоритета (как get_event_area_from_position в Pix)."""
    border = hit_border(sw, sh)
    x, y = sx - 1, sy - 1
    width, height = sw + 1, sh + 1
    b = border
    return [
        (HandlePos.BOTTOM_RIGHT, (x + width - b, y + height - b, b, b)),
        (HandlePos.BOTTOM_LEFT, (x, y + height - b, b, b)),
        (HandlePos.TOP_RIGHT, (x + width - b, y, b, b)),
        (HandlePos.TOP_LEFT, (x, y, b, b)),
        (HandlePos.RIGHT_CENTER, (x + width - b, y + b, b, max(height - 2 * b, 0))),
        (HandlePos.LEFT_CENTER, (x, y + b, b, max(height - 2 * b, 0))),
        (HandlePos.BOTTOM_CENTER, (x + b, y + height - b, max(width - 2 * b, 0), b)),
        (HandlePos.TOP_CENTER, (x + b, y, max(width - 2 * b, 0), b)),
        (HandlePos.INSIDE, (x, y, width, height)),
    ]


def bracket_segments(zone, handle: HandlePos) -> list[tuple[QPointF, QPointF]]:
    """Отрезки hover-скобки по внутренней границе зоны."""
    sides = BRACKET_SIDES.get(handle)
    if sides is None:
        return []
    zx, zy, zw, zh = zone
    x, y = zx + 0.5, zy + 0.5
    w, h = zw - 1.0, zh - 1.0
    segments = []
    if sides & SIDE_TOP:
        segments.append((QPointF(x, y), QPointF(x + w, y)))
    if sides & SIDE_RIGHT:
        segments.append((QPointF(x + w, y), QPointF(x + w, y + h)))
    if sides & SIDE_BOTTOM:
        segments.append((QPointF(x, y + h), QPointF(x + w, y + h)))
    if sides & SIDE_LEFT:
        segments.append((QPointF(x, y), QPointF(x, y + h)))
    return segments
```

> `max(..., 0)` для сторон — защита от отрицательных размеров при выделении меньше
> `2*border`; для таких выделений всё равно выигрывают углы из-за приоритета.

### Шаг 2. Состояние класса `__init__`

- удалить `self.handle_size = 8`;
- удалить весь словарь `self.handle_map = {...}`;
- рядом с `self.active_handle` добавить:

```python
self.hovered_handle: HandlePos = HandlePos.NONE
```

Всё остальное (`strategies`, `policies`, зум-поля) не трогать.
`self.strategies` по-прежнему содержит `HandlePos.NONE: CreateStrategy()` — создание
выделения не меняем.

### Шаг 3. Пересчёт в экранные координаты и hit-test

Заменить `_widget_rect_from_image` (и удалить ставший ненужным `_to_widget_point`) на:

```python
def _selection_screen_rect(self) -> QRect:
    """sel в пикселях изображения -> прямоугольник в координатах виджета."""
    rect = self.selection_rect
    scale = self.scale_factor
    return QRect(
        round_half_up(rect.x() * scale),
        round_half_up(rect.y() * scale),
        round_half_up(rect.width() * scale),
        round_half_up(rect.height() * scale),
    )


def _selection_is_empty(self) -> bool:
    rect = self.selection_rect
    return rect is None or rect.width() <= 0 or rect.height() <= 0


def _handle_zones(self):
    if self._selection_is_empty():
        return []
    disp = self._selection_screen_rect()
    return handle_zones(disp.x(), disp.y(), disp.width(), disp.height())
```

`_to_image_point` оставить как есть (используется стратегиями в mouse-событиях).

Заменить `get_handle_at` на:

```python
def get_handle_at(self, pos: QPoint) -> HandlePos:
    """Возвращает зону под точкой виджета (или HandlePos.NONE)."""
    for handle, zone in self._handle_zones():
        if point_in_zone(pos.x(), pos.y(), zone):
            return handle
    return HandlePos.NONE
```

### Шаг 4. Курсор и hover-состояние

Заменить тело `_update_cursor`:

```python
def _update_cursor(self, pos: QPoint):
    handle = self.get_handle_at(pos)
    self.setCursor(CURSOR_BY_HANDLE.get(handle, Qt.CursorShape.CrossCursor))
```

Изменить `mouseMoveEvent` — в ветке «кнопка не нажата» обновлять hover:

```python
def mouseMoveEvent(self, event):
    pos = event.position().toPoint()

    if not self.is_selecting:
        handle = self.get_handle_at(pos)
        if handle != self.hovered_handle:
            self.hovered_handle = handle
            self.update()
        self._update_cursor(pos)
        return

    # ... существующий код ресайза/перемещения без изменений ...
```

Изменить `mouseReleaseEvent`:

```python
def mouseReleaseEvent(self, event):
    self.is_selecting = False
    self.active_handle = HandlePos.NONE
    pos = event.position().toPoint()
    self.hovered_handle = self.get_handle_at(pos)
    self._update_cursor(pos)
    self.update()
```

Добавить после `mouseReleaseEvent`:

```python
def leaveEvent(self, event):
    self.hovered_handle = HandlePos.NONE
    self.update()
    super().leaveEvent(event)
```

В `mousePressEvent` (в самом начале, после проверки `image.isNull()`):

```python
if event.button() != Qt.MouseButton.LeftButton:
    return
```

Это соответствует Pix (`if (event->button != 1) return FALSE;`) и не даёт правому
клику включать режим драга.

После правок прогнать автоформатирование импортов/пробелов только по изменённым файлам:

```bash
uv run ruff check --fix src/barbaros/widgets/image_crop/crop_selection.py
```

> В репозитории есть доruff-ошибки в других файлах; их не трогаем. Наша цель — чистые
> `crop_selection.py` и новый тест.

Сбросить hover при смене геометрии (иначе скобка может «зависнуть» в старом месте):

- в `set_crop_rect`: после `self.selection_rect = rect` → `self.hovered_handle = HandlePos.NONE`;
- в `update_fit_scale`: после `self._update_layout()` → `self.hovered_handle = HandlePos.NONE`;
- в `set_zoom`: после `self._update_layout()` → `self.hovered_handle = HandlePos.NONE`.

Во всех трёх случаях `self.update()` уже вызывается (`set_crop_rect`, `set_zoom`) либо
будет вызван следующим кадром; можно добавить `self.update()` в `update_fit_scale`,
если нужен немедленный перерсис.

### Шаг 5. `paintEvent` — полная замена

Существующий `paintEvent` (от `painter = QPainter(self)` до конца метода) заменить на:

```python
def paintEvent(self, event):
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if self.image.isNull():
        painter.fillRect(self.rect(), Qt.GlobalColor.lightGray)
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        painter.drawText(
            self.rect(), Qt.AlignmentFlag.AlignCenter, self.tr("No image loaded")
        )
        return

    painter.drawPixmap(self.display_rect, self.pixmap)

    if self._selection_is_empty():
        return

    disp = self._selection_screen_rect()
    image_rect = self.display_rect

    # 1. Затемнение снаружи выделения; во время драга его нет.
    if not self.is_selecting:
        painter.fillRect(image_rect, QColor(0, 0, 0, MASK_ALPHA))
        painter.save()
        painter.setClipRect(disp.intersected(image_rect))
        painter.drawPixmap(image_rect, self.pixmap)
        painter.restore()

    # 2. Рамка и hover-скобка — Difference, 1 device px.
    highlight = self.active_handle if self.is_selecting else self.hovered_handle
    zones = dict(self._handle_zones())

    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
    painter.setClipRect(QRect(disp.x(), disp.y(), disp.width() + 1, disp.height() + 1))
    pen = QPen(QColor(255, 255, 255))
    pen.setWidthF(1.0 / self.devicePixelRatioF())
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(
        QRectF(
            disp.x() + 0.5,
            disp.y() + 0.5,
            max(disp.width() - 1, 0),
            max(disp.height() - 1, 0),
        )
    )

    if highlight in BRACKET_SIDES and highlight in zones:
        path = QPainterPath()
        for start, end in bracket_segments(zones[highlight], highlight):
            path.moveTo(start)
            path.lineTo(end)
        painter.drawPath(path)

    painter.restore()
```

Почему так:

- `drawPixmap` + `fillRect(0.5)` + клип + повторный `drawPixmap` — точный аналог
  `paint_background` + `paint_selection` (без 4 прямоугольников и без щелей);
- `QPainterPath` со всеми отрезками скобки рисуется **одним** вызовом `drawPath`:
  если рисовать отрезки по одному `drawLine`, общий угловой пиксель инвертируется
  дважды и вернётся к исходному цвету;
- `highlight` при драге = `active_handle`, поэтому скобка не мигает при перемещении
  ручки; для `INSIDE`/`NONE` её нет;
- клип `QRect(..., +1, +1)` нужен, чтобы левая/верхняя линии рамки не были срезаны
  (см. §5.2).

### Шаг 6. Удалить мёртвый код и поправить docstring

- удалить `handle_map`, `handle_size`, `_widget_rect_from_image`, `_to_widget_point`
  (проверить `grep -n "handle_map\|handle_size\|_widget_rect_from_image\|_to_widget_point"`);
- обновить docstring класса:

```python
"""Виджет обрезки: рамка выделения в стиле Pix.

Принимает QImage, вписывает его в виджет и поддерживает зум.
Отрисовка (затемнение 0.5, рамка 1 device px в режиме Difference, hover-скобка)
повторяет docs/specs/pix-crop-selector. Координаты выделения хранятся в пикселях
изображения, в координаты виджета пересчитываются при отрисовке и hit-test.
"""
```

### Шаг 7. Переводы (опционально, в конце)

Строки не меняются, но сдвигаются `line=` в `.ts`. Если проект требует актуальных
локаций:

```bash
uv run invoke update_translations
uv run invoke compile_translations
```

Это отдельный, механический diff; если не хочется шума — не делать, на работу не влияет.

---

## 7. Тесты

Новый файл `tests/test_crop_selection.py`. Тесты не зависят от скриншотов и проверяют
семантику отрисовки по пикселям (валидировано на прототипе).

```python
"""Тесты отрисовки crop-рамки по спеке docs/specs/pix-crop-selector."""

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage

from barbaros.widgets.image_crop.crop_selection import (
    BRACKET_SIDES,
    MASK_ALPHA,
    GimpStyleCropSelection,
    bracket_segments,
    handle_zones,
    hit_border,
    point_in_zone,
    round_half_up,
)
from barbaros.widgets.image_crop.transform_strategy import HandlePos

IMAGE_COLOR_RGB = (70, 120, 160)
IMAGE_COLOR = QColor(*IMAGE_COLOR_RGB)
MASKED = tuple(
    int(channel * (255 - MASK_ALPHA) / 255 + 0.5) for channel in IMAGE_COLOR_RGB
)  # (35, 60, 80): цвет под чёрным alpha=128
DIFFERENCE = tuple(255 - channel for channel in IMAGE_COLOR_RGB)  # (185, 135, 95)


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def make_widget(selection=QRect(20, 20, 60, 60), image_size=(100, 100), view=(100, 100)):
    image = QImage(image_size[0], image_size[1], QImage.Format.Format_RGB32)
    image.fill(IMAGE_COLOR)
    widget = GimpStyleCropSelection(image)
    widget.update_fit_scale(view[0], view[1])
    widget.set_crop_rect(selection)
    return widget


def render(widget) -> QImage:
    image = QImage(widget.size(), QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.black)
    widget.render(image)
    return image


def pixel(image: QImage, x: int, y: int) -> tuple[int, int, int]:
    color = image.pixelColor(x, y)
    return (color.red(), color.green(), color.blue())


# ---------- чистая геометрия ----------


def test_round_half_up_like_pix_iround():
    assert round_half_up(10.5) == 11
    assert round_half_up(10.4) == 10
    assert round_half_up(0.5) == 1


def test_hit_border_rule():
    assert hit_border(400, 400) == 40
    assert hit_border(90, 400) == 30   # ширина < 120
    assert hit_border(400, 90) == 30   # высота < 120
    assert hit_border(90, 60) == 20    # высота перекрывает ширину
    assert hit_border(6, 6) == 3       # минимум


def test_handle_zones_geometry():
    zones = dict(handle_zones(20, 20, 60, 60))  # b=20
    assert zones[HandlePos.TOP_LEFT] == (19, 19, 20, 20)
    assert zones[HandlePos.BOTTOM_RIGHT] == (60, 60, 20, 20)
    assert zones[HandlePos.TOP_CENTER] == (39, 19, 21, 20)
    assert zones[HandlePos.LEFT_CENTER] == (19, 39, 20, 21)
    assert zones[HandlePos.INSIDE] == (19, 19, 61, 61)


def test_point_in_zone_includes_right_and_bottom():
    zone = (20, 20, 30, 30)
    assert point_in_zone(20, 20, zone)
    assert point_in_zone(50, 50, zone)   # правая/нижняя граница включена
    assert not point_in_zone(51, 50, zone)
    assert not point_in_zone(19, 20, zone)


def test_bracket_sides_table():
    assert len(BRACKET_SIDES) == 8
    assert HandlePos.NONE not in BRACKET_SIDES
    assert HandlePos.INSIDE not in BRACKET_SIDES


def test_corner_bracket_has_two_lines():
    zone = dict(handle_zones(20, 20, 60, 60))[HandlePos.TOP_LEFT]
    segments = bracket_segments(zone, HandlePos.TOP_LEFT)
    assert len(segments) == 2
    points = [((a.x(), a.y()), (b.x(), b.y())) for a, b in segments]
    assert points == [
        ((38.5, 19.5), (38.5, 38.5)),
        ((19.5, 38.5), (38.5, 38.5)),
    ]


def test_side_bracket_has_three_lines():
    zone = dict(handle_zones(20, 20, 60, 60))[HandlePos.TOP_CENTER]
    segments = bracket_segments(zone, HandlePos.TOP_CENTER)
    assert len(segments) == 3
    assert {a.x() for a, _ in segments} == {39.5, 59.5}
    assert any(a.y() == b.y() == 38.5 for a, b in segments)


# ---------- hit-test через виджет ----------


def test_hit_test_priority():
    widget = make_widget()
    assert widget.get_handle_at(QPoint(19, 19)) == HandlePos.TOP_LEFT
    assert widget.get_handle_at(QPoint(39, 39)) == HandlePos.TOP_LEFT  # угол важнее стороны
    assert widget.get_handle_at(QPoint(40, 40)) == HandlePos.INSIDE
    assert widget.get_handle_at(QPoint(50, 25)) == HandlePos.TOP_CENTER
    assert widget.get_handle_at(QPoint(25, 50)) == HandlePos.LEFT_CENTER
    assert widget.get_handle_at(QPoint(50, 50)) == HandlePos.INSIDE
    assert widget.get_handle_at(QPoint(5, 50)) == HandlePos.NONE
    assert widget.get_handle_at(QPoint(61, 61)) == HandlePos.BOTTOM_RIGHT
    assert widget.get_handle_at(QPoint(80, 80)) == HandlePos.BOTTOM_RIGHT


def test_hit_test_empty_selection():
    widget = make_widget(selection=QRect(20, 20, 0, 0))
    assert widget.get_handle_at(QPoint(20, 20)) == HandlePos.NONE


def test_selection_screen_rect_independent_rounding():
    widget = make_widget(selection=QRect(11, 11, 21, 21), image_size=(200, 200), view=(100, 100))
    # scale == 0.5: 11*0.5=5.5 -> 6, 21*0.5=10.5 -> 11 (floor(x+0.5), не int/round)
    disp = widget._selection_screen_rect()
    assert (disp.x(), disp.y(), disp.width(), disp.height()) == (6, 6, 11, 11)


# ---------- отрисовка ----------


def test_plain_render_mask_border_no_handles():
    widget = make_widget()
    image = render(widget)
    assert pixel(image, 50, 50) == (70, 120, 160), "внутри выделения яркость исходная"
    assert pixel(image, 5, 50) == MASKED, "снаружи выделения затемнение 0.5"
    assert pixel(image, 50, 5) == MASKED
    assert pixel(image, 20, 50) == DIFFERENCE, "левая рамка = инверсия"
    assert pixel(image, 50, 20) == DIFFERENCE, "верхняя рамка = инверсия"
    assert pixel(image, 79, 50) == DIFFERENCE, "правая рамка = инверсия"
    assert pixel(image, 50, 79) == DIFFERENCE, "нижняя рамка = инверсия"

    # старые оранжевые ручки не должны рисоваться
    for x in range(image.width()):
        for y in range(image.height()):
            assert pixel(image, x, y) != (255, 165, 0)


def test_mask_hidden_while_dragging():
    widget = make_widget()
    widget.is_selecting = True
    image = render(widget)
    assert pixel(image, 5, 50) == (70, 120, 160), "при драге затемнения нет"
    assert pixel(image, 20, 50) == DIFFERENCE, "рамка остаётся"


def test_empty_selection_hides_overlay():
    for selection in (QRect(20, 20, 0, 0), QRect(20, 20, 60, 0), QRect(20, 20, 0, 60)):
        image = render(make_widget(selection=selection))
        assert pixel(image, 5, 50) == (70, 120, 160)
        assert pixel(image, 50, 50) == (70, 120, 160)


def test_hover_corner_bracket():
    widget = make_widget()
    widget.hovered_handle = HandlePos.TOP_LEFT
    image = render(widget)
    assert pixel(image, 38, 30) == DIFFERENCE, "вертикаль скобки"
    assert pixel(image, 30, 38) == DIFFERENCE, "горизонталь скобки"
    assert pixel(image, 30, 30) == (70, 120, 160)


def test_hover_side_bracket():
    widget = make_widget()
    widget.hovered_handle = HandlePos.TOP_CENTER
    image = render(widget)
    assert pixel(image, 39, 25) == DIFFERENCE, "левая вертикаль"
    assert pixel(image, 59, 25) == DIFFERENCE, "правая вертикаль"
    assert pixel(image, 50, 38) == DIFFERENCE, "нижняя горизонталь"


def test_hover_interior_has_no_bracket():
    widget = make_widget()
    widget.hovered_handle = HandlePos.INSIDE
    image = render(widget)
    assert pixel(image, 38, 30) == (70, 120, 160)
    assert pixel(image, 30, 38) == (70, 120, 160)


def test_cursor_changes_with_zone():
    widget = make_widget()
    widget._update_cursor(QPoint(5, 50))
    assert widget.cursor().shape() == Qt.CursorShape.CrossCursor
    widget._update_cursor(QPoint(50, 50))
    assert widget.cursor().shape() == Qt.CursorShape.SizeAllCursor
    widget._update_cursor(QPoint(20, 20))  # верхний левый угол
    assert widget.cursor().shape() == Qt.CursorShape.SizeFDiagCursor
```

> Значения `(19,19,20,20)` и `(185,135,95)` рассчитаны для image 100×100, view 100×100,
> `selection=QRect(20,20,60,60)` (scale 1.0). При изменении входных данных тестов
> пересчитать по формулам §4.

Запуск:

```bash
# точечно
uv run pytest tests/test_crop_selection.py -q

# без дисплея (CI/headless)
QT_QPA_PLATFORM=offscreen uv run pytest tests/test_crop_selection.py -q

# регрессия существующих тестов стратегий/политик
uv run pytest tests -q

# линт (в репозитории есть старые ошибки в других файлах — проверяем только изменённые)
uv run ruff check src/barbaros/widgets/image_crop/crop_selection.py tests/test_crop_selection.py
```

---

## 8. Критерии приёмки

### Автоматические

- [ ] `uv run pytest tests/test_crop_selection.py -q` — все тесты зелёные;
- [ ] `uv run pytest tests -q` — старые тесты (`policy`, `*_strategy`, i18n) не сломаны;
- [ ] `uv run ruff check src/barbaros/widgets/image_crop/crop_selection.py tests/test_crop_selection.py`
      — без ошибок (общий `ruff check` по репозиторию может содержать старые ошибки в других файлах);
- [ ] в `crop_selection.py` не осталось `handle_map`, `handle_size`,
      `_widget_rect_from_image`, `_to_widget_point`.

### Визуальные (ручная проверка в приложении)

1. `uv run python main.py` → вкладка «Изображение» → загрузить картинку → клик по превью
   (открывается `CropDialog`).
2. **Нет оранжевых квадратов**; рамка тонкая, 1 px, «инвертирует» картинку под собой.
3. Снаружи выделения картинка темнее (alpha 0.5), внутри — исходная. Тёмный/светлый фон
   просматривается под рамкой (Difference, а не белая линия).
4. Навести на угол — появляется «уголок» из 2 линий; на сторону — «скобка» из 3 линий;
   над центром выделения — скобки нет, курсор move.
5. Нажать и потянуть: затемнение **сразу исчезает**, рамка остаётся; отпустить —
   затемнение возвращается.
6. Уменьшить выделение так, чтобы его экранная сторона стала `< 120` — зона ручки
   уменьшается (b = сторона/3); скобка рисуется на новом месте.
7. Зум 10% / 800%: рамка остаётся 1 px, скобка не «толстеет», hit-зоны пересчитываются.
8. Изображение целиком (выделение = весь кадр): рамка по краю видна, затемнения нет
   (нечего затемнять) — это корректно.
9. Сравнить с `docs/specs/pix-crop-selector/hover-corner.png` и `drag-mask-off.png`
   (не учитывая сетку, панель и chrome — они вне спеки).

### Нефункциональные

- [ ] нет повторного декодирования/масштабирования изображения на кадр: используется
      закэшированный `self.pixmap`, в paint только `drawPixmap`;
- [ ] при движении мыши без смены зоны `update()` не вызывается (нет лишних repaint);
- [ ] на 50-мегапиксельном изображении драг не «залипает» (проверить вручную);
- [ ] нет новых утечек: QPainter/QPainterPath/QPen — локальные объекты, создаются/умирают
      в пределах `paintEvent`.

---

## 9. Риски и как их проверять

| Риск | Проверка/митигация |
|---|---|
| `CompositionMode_Difference` на другом бэкенде/платформе даёт иной цвет | тесты фиксируют raster-результат; ручная проверка в приложении; формула `255 - in` на непрозрачном фоне |
| Клип в Qt отрежет левую/верхнюю рамку (как было в эксперименте с `QRectF(+0.5)`) | тест `test_plain_render_mask_border_no_handles` проверяет пиксели `(20,50)` и `(50,20)` |
| Слишком большие зоны ручек (40 px) затрудняют move маленьких выделений | это поведение спеки; при жалобах — отдельное решение «разумный clamp» §8.1, не в этом PR |
| Пропадающие видимые ручки ухудшают discoverability | компенсируется курсорами и hover-скобкой; это осознанный дизайн Pix |
| Hover-скобка «зависает» после зума/смены выделения | сброс `hovered_handle` в `set_zoom`/`update_fit_scale`/`set_crop_rect` + тест косвенно |
| Смещение 1 px из-за независимого округления | это ожидаемо (§4 спеки); тест `test_selection_screen_rect_independent_rounding` |
| Выделение, которое при текущем зуме округляется в 0 px (крошечное выделение / зум 10%) | краевой случай спеки §8.5; отдельный fallback не делаем, рамка может выглядеть как 1–2 линии. Проверить вручную, в тесты не тащить |
| Ломается i18n-контекст | класс не переименовываем, строки не меняем; `.ts` при необходимости обновляется `invoke update_translations` |

---

## Приложение A. Быстрый рендер состояний для глазной проверки

Скрипт создаёт 4 PNG (обычное состояние, hover угла, hover стороны, драг) без запуска
всего приложения — удобно приложить к PR. Запускать из корня репозитория:

```python
# python scripts/render_crop_states.py  (создать при необходимости)
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from barbaros.widgets.image_crop.crop_selection import GimpStyleCropSelection
from barbaros.widgets.image_crop.transform_strategy import HandlePos

app = QApplication([])
image = QImage(597, 771, QImage.Format.Format_RGB32)
image.fill(QColor(70, 120, 160))

widget = GimpStyleCropSelection(image)
widget.update_fit_scale(800, 600)
widget.set_crop_rect(QRect(99, 128, 398, 514))

for name, handle, dragging in [
    ("plain", HandlePos.NONE, False),
    ("hover-tl", HandlePos.TOP_LEFT, False),
    ("hover-top", HandlePos.TOP_CENTER, False),
    ("drag", HandlePos.NONE, True),
]:
    widget.hovered_handle = handle
    widget.is_selecting = dragging
    target = QImage(widget.size(), QImage.Format.Format_RGB32)
    target.fill(QColor(0, 0, 0))
    widget.render(target)
    target.save(f"/tmp/crop-{name}.png")
```

Сравнивать с целевым поведением: тусклый фон снаружи, яркий внутри, 1-px инверсия,
никаких оранжевых квадратов; на hover — только тонкая L/П-образная скобка.

---

## Приложение B. Чек-лист для локальной модели (порядок действий)

1. Прочитать `docs/specs/pix-crop-selector/README.md` §2, §4–§6 и этот план целиком.
2. Открыть `src/barbaros/widgets/image_crop/crop_selection.py`, класс
   `GimpStyleCropSelection`.
3. Добавить импорты/константы/helper-функции (Шаг 1).
4. Удалить `handle_size`/`handle_map`, добавить `hovered_handle` (Шаг 2).
5. Заменить `_widget_rect_from_image` на `_selection_screen_rect` +
   `_selection_is_empty` + `_handle_zones`; переписать `get_handle_at` (Шаг 3).
6. Обновить `_update_cursor`, `mouseMoveEvent`, `mouseReleaseEvent`, добавить `leaveEvent`,
   фильтр левой кнопки, сброс hover (Шаг 4).
7. Полностью заменить `paintEvent` (Шаг 5).
8. Удалить мёртвый код, поправить docstring (Шаг 6).
9. Создать `tests/test_crop_selection.py` (Шаг 7).
10. `uv run pytest tests/test_crop_selection.py -q` — добиться зелёного.
11. `uv run pytest tests -q` и `uv run ruff check` — добиться зелёного.
12. Пройти визуальный чек-лист §8 и приложить 4 PNG из Приложения A к PR.
