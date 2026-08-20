from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from urllib.parse import SplitResult, urlsplit, urlunsplit


class UnsafeTargetError(ValueError):
    pass


Resolver = Callable[[str], Awaitable[Sequence[str]]]


def _normalized_parts(url: str) -> SplitResult:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        raise UnsafeTargetError("only http and https URLs are crawlable")
    if not parts.hostname or parts.username or parts.password:
        raise UnsafeTargetError("URL must contain a plain public hostname")
    if parts.port not in {None, 80, 443}:
        raise UnsafeTargetError("non-standard ports are not crawlable")
    hostname = parts.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".local", ".internal", ".localhost")):
        raise UnsafeTargetError("local hostnames are blocked")
    netloc = hostname
    if parts.port is not None:
        netloc = f"{hostname}:{parts.port}"
    return SplitResult(
        scheme=parts.scheme,
        netloc=netloc,
        path=parts.path or "/",
        query=parts.query,
        fragment="",
    )


def validate_public_url(url: str, resolved_ips: Sequence[str]) -> str:
    parts = _normalized_parts(url)
    if not resolved_ips:
        raise UnsafeTargetError("hostname did not resolve")
    for raw in resolved_ips:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise UnsafeTargetError("resolver returned an invalid address") from exc
        if not address.is_global:
            raise UnsafeTargetError(f"non-public address blocked: {address}")
    return urlunsplit(parts)


async def system_resolver(hostname: str) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    rows = await loop.getaddrinfo(
        hostname,
        None,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    return tuple(dict.fromkeys(str(row[4][0]) for row in rows))


async def resolve_public_url(url: str, *, resolver: Resolver = system_resolver) -> str:
    parts = _normalized_parts(url)
    hostname = parts.hostname
    if hostname is None:
        raise UnsafeTargetError("hostname missing")
    addresses = await resolver(hostname)
    return validate_public_url(urlunsplit(parts), addresses)
