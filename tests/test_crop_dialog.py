"""Round-trip tests for CropDialog and its integration with ImageManagerWidget.

The crop widget/strategy tests cover the geometry; these tests cover the path
users actually take: open the crop dialog, accept or cancel it, get the
cropped image, and hand it over to the OCR feature through ImageManagerWidget.
"""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
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
