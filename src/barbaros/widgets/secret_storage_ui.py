"""Translated wording for the API-key storage statuses (BAR-11).

The status words appear in more than one widget (the providers table and the
edit dialog), so the mapping lives here instead of being duplicated.  The
longer, widget-specific sentences stay in the widget that shows them.

``QCoreApplication.translate`` is called directly with literal strings (not
through the ``_()`` helper) so ``pyside6-lupdate`` extracts these messages.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from barbaros.security import SecretStatus


def status_label(status: SecretStatus) -> str:
    """A short label for a read status; empty for ``FOUND``/``MISSING``."""
    if status is SecretStatus.LOCKED:
        return QCoreApplication.translate("SecretStorage", "locked")
    if status is SecretStatus.UNAVAILABLE:
        return QCoreApplication.translate("SecretStorage", "unavailable")
    if status is SecretStatus.CORRUPT:
        return QCoreApplication.translate("SecretStorage", "corrupt")
    return ""


def status_hint(status: SecretStatus) -> str:
    """A one-line explanation for a read status, used as a tooltip."""
    if status is SecretStatus.LOCKED:
        return QCoreApplication.translate(
            "SecretStorage",
            "The system keyring is locked. Unlock it and try again.",
        )
    if status is SecretStatus.UNAVAILABLE:
        return QCoreApplication.translate(
            "SecretStorage",
            "The system keyring cannot be reached, so the saved API key cannot be read.",
        )
    if status is SecretStatus.CORRUPT:
        return QCoreApplication.translate(
            "SecretStorage",
            "The saved keyring entry is unreadable. Re-enter the key to replace it.",
        )
    return ""
