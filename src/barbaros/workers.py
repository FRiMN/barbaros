import asyncio
import base64
import json
import logging
import threading
from collections.abc import Sequence

from any_llm.types.completion import ChatCompletion
from any_llm.types.model import Model
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from .model_manager import ProviderClient, ProviderMeta, _short_repr
from .provider_models import model_entries
from .widgets.filterable_combobox import ModelSelection

logger = logging.getLogger(__name__)

#: Total budget for one model-list request (BAR-23).
#:
#: ``any_llm`` leaves the HTTP timeouts at httpx's defaults (read 600 s), so a
#: stalled or hostile endpoint would keep the fetch -- and the app on shutdown
#: -- busy for up to ten minutes.  The worker bounds the whole request instead;
#: a per-request timeout keyword is provider-specific and not portable across
#: the providers any_llm supports (see the experiments in the BAR-23 PR).
LIST_MODELS_TIMEOUT_S = 20.0


class AbstractAsyncWorker(QObject):
    finished = Signal()
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self._task = None

    @Slot()
    def run(self):
        """Run in thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._task = loop.create_task(self.run_task())

        try:
            loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            self.cancelled.emit()
        finally:
            self.finished.emit()

    async def run_task(self):
        raise NotImplementedError

    def cancel(self):
        if not self._task:
            return

        self._task.get_loop().call_soon_threadsafe(self._task.cancel)


class TranslationWorker(AbstractAsyncWorker):
    done = Signal(ChatCompletion)
    error = Signal(str)

    def __init__(self, text_to_translate: str, target_language: str, model: ModelSelection, provider: ProviderClient):
        super().__init__()
        self.text_to_translate = text_to_translate
        self.target_language = target_language
        self.model = model
        self.text_prompt = f"""
        Target Language: {target_language}
        Text: {text_to_translate}
        """
        self.client = provider.client()

    async def run_task(self):
        from .resources_loader import Resource

        try:
            messages = [
                {"role": "system", "content": Resource.translation_agent_system_prompt.value},
                {"role": "user", "content": self.text_prompt}
            ]
            resp: ChatCompletion = await self.client.acompletion(self.model.model, messages)

            self.done.emit(resp)
        except Exception as e:
            self.error.emit(str(e))


class OCRWorker(AbstractAsyncWorker):
    done = Signal(ChatCompletion)
    error = Signal(str)

    def __init__(self, image_bytes: bytes, model: ModelSelection, provider: ProviderClient):
        super().__init__()
        self.image_bytes = image_bytes
        self.model = model
        self.client = provider.client()

    async def run_task(self):
        try:
            # BAR-25: fail closed. A client that cannot prove image support gets
            # no image at all; the image bytes are only encoded after this guard.
            if not getattr(self.client, "SUPPORTS_COMPLETION_IMAGE", False):
                provider_name = getattr(self.client, "PROVIDER_NAME", "unknown")
                self.error.emit(
                    f"Provider '{self.model.provider}' ({provider_name}) does not support images"
                )
                return

            base64_img = base64.b64encode(self.image_bytes).decode('utf-8')
            msg = [
                {"type": "text", "text": "Extract the text in the image."},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{base64_img}"
                }}
            ]

            messages = [
                {"role": "user", "content": msg}
            ]
            resp: ChatCompletion = await self.client.acompletion(self.model.model, messages)

            self.done.emit(resp)
        except Exception as e:
            self.error.emit(str(e))


class ListModelWorker(QObject):
    """Fetching models for provider."""

    finished = Signal(ProviderMeta, str)
    error = Signal(ProviderMeta, str)
    #: Terminal signal for every ``run()`` path, cancellation included.
    #:
    #: The thread quits on it.  A cancelled fetch must not be reported as
    #: ``error``: stopping a fetch is a normal user action (Reload, remove a
    #: provider, quit), and an error signal shows a modal dialog from
    #: ``MainWindow._show_provider_error``.
    stopped = Signal()

    def __init__(self, provider: ProviderClient, *, timeout: float | None = None):
        super().__init__()
        self.provider = provider.meta
        self.client = provider.client()
        # ``None`` defers to ``LIST_MODELS_TIMEOUT_S`` read in ``run()``, so a
        # test can shrink the budget of a worker the manager creates.
        self.timeout = timeout
        self._lock = threading.Lock()
        self._task: asyncio.Task | None = None
        self._cancel_requested = False

    @Slot()
    def run(self):
        """Fetch the list in this thread, bounded by the total timeout.

        The request is an asyncio task on a loop owned by this thread, so it
        can be cancelled from the GUI thread.  ``QThread.terminate()`` is not
        used: Qt discourages it and a terminated thread does not release the
        Python locks it holds (see ``_FetchResultsDispatcher`` in
        ``model_manager``).
        """
        timeout = self.timeout if self.timeout is not None else LIST_MODELS_TIMEOUT_S
        logger.debug("ListModelWorker: fetching models for %s", _short_repr(self.provider.name))

        # A private loop: nothing else in this thread waits for it, and the
        # running loop is what ``asyncio.get_event_loop()`` resolves to inside
        # the coroutine, so the thread-global loop is left untouched.
        loop = asyncio.new_event_loop()

        try:
            if self._cancel_pending():
                return

            task = loop.create_task(self._fetch_models(timeout))
            with self._lock:
                self._task = task
                cancel_requested = self._cancel_requested
            if cancel_requested:
                task.cancel()

            loop.run_until_complete(task)
        except asyncio.CancelledError:
            logger.debug("ListModelWorker: fetching models for %s cancelled", _short_repr(self.provider.name))
        except TimeoutError:
            self.error.emit(self.provider, f"list_models timeout after {timeout:g}s")
        except Exception as exc:
            logger.debug("ListModelWorker: fetching models for %s failed", _short_repr(self.provider.name))
            self.error.emit(self.provider, str(exc))
        finally:
            with self._lock:
                self._task = None
            loop.close()
            self.stopped.emit()

    async def _fetch_models(self, timeout: float):
        models: Sequence[Model] = await asyncio.wait_for(self.client.alist_models(), timeout=timeout)
        entries = model_entries(models)
        if len(entries) != len(models):
            logger.warning(
                "ListModelWorker: provider %s returned %d unusable model entries",
                _short_repr(self.provider.name),
                len(models) - len(entries),
            )

        logger.debug(
            "ListModelWorker: fetched %d model(s) for %s",
            len(models),
            _short_repr(self.provider.name),
        )
        self.finished.emit(self.provider, json.dumps(entries))

    def _cancel_pending(self) -> bool:
        with self._lock:
            return self._cancel_requested

    def cancel(self):
        """Request cooperative cancellation; safe to call at any time.

        Before ``run()`` starts the request is honoured by the flag check there
        (nothing is fetched), while running it cancels the asyncio task, which
        aborts the in-flight HTTP request.  After completion it is a no-op.
        """
        with self._lock:
            self._cancel_requested = True
            task = self._task

        if task is None:
            return

        try:
            task.get_loop().call_soon_threadsafe(task.cancel)
        except RuntimeError:
            # The loop is already closed: the fetch is over, nothing to cancel.
            logger.debug("ListModelWorker: loop already closed for %s", _short_repr(self.provider.name))

    def connect_terminate(self, thread: QThread):
        # ``thread.quit`` must be delivered while the manager blocks in
        # ``QThread.wait()`` (see ``ModelManager.stop_fetching_models``): a
        # queued connection would only run once the GUI thread returns to its
        # event loop, i.e. after the wait already timed out.  ``quit`` is
        # thread-safe, so it is called directly from the worker thread.
        for signal in (self.finished, self.error, self.stopped):
            signal.connect(self.deleteLater)
            signal.connect(thread.quit, Qt.ConnectionType.DirectConnection)
