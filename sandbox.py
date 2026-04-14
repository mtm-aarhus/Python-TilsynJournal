"""This module contains the main process of the robot."""

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueElement, QueueStatus

from robot_framework.process import process
import os
import json
from typing import Optional


def make_queue_element_with_payload(
    payload: dict | list,
    queue_name: str,
    reference: Optional[str] = None,
    created_by: Optional[str] = None,
    status: QueueStatus = QueueStatus.NEW, 
) -> QueueElement:
    # Validate & serialize
    data_str = json.dumps(payload, ensure_ascii=False)
    if len(data_str) > 2000:
        raise ValueError("data exceeds 2000 chars (column limit)")

    return QueueElement(
        queue_name=queue_name,
        status=status,
        data=data_str,
        reference=reference,
        created_by=created_by,
    )

# pylint: disable-next=unused-argum
orchestrator_connection = OrchestratorConnection(
    "TilsynBilleder",
    os.getenv("OpenOrchestratorSQL"),
    os.getenv("OpenOrchestratorKey"),
    None,
    None
)


qe = make_queue_element_with_payload(
    payload={
        "id": "101510493",
        "type": "permission",
        "inspector_email": "jadt@aarhus.dk",
        "comment": "Test",
        "selection": "Alt okay",
        "inspected_at": "2026-04-14T14:08:08"
    },
    queue_name="TilsynJournal",
    reference="Sandbox",
    status=QueueStatus.NEW, 
)

process(orchestrator_connection, qe)