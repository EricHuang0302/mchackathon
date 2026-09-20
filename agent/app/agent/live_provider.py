from __future__ import annotations

import asyncio
import os
from queue import Empty, Full, Queue
from threading import Event, Thread, current_thread
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.agent import scene_extraction
from app.agent.scene_extraction import SceneExtraction
from app.api.errors import ApiError, unavailable
from app.services.mock import now


class ObservationProvider(Protocol):
    def start(self) -> None: ...
    def send_audio(self, data: bytes) -> None: ...
    def poll(self) -> list[dict]: ...
    def close(self) -> None: ...


class AgentToolExecutor(Protocol):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


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

    ALLOWED_KEYS = scene_extraction.ALLOWED_KEYS
    ALLOWED_TOOLS = scene_extraction.ALLOWED_TOOLS
    PLAN_STEPS = scene_extraction.PLAN_STEPS

    def __init__(
        self,
        uid: str,
        incident_id: UUID,
        tool_executor: AgentToolExecutor | None = None,
    ):
        self.uid = uid
        self.incident_id = incident_id
        self._input: Queue[bytes | None] = Queue(maxsize=24)
        self._output: Queue[dict] = Queue(maxsize=24)
        self._ready = Event()
        self._stopped = Event()
        self._error: Exception | None = None
        self._thread: Thread | None = None
        self._tool_executor = tool_executor

    def start(self) -> None:
        if not (os.getenv("GEMINI_TRANSCRIBE_MODEL") or os.getenv("GEMINI_MODEL")):
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
            self._enqueue({"type": "error", "code": "unavailable"})
            self._ready.set()
        finally:
            self._stopped.set()

    async def _session(self) -> None:
        from google import genai
        from google.adk.agents import Agent, LiveRequestQueue
        from google.adk.agents.run_config import RunConfig
        from google.adk.runners import InMemoryRunner
        from google.genai import types

        agent = Agent(
            name="scene_observer",
            model=os.getenv("GEMINI_TRANSCRIBE_MODEL") or os.environ["GEMINI_MODEL"],
            instruction=(
                "Listen to the user's scene report. Do not give treatment advice. The application "
                "uses the input transcript for a separate bounded extraction step."
            ),
        )
        runner = InMemoryRunner(agent=agent, app_name="first_aid_copilot")
        session = await runner.session_service.create_session(
            app_name="first_aid_copilot", user_id=self.uid,
        )
        live_queue = LiveRequestQueue()
        config = RunConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            save_live_blob=False,
        )
        text_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        async def pump() -> None:
            while not self._stopped.is_set():
                data = await asyncio.to_thread(self._input.get)
                if data is None:
                    break
                live_queue.send_realtime(types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
            live_queue.close()

        sender = asyncio.create_task(pump())
        self._ready.set()
        last_transcript = ""
        try:
            async for event in runner.run_live(session=session, live_request_queue=live_queue, run_config=config):
                if self._stopped.is_set():
                    break
                if event.input_transcription and event.input_transcription.text:
                    transcript = event.input_transcription.text.strip()
                    if transcript and transcript != last_transcript:
                        await self._extract_transcript(text_client, transcript)
                        last_transcript = transcript
                if event.interrupted:
                    last_transcript = ""
        finally:
            self._stopped.set()
            live_queue.close()
            sender.cancel()
            await text_client.aio.aclose()

    async def _extract_transcript(self, client, transcript: str) -> None:
        from google.genai import types

        response = await client.aio.models.generate_content(
            model=os.getenv("GEMINI_TEXT_MODEL", "gemini-3.8-flash"),
            contents=scene_extraction.extraction_prompt(transcript),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SceneExtraction,
                temperature=0,
            ),
        )
        parsed = response.parsed
        if isinstance(parsed, SceneExtraction):
            self._accept_payload(parsed.model_dump(mode="json", exclude_none=True))
        elif isinstance(parsed, dict):
            self._accept_payload(parsed)
        elif response.text:
            self._accept_text(response.text)

    def _accept_text(self, text: str) -> None:
        payload = scene_extraction.payload_from_text(text)
        if payload is not None:
            self._accept_payload(payload)

    def _accept_payload(self, payload: dict[str, Any]) -> None:
        for key, value in scene_extraction.observation_values(payload):
            observation = {
                "type": "observation.proposed",
                "observationId": str(uuid4()), "key": key,
                "value": value, "source": "model_proposal", "observedAt": now().isoformat(),
                "confirmation": "proposed", "evidenceEventIds": [],
            }
            if not self._enqueue(observation):
                return

        steps = scene_extraction.plan_steps(payload)
        if steps:
            plan_id = str(uuid4())
            if not self._enqueue({
                "type": "task.plan",
                "messageId": plan_id,
                "plan": {
                    "planId": plan_id,
                    "summary": scene_extraction.PLAN_SUMMARY,
                    "steps": steps,
                },
            }):
                return

        if self._tool_executor is None:
            return
        for name, arguments in scene_extraction.tool_actions(payload):
            self._execute_tool(name, arguments)

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.ALLOWED_TOOLS or self._tool_executor is None:
            raise ApiError("invalid_input", 400, "Unknown Agent tool")
        call_id = str(uuid4())
        try:
            result = self._tool_executor.execute(name, arguments)
            self._enqueue({
                "type": "agent.tool.completed",
                "messageId": call_id,
                "toolCallId": call_id,
                "name": name,
                "status": "completed",
                "result": result,
            })
            return result
        except Exception as exc:
            code = getattr(exc, "code", "unavailable")
            self._enqueue({
                "type": "agent.tool.completed",
                "messageId": call_id,
                "toolCallId": call_id,
                "name": name,
                "status": "failed",
                "error": code,
            })
            return {"error": code}

    def _enqueue(self, event: dict) -> bool:
        try:
            self._output.put_nowait(event)
            return True
        except Full:
            return False


def default_provider(uid: str, incident_id: UUID, service=None) -> ObservationProvider:
    if os.getenv("GEMINI_TRANSCRIBE_MODEL") or os.getenv("GEMINI_MODEL"):
        executor = None
        if service is not None:
            from app.agent.live_tools import LiveAgentToolExecutor
            executor = LiveAgentToolExecutor(service, uid, incident_id)
        return AdkObservationProvider(uid, incident_id, executor)
    return UnavailableProvider()
