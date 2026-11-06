"""Round-trip tests for CropDialog and its integration with ImageManagerWidget.

The crop widget/strategy tests cover the geometry; these tests cover the path
users actually take: open the crop dialog, accept or cancel it, get the
cropped image, and hand it over to the OCR feature through ImageManagerWidget.
"""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QDialog

from barbaros.widgets import image_manager
from barbaros.widgets.image_crop.crop_selection import CropDialog
from barbaros.widgets.image_manager import ImageManagerWidget

IMAGE_COLOR = QColor(70, 120, 160)
MARKER_COLOR = QColor(200, 50, 50)
IMAGE_SIZE = (400, 300)
INITIAL_CROP = QRect(50, 50, 200, 150)


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def image() -> QImage:
    image = QImage(*IMAGE_SIZE, QImage.Format.Format_RGB32)
    image.fill(IMAGE_COLOR)
    return image


def press(widget, pos: QPoint):
    point = QPointF(pos)
    widget.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            point,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def release(widget, pos: QPoint):
    point = QPointF(pos)
    widget.mouseReleaseEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            point,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


# ---------- CropDialog ----------


def test_close_accepts_crop_and_copies_the_selected_region(image):
    image.setPixelColor(60, 60, MARKER_COLOR)  # inside INITIAL_CROP
    image.setPixelColor(10, 10, MARKER_COLOR)  # outside, must not be copied

    dialog = CropDialog(image, initial_crop_rect=INITIAL_CROP)
    dialog.close()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.get_crop_rect() == INITIAL_CROP
    cropped = dialog.get_cropped_image()
    assert cropped is not None
    assert cropped.size() == INITIAL_CROP.size()
    assert cropped.pixelColor(10, 10) == MARKER_COLOR
    assert cropped.pixelColor(0, 0) == IMAGE_COLOR


def test_reject_returns_no_crop(image):
    dialog = CropDialog(image, initial_crop_rect=INITIAL_CROP)
    dialog.reject()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.get_crop_rect() is None
    assert dialog.get_cropped_image() is None


def test_click_without_drag_accepts_a_min_size_crop(image):
    dialog = CropDialog(image, initial_crop_rect=INITIAL_CROP)
    crop_widget = dialog.crop_widget

    press(crop_widget, QPoint(5, 5))
    release(crop_widget, QPoint(5, 5))
    dialog.close()

    assert dialog.result() == QDialog.DialogCode.Accepted
    cropped = dialog.get_cropped_image()
    assert cropped is not None
    assert cropped.width() >= 50
    assert cropped.height() >= 50


# ---------- wheel zoom ----------
#
# The widget draws the image scaled to its own size and lives in a scroll area,
# so zooming is a size change plus a scrollbar shift. Users expect the point
# under the mouse wheel to stay under the cursor (like in image viewers), not
# the top-left corner of the image.

ZOOM_NOTCH = 120


def show_dialog(image: QImage, initial_crop_rect: QRect = INITIAL_CROP) -> CropDialog:
    """A shown dialog: the scroll area only gets a viewport after show()."""
    dialog = CropDialog(image, initial_crop_rect=initial_crop_rect)
    dialog.show()
    QApplication.processEvents()
    QApplication.processEvents()  # deferred initial fit
    return dialog


def image_point_under(crop_widget, viewport, point: QPoint) -> QPointF:
    """Image pixel shown under a point of the scroll area viewport."""
    widget_point = crop_widget.mapFrom(viewport, point)
    return QPointF(
        widget_point.x() / crop_widget.scale_factor,
        widget_point.y() / crop_widget.scale_factor,
    )


def anchor_distance(
    crop_widget, viewport, viewport_point: QPoint, image_point: QPointF
) -> QPointF:
    """How far (in widget pixels) an image point sits from the cursor now.

    The scrollbars move in whole pixels, so after a zoom the anchored point may
    be off by less than one pixel; anything larger is a real drift.
    """
    widget_point = QPointF(crop_widget.mapFrom(viewport, viewport_point))
    expected = image_point * crop_widget.scale_factor
    return QPointF(widget_point.x() - expected.x(), widget_point.y() - expected.y())


