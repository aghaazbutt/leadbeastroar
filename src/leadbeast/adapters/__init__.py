"""Protocol-based integrations with the outside world.

Every external edge (source, contact, CRM, channel, model, report) is a
Protocol. Implementations live in sibling packages (source/, channel/,
crm/, model/, report/). Pipeline code depends on the Protocol, never on a
concrete class — swapping EspoCRM for HubSpot is a one-file change.
"""

from leadbeast.adapters.protocols import (
    ChannelAdapter,
    ContactProvider,
    CrmAdapter,
    DetectorProtocol,
    DetectorResult,
    DraftRequest,
    HealthReport,
    ModelClient,
    ReportRenderer,
    SendResult,
    SourceAdapter,
    SourceRecordIn,
)

__all__ = [
    "ChannelAdapter",
    "ContactProvider",
    "CrmAdapter",
    "DetectorProtocol",
    "DetectorResult",
    "DraftRequest",
    "HealthReport",
    "ModelClient",
    "ReportRenderer",
    "SendResult",
    "SourceAdapter",
    "SourceRecordIn",
]
