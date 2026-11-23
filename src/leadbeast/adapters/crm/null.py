"""Null CRM: no-op. Default when LB_CRM_PROVIDER=null."""

from __future__ import annotations

import uuid

from leadbeast.adapters.protocols import CrmAdapter, HealthReport


class NullCrm(CrmAdapter):
    key = "null"

    async def upsert_business(self, *, business_id: uuid.UUID, fields: dict[str, object]) -> str:
        return str(business_id)

    async def health(self) -> HealthReport:
        return HealthReport(key=self.key, status="healthy", detail="no CRM configured")
