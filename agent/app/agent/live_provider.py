from __future__ import annotations

import asyncio
import json
import os
from queue import Empty, Full, Queue
from threading import Event, Thread, current_thread
from typing import Protocol
from uuid import UUID, uuid4

from app.api.errors import ApiError, unavailable
from app.services.mock import now


class ObservationProvider(Protocol):
    def start(self) -> None: ...
    def send_audio(self, data: bytes) -> None: ...
    def poll(self) -> list[dict]: ...
    def close(self) -> None: ...


class UnavailableProvider:
    def start(self) -> None:
        raise unavailable()

    def send_audio(self, data: bytes) -> None:
        raise unavailable()

    def poll(self) -> list[dict]:
        return []

    def close(self) -> None:
        pass


class AdkObservationProvider:
    """ADK Live audio in, allowlisted unconfirmed observations out.

    Model text and audio are never forwarded directly as treatment guidance.
    """

    ALLOWED_KEYS = {"responsive", "breathing_normal"}

    def __init__(self, uid: str, incident_id: UUID):
        self.uid = uid
        self.incident_id = incident_id
        self._input: Queue[bytes | None] = Queue(maxsize=24)
        self._output: Queue[dict] = Queue(maxsize=24)
        self._ready = Event()
        self._stopped = Event()
        self._error: Exception | None = None
        self._thread: Thread | None = None

    def start(self) -> None:
        if not os.getenv("GEMINI_MODEL"):
            raise unavailable()
        try:
            import google.adk  # noqa: F401
            import google.genai  # noqa: F401
        except ImportError:
            raise unavailable() from None
        self._thread = Thread(target=self._run, daemon=True, name="adk-live-observations")
        self._thread.start()
        if not self._ready.wait(timeout=8) or self._error:
            self.close()
            raise unavailable()

    def send_audio(self, data: bytes) -> None:
        if self._stopped.is_set():
            raise unavailable()
        try:
            self._input.put_nowait(data)
        except Full:
            raise ApiError("unavailable", 503, "Live media queue full") from None

    def poll(self) -> list[dict]:
        output = []
        while len(output) < 8:
            try:
                output.append(self._output.get_nowait())
            except Empty:
                break
        return output

    def close(self) -> None:
        self._stopped.set()
        try:
            self._input.put_nowait(None)
        except Full:
            pass
        if self._thread and self._thread is not current_thread():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            asyncio.run(self._session())
        except Exception as exc:
            self._error = exc
            self._ready.set()
        finally:
            self._stopped.set()

    async def _session(self) -> None:
        from google.adk.agents import Agent, LiveRequestQueue
        from google.adk.agents.run_config import RunConfig
        from google.adk.runners import InMemoryRunner
        from google.genai import types

        agent = Agent(
            name="scene_observer",
            model=os.environ["GEMINI_MODEL"],
            instruction=(
                "Transcribe only explicitly reported facts. Reply with a single JSON object "
                "containing observations, an array of objects with key and value. "
                "Allowed keys: responsive, breathing_normal. "
                "Use the string unknown when uncertain. Do not give treatment advice."
            ),
        )
        runner = InMemoryRunner(agent=agent, app_name="first_aid_copilot")
        session = await runner.session_service.create_session(
            app_name="first_aid_copilot", user_id=self.uid,
        )
        live_queue = LiveRequestQueue()
        config = RunConfig(response_modalities=["TEXT"], save_live_blob=False)

        async def pump() -> None:
            while not self._stopped.is_set():
                data = await asyncio.to_thread(self._input.get)
                if data is None:
                    break
                live_queue.send_realtime(types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
            live_queue.close()

        sender = asyncio.create_task(pump())
        self._ready.set()
        pending_text: list[str] = []
        try:
            async for event in runner.run_live(session=session, live_request_queue=live_queue, run_config=config):
                if self._stopped.is_set():
                    break
                for part in event.content.parts if event.content and event.content.parts else []:
                    if getattr(part, "text", None):
                        pending_text.append(part.text)
                if event.interrupted:
                    pending_text.clear()
                elif event.turn_complete and pending_text:
                    self._accept_text("".join(pending_text))
                    pending_text.clear()
        finally:
            self._stopped.set()
            live_queue.close()
            sender.cancel()

    def _accept_text(self, text: str) -> None:
        try:
            proposals = json.loads(text).get("observations", [])
        except (ValueError, AttributeError):
            return
        if not isinstance(proposals, list):
            return
        for proposal in proposals[:5]:
            if not isinstance(proposal, dict) or proposal.get("key") not in self.ALLOWED_KEYS:
                continue
            value = proposal.get("value", "unknown")
            if proposal["key"] in {"responsive", "breathing_normal"}:
                if not isinstance(value, bool) and value != "unknown":
                    continue
            elif not isinstance(value, str) or len(value) > 200:
                continue
            observation = {
                "observationId": str(uuid4()), "key": proposal["key"],
                "value": value, "source": "model_proposal", "observedAt": now().isoformat(),
                "confirmation": "proposed", "evidenceEventIds": [],
            }
            try:
                self._output.put_nowait(observation)
            except Full:
                break


def default_provider(uid: str, incident_id: UUID) -> ObservationProvider:
    if os.getenv("GEMINI_MODEL"):
        return AdkObservationProvider(uid, incident_id)
    return UnavailableProvider()
