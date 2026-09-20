from uuid import uuid4

from app.agent.live_tools import LiveAgentToolExecutor
from app.schemas.contracts import CreateIncidentRequest
from app.services.mock import SyntheticIncidentService


def test_live_tools_create_one_reusable_runner_invitation():
    service = SyntheticIncidentService()
    incident_id, client_id = uuid4(), uuid4()
    service.create_incident(
        "alice",
        CreateIncidentRequest(
            incidentId=incident_id,
            primaryClientId=client_id,
            ruleVersion="demo-v1",
        ),
    )
    executor = LiveAgentToolExecutor(service, "alice", incident_id)

    first = executor.execute("dispatch_helper", {"role": "aed_runner"})
    repeated = executor.execute("dispatch_helper", {"role": "aed_runner"})
    aeds = executor.execute("find_nearest_aeds", {"limit": 3})

    assert first == repeated
    assert first["scope"] == "aed_runner"
    assert first["helperId"]
    assert len(first["secret"]) >= 32
    assert aeds == {"candidates": [], "dataUpdatedAt": None}