def wheel(crop_widget, viewport, viewport_point: QPoint, up: bool = True):
    """Scroll wheel over the crop widget at the given viewport point."""
    widget_point = crop_widget.mapFrom(viewport, viewport_point)
    angle = ZOOM_NOTCH if up else -ZOOM_NOTCH
    crop_widget.wheelEvent(
        QWheelEvent(
            QPointF(widget_point),
            QPointF(widget_point),
            QPoint(),
            QPoint(0, angle),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
    )
    QApplication.processEvents()  # the scrollbar correction is deferred


def test_wheel_zoom_keeps_the_image_point_under_the_cursor(image):
    dialog = show_dialog(image)
    try:
        crop_widget = dialog.crop_widget
        crop_widget.set_zoom(3.0)  # a state where both axes can scroll
        QApplication.processEvents()
        viewport = dialog.scroll_area.viewport()
        cursor = QPoint(viewport.width() // 2 + 40, viewport.height() // 2 + 30)

        for _ in range(8):
            anchor = image_point_under(crop_widget, viewport, cursor)
            wheel(crop_widget, viewport, cursor, up=True)
            drift = anchor_distance(crop_widget, viewport, cursor, anchor)
            assert abs(drift.x()) <= 1.0
            assert abs(drift.y()) <= 1.0
    finally:
        dialog.close()


def test_wheel_zoom_out_keeps_the_image_point_under_the_cursor(image):
    dialog = show_dialog(image)
    try:
        crop_widget = dialog.crop_widget
        crop_widget.set_zoom(4.0)
        QApplication.processEvents()
        # Start from the middle of a scrollable view: zooming out at the very
        # top-left corner cannot keep the anchor, the content is already pinned.
        scroll_area = dialog.scroll_area
        scroll_area.horizontalScrollBar().setValue(
            scroll_area.horizontalScrollBar().maximum() // 2
        )
        scroll_area.verticalScrollBar().setValue(
            scroll_area.verticalScrollBar().maximum() // 2
        )
        QApplication.processEvents()
        viewport = scroll_area.viewport()
        cursor = QPoint(viewport.width() // 2, viewport.height() // 2)

        zoom_before = crop_widget.zoom_level
        for _ in range(5):
            anchor = image_point_under(crop_widget, viewport, cursor)
            wheel(crop_widget, viewport, cursor, up=False)
            drift = anchor_distance(crop_widget, viewport, cursor, anchor)
            assert abs(drift.x()) <= 1.0
            assert abs(drift.y()) <= 1.0
        assert crop_widget.zoom_level < zoom_before
    finally:
        dialog.close()


def test_wheel_zoom_scrolls_towards_the_cursor_not_the_top_left_corner(image):
    dialog = show_dialog(image)
    try:
        crop_widget = dialog.crop_widget
        crop_widget.set_zoom(3.0)
        QApplication.processEvents()
        viewport = dialog.scroll_area.viewport()
        scroll_area = dialog.scroll_area
        scroll_area.horizontalScrollBar().setValue(0)
        scroll_area.verticalScrollBar().setValue(0)

        # Near the bottom-right corner the content must be scrolled towards it;
        # a top-left-anchored zoom would leave the scrollbars at zero.
        cursor = QPoint(viewport.width() - 20, viewport.height() - 20)
        wheel(crop_widget, viewport, cursor, up=True)

        assert scroll_area.horizontalScrollBar().value() > 0
        assert scroll_area.verticalScrollBar().value() > 0
    finally:
        dialog.close()


def test_wheel_zoom_keeps_the_crop_rect(image):
    dialog = show_dialog(image)
    try:
        crop_widget = dialog.crop_widget
        crop_before = crop_widget.get_crop_rect()
        viewport = dialog.scroll_area.viewport()
        wheel(
            crop_widget,
            viewport,
            QPoint(viewport.width() // 2, viewport.height() // 2),
        )
        assert crop_widget.get_crop_rect() == crop_before
    finally:
        dialog.close()


# ---------- ImageManagerWidget round trip ----------


def test_image_manager_applies_the_accepted_crop(image, monkeypatch):
    widget = ImageManagerWidget(None)
    emitted = []
    widget.imageCropped.connect(lambda: emitted.append(True))
    widget.set_image(image, "test.png")
    emitted.clear()

    applied = QRect(100, 100, 120, 80)

    class AcceptingDialog(CropDialog):
        rect_to_apply = applied

        def exec(self):
            self.crop_widget.set_crop_rect(self.rect_to_apply)
            self.close()
            return self.result()

    monkeypatch.setattr(image_manager, "CropDialog", AcceptingDialog)
    widget._crop_preview.clicked.emit()

    assert widget.get_crop_rect() == applied
    assert widget.get_cropped_image().size() == applied.size()
    assert widget._crop_preview.crop_rect == applied
    assert emitted == [True]


def test_image_manager_keeps_state_when_the_dialog_is_cancelled(image, monkeypatch):
    widget = ImageManagerWidget(None)
    widget.set_image(image, "test.png")
    previous_rect = widget.get_crop_rect()
    previous_image = widget.get_cropped_image()

    class CancellingDialog(CropDialog):
        def exec(self):
            self.reject()
            return self.result()

    monkeypatch.setattr(image_manager, "CropDialog", CancellingDialog)
    widget._crop_preview.clicked.emit()

    assert widget.get_crop_rect() == previous_rect
    assert widget.get_cropped_image() is previous_image
