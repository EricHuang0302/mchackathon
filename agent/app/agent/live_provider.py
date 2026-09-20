from __future__ import annotations

import asyncio
import json
import os
from queue import Empty, Full, Queue
from threading import Event, Thread, current_thread
from typing import Any, Protocol
from uuid import UUID, uuid4

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

    ALLOWED_KEYS = {
        "responsive",
        "breathing_normal",
        "location.address",
        "circumstances.whatHappened",
    }
    ALLOWED_TOOLS = {"find_nearest_aeds", "dispatch_helper"}
    PLAN_STEPS = {
        "confirm_observations": "確認 Gemini 擷取的現場資訊",
        "find_nearest_aeds": "查詢現場附近 AED",
        "dispatch_aed_runner": "建立 AED 取件協助者任務",
        "dispatch_ambulance_greeter": "建立救護車引導協助者任務",
        "prepare_handoff": "持續整理現場快照與交接時間軸",
    }

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

        def find_nearest_aeds(limit: int = 3) -> dict:
            """Find up to limit nearby AED candidates for the active incident."""
            return self._execute_tool("find_nearest_aeds", {"limit": limit})

        def dispatch_helper(role: str) -> dict:
            """Create an expiring QR invitation for an AED runner or ambulance greeter."""
            return self._execute_tool("dispatch_helper", {"role": role})

        agent = Agent(
            name="scene_observer",
            model=os.environ["GEMINI_MODEL"],
            tools=[find_nearest_aeds, dispatch_helper] if self._tool_executor else [],
            instruction=(
                "Extract only facts explicitly spoken by the user. Reply with one JSON object "
                "with observations and plan. observations is an array of key/value "
                "objects. Allowed keys are responsive, breathing_normal, location.address, and "
                "circumstances.whatHappened. Use the string unknown when uncertain. plan contains "
                "up to five steps whose id is one of confirm_observations, find_nearest_aeds, "
                "dispatch_aed_runner, dispatch_ambulance_greeter, or prepare_handoff. When a person is reported collapsed and "
                "unresponsive, include a plan to confirm the report and coordinate an AED runner, "
                "then call find_nearest_aeds and dispatch_helper with role aed_runner. Never give "
                "treatment advice, never claim an action happened, and never invent a location."
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
            candidate = text.strip()
            if candidate.startswith("```"):
                candidate = candidate.removeprefix("```json").removeprefix("```")
                candidate = candidate.removesuffix("```").strip()
            start, end = candidate.find("{"), candidate.rfind("}")
            payload = json.loads(candidate[start:end + 1] if start >= 0 and end >= start else candidate)
        except (ValueError, AttributeError):
            return
        if not isinstance(payload, dict):
            return
        proposals = payload.get("observations", [])
        if not isinstance(proposals, list):
            proposals = []
        for proposal in proposals[:5]:
            if not isinstance(proposal, dict) or proposal.get("key") not in self.ALLOWED_KEYS:
                continue
            value = proposal.get("value", "unknown")
            if proposal["key"] in {"responsive", "breathing_normal"}:
                if not isinstance(value, bool) and value != "unknown":
                    continue
            elif not isinstance(value, str) or len(value.strip()) == 0 or len(value) > 200:
                continue
            observation = {
                "type": "observation.proposed",
                "observationId": str(uuid4()), "key": proposal["key"],
                "value": value, "source": "model_proposal", "observedAt": now().isoformat(),
                "confirmation": "proposed", "evidenceEventIds": [],
            }
            if not self._enqueue(observation):
                return

        plan = payload.get("plan")
        if isinstance(plan, dict):
            raw_steps = plan.get("steps")
            steps = []
            seen_step_ids = set()
            if isinstance(raw_steps, list):
                for step in raw_steps[:5]:
                    if not isinstance(step, dict):
                        continue
                    step_id = step.get("id")
                    if step_id not in self.PLAN_STEPS or step_id in seen_step_ids:
                        continue
                    seen_step_ids.add(step_id)
                    steps.append({
                        "id": step_id,
                        "label": self.PLAN_STEPS[step_id],
                        "status": "proposed",
                    })
            if steps:
                plan_id = str(uuid4())
                if not self._enqueue({
                    "type": "task.plan",
                    "messageId": plan_id,
                    "plan": {
                        "planId": plan_id,
                        "summary": "Gemini 建議的現場協調計畫",
                        "steps": steps,
                    },
                }):
                    return

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
    if os.getenv("GEMINI_MODEL"):
        executor = None
        if service is not None:
            from app.agent.live_tools import LiveAgentToolExecutor
            executor = LiveAgentToolExecutor(service, uid, incident_id)
        return AdkObservationProvider(uid, incident_id, executor)
    return UnavailableProvider()
