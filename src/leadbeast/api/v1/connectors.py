from __future__ import annotations

from fastapi import APIRouter

from leadbeast.adapters import ChannelAdapter, CrmAdapter, ModelClient
from leadbeast.adapters.registry import registry
from leadbeast.api.deps import AuthDep
from leadbeast.api.v1.schemas import HealthOut

router = APIRouter(prefix="/connectors", tags=["connectors"], dependencies=[AuthDep])


@router.get("/health", response_model=list[HealthOut])
async def health() -> list[HealthOut]:
    reports = []
    for proto, _label in [
        (ModelClient, "model"),
        (ChannelAdapter, "channel"),
        (CrmAdapter, "crm"),
    ]:
        if registry.has(proto):
            adapter = registry.get(proto)
            r = await adapter.health()
            reports.append(HealthOut(key=r.key, status=r.status, detail=r.detail))
    return reports
