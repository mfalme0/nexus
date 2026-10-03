"""Evidence records: what a tool actually observed, and whether it is trustworthy.

The README's core constraint is that NEXUS must never confuse sounding confident
with being correct, and that the honest failure mode is:

    "I could not verify disk usage because the host did not respond."

For that to be expressible, "could not measure" has to be a *value* rather than an
exception or a missing field. Every probe therefore returns an `Evidence` whose
`status` says whether the value was really observed. A caller cannot mistake a
missing reading for a healthy one, because UNAVAILABLE is a distinct, inspectable
state rather than `None`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EvidenceStatus(StrEnum):
    """Whether an observation was actually obtained."""

    OBSERVED = "OBSERVED"
    """The value came from the real system and can be cited as fact."""

    UNAVAILABLE = "UNAVAILABLE"
    """The probe could not reach its source. `value` is None and `detail` says why."""


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Evidence:
    """One observation about a host, with provenance.

    `source` names where the reading came from (a path, a command, an API) so a
    later explanation can cite the specific thing that was checked rather than
    asserting a conclusion.
    """

    key: str
    status: EvidenceStatus
    source: str
    observed_at: datetime = field(default_factory=utcnow)
    value: Mapping[str, Any] | None = None
    detail: str | None = None

    @property
    def observed(self) -> bool:
        """True when the value came from the real system and may be cited as fact."""
        return self.status is EvidenceStatus.OBSERVED

    @property
    def required_evidence_covered(self) -> bool:
        """Reads naturally when aggregating coverage for a proposed conclusion."""
        return self.status is EvidenceStatus.OBSERVED

    def as_claim(self) -> str:
        """A sentence the agent can quote verbatim in an explanation.

        An UNAVAILABLE probe renders as an explicit inability to verify, never as a
        silent omission, so a gap in evidence shows up in the output instead of
        being smoothed over.
        """
        if self.status is EvidenceStatus.OBSERVED:
            return f"{self.key}: {self.value} (observed from {self.source})"
        return f"{self.key}: could not verify - {self.detail or 'source unavailable'}"

    @classmethod
    def observed_value(
        cls,
        key: str,
        source: str,
        value: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> "Evidence":
        return cls(
            key=key,
            status=EvidenceStatus.OBSERVED,
            source=source,
            observed_at=now or utcnow(),
            value=value,
        )

    @classmethod
    def unavailable(cls, key: str, source: str, detail: str) -> "Evidence":
        return cls(
            key=key,
            status=EvidenceStatus.UNAVAILABLE,
            source=source,
            value=None,
            detail=detail,
        )
