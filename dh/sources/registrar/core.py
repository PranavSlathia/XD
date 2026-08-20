from __future__ import annotations

from dataclasses import dataclass

from dh.engine.configuration import CORE_TLDS


@dataclass(frozen=True, slots=True)
class TLDLifecycleAdapter:
    """Registry-specific boundary for a TLD supported by XD.

    The core six currently share Porkbun's authoritative availability vocabulary,
    but they remain separate adapters so registry-specific lifecycle rules can be
    introduced without changing the quote or readiness contracts.
    """

    tld: str
    quote_ttl_seconds: int = 15 * 60

    def availability_status(self, value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"yes", "available", "true", "1"}:
            return "available"
        if normalized in {"no", "unavailable", "false", "0", "registered"}:
            return "unavailable"
        return "unknown"

    def price_class(
        self,
        *,
        availability_status: str,
        quote_type: object,
        premium: bool | None,
        registration_price_micros: int | None,
    ) -> str:
        if availability_status != "available":
            return "unknown"
        normalized_type = str(quote_type or "").strip().lower().replace("_", "-")
        if normalized_type in {"auction", "backorder"}:
            return "auction"
        if normalized_type in {"aftermarket", "marketplace", "resale"}:
            return "aftermarket"
        if premium is True:
            return "premium"
        if (
            premium is False
            and registration_price_micros is not None
            and normalized_type in {"", "registration", "register", "standard"}
        ):
            return "normal"
        return "unknown"


TLD_ADAPTERS = {tld: TLDLifecycleAdapter(tld=tld) for tld in CORE_TLDS}


def adapter_for_domain(domain: str) -> TLDLifecycleAdapter:
    normalized = domain.strip().lower().rstrip(".")
    if "." not in normalized:
        raise ValueError("domain must include a supported TLD")
    tld = normalized.rsplit(".", 1)[1]
    try:
        return TLD_ADAPTERS[tld]
    except KeyError as exc:
        raise ValueError(f"unsupported TLD: .{tld}") from exc

