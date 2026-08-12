"""Security policy helpers for outbound resource requests and client paths.

The helpers in this module deliberately perform no network requests and use
only the Python standard library.  Callers validate an initial URL and every
redirect target before handing it to an HTTP client.  A custom resolver can be
injected for deterministic tests or for an application-owned DNS layer.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
import ipaddress
from pathlib import Path, PurePosixPath, PureWindowsPath
import socket
from typing import TypeAlias
from urllib.parse import unquote, urljoin, urlsplit


IPAddress: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver: TypeAlias = Callable[[str, int], Iterable[str | IPAddress]]


class PolicyViolation(ValueError):
    """A stable, machine-readable rejection raised by a security policy."""

    def __init__(self, code: str, message: str, *, value: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.value = value


# Compatibility name used by the first service-layer callers.  New code should
# prefer ``PolicyViolation`` so the failure category is explicit.
PolicyError = PolicyViolation


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    """A URL whose syntax, host policy, and resolved addresses were checked."""

    url: str
    scheme: str
    hostname: str
    port: int
    addresses: tuple[IPAddress, ...]


def system_resolver(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve *hostname* with the system resolver, returning unique addresses."""

    addresses: list[str] = []
    seen: set[str] = set()
    for family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    ):
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        address = str(sockaddr[0])
        if address not in seen:
            seen.add(address)
            addresses.append(address)
    return tuple(addresses)


def _normalize_hostname(hostname: str) -> str:
    candidate = hostname.strip().rstrip(".")
    if not candidate:
        raise PolicyViolation("empty_host", "host must not be empty", value=hostname)

    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass

    try:
        normalized = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise PolicyViolation(
            "invalid_host", "host is not a valid DNS name", value=hostname
        ) from exc

    if len(normalized) > 253 or any(
        not label or len(label) > 63 for label in normalized.split(".")
    ):
        raise PolicyViolation(
            "invalid_host", "host is not a valid DNS name", value=hostname
        )
    return normalized


def _normalize_host_pattern(pattern: str) -> str:
    value = pattern.strip()
    if value.startswith("*."):
        suffix = _normalize_hostname(value[2:])
        try:
            ipaddress.ip_address(suffix)
        except ValueError:
            return f"*.{suffix}"
        raise PolicyViolation(
            "invalid_allowed_host",
            "wildcards cannot be used with IP addresses",
            value=pattern,
        )
    return _normalize_hostname(value)


def _reject_control_characters(value: str, *, code: str, label: str) -> None:
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
        raise PolicyViolation(
            code,
            f"{label} must not contain whitespace or control characters",
            value=value,
        )


def _parse_resolved_address(value: str | IPAddress) -> IPAddress:
    if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return value
    candidate = str(value).split("%", 1)[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError as exc:
        raise PolicyViolation(
            "resolver_invalid_address",
            "resolver returned a non-IP address",
            value=str(value),
        ) from exc


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Validate outbound HTTP(S) URLs against scheme, host and credential policy.

    ``allowed_hosts`` uses exact host matching.  A leading ``*.`` explicitly
    permits subdomains while excluding the bare suffix.  Resolved addresses are
    still returned for callers that need them, but no address-class blocking is
    applied; scheme, host allowlisting and redirect-count guards remain.
    """

    allowed_hosts: Collection[str]
    resolver: Resolver = field(default=system_resolver, repr=False, compare=False)
    max_redirects: int = 5

    def __post_init__(self) -> None:
        normalized = frozenset(_normalize_host_pattern(host) for host in self.allowed_hosts)
        if not normalized:
            raise PolicyViolation(
                "empty_allowed_hosts", "at least one allowed host is required"
            )
        if self.max_redirects < 0:
            raise PolicyViolation(
                "invalid_max_redirects", "max_redirects must be non-negative"
            )
        object.__setattr__(self, "allowed_hosts", normalized)

    def _host_is_allowed(self, hostname: str) -> bool:
        for pattern in self.allowed_hosts:
            if not isinstance(pattern, str):
                continue
            if pattern.startswith("*."):
                suffix = pattern[1:]
                if hostname.endswith(suffix) and hostname != pattern[2:]:
                    return True
            elif hostname == pattern:
                return True
        return False

    def validate_url(self, url: str) -> ValidatedUrl:
        """Validate one outbound URL and resolve all of its addresses."""

        if not isinstance(url, str) or not url:
            raise PolicyViolation("invalid_url", "URL must be a non-empty string")
        _reject_control_characters(
            url, code="url_control_character", label="URL"
        )

        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise PolicyViolation("invalid_url", "URL authority is invalid", value=url) from exc

        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise PolicyViolation(
                "unsupported_scheme",
                "only http and https URLs are permitted",
                value=parsed.scheme,
            )
        if parsed.username is not None or parsed.password is not None:
            raise PolicyViolation(
                "url_credentials",
                "credentials in URLs are not permitted",
                value=url,
            )
        if parsed.hostname is None:
            raise PolicyViolation("empty_host", "URL host must not be empty", value=url)

        hostname = _normalize_hostname(parsed.hostname)
        if not self._host_is_allowed(hostname):
            raise PolicyViolation(
                "host_not_allowed",
                f"host is not allowlisted: {hostname}",
                value=hostname,
            )

        effective_port = port if port is not None else (443 if scheme == "https" else 80)
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                resolved_values = tuple(self.resolver(hostname, effective_port))
            except PolicyViolation:
                raise
            except (OSError, socket.gaierror) as exc:
                raise PolicyViolation(
                    "dns_resolution_failed",
                    f"DNS resolution failed for {hostname}",
                    value=hostname,
                ) from exc
            if not resolved_values:
                raise PolicyViolation(
                    "dns_no_addresses",
                    f"DNS returned no addresses for {hostname}",
                    value=hostname,
                )
            addresses = tuple(_parse_resolved_address(value) for value in resolved_values)
        else:
            addresses = (literal,)

        unique_addresses = tuple(dict.fromkeys(addresses))

        return ValidatedUrl(
            url=url,
            scheme=scheme,
            hostname=hostname,
            port=effective_port,
            addresses=unique_addresses,
        )

    def validate_redirect(self, current_url: str, location: str) -> ValidatedUrl:
        """Resolve and validate one redirect target relative to *current_url*."""

        current = self.validate_url(current_url)
        if not isinstance(location, str) or not location:
            raise PolicyViolation(
                "invalid_redirect", "redirect location must be a non-empty string"
            )
        _reject_control_characters(
            location, code="redirect_control_character", label="redirect location"
        )
        return self.validate_url(urljoin(current.url, location))

    def validate_redirect_chain(
        self, initial_url: str, locations: Sequence[str]
    ) -> ValidatedUrl:
        """Validate an initial URL and each redirect target in order."""

        if len(locations) > self.max_redirects:
            raise PolicyViolation(
                "too_many_redirects",
                f"redirect count exceeds the limit of {self.max_redirects}",
            )
        current = self.validate_url(initial_url)
        for location in locations:
            if not isinstance(location, str) or not location:
                raise PolicyViolation(
                    "invalid_redirect", "redirect location must be a non-empty string"
                )
            _reject_control_characters(
                location,
                code="redirect_control_character",
                label="redirect location",
            )
            current = self.validate_url(urljoin(current.url, location))
        return current


def _fully_unquote(value: str) -> str:
    decoded = value
    # A successful percent decode shortens the string, so at most ``len(value)``
    # rounds are needed to reach a fixed point even for repeatedly encoded input.
    for _ in range(len(value) + 1):
        next_value = unquote(decoded, errors="strict")
        if next_value == decoded:
            return decoded
        decoded = next_value
    raise PolicyViolation(
        "invalid_client_path", "client path escaping did not reach a stable form"
    )


def validate_client_path(client_path: str) -> PurePosixPath:
    """Return a normalized relative path or reject absolute/traversal input."""

    if not isinstance(client_path, str) or not client_path:
        raise PolicyViolation(
            "invalid_client_path", "client path must be a non-empty string"
        )
    try:
        decoded = _fully_unquote(client_path)
    except UnicodeError as exc:
        raise PolicyViolation(
            "invalid_client_path", "client path contains invalid escaping"
        ) from exc
    if "\x00" in decoded:
        raise PolicyViolation("path_nul", "client path must not contain NUL")

    windows_path = PureWindowsPath(decoded)
    if windows_path.anchor or windows_path.drive:
        raise PolicyViolation(
            "absolute_client_path",
            "absolute or drive-qualified client paths are not permitted",
            value=client_path,
        )

    portable = decoded.replace("\\", "/")
    path = PurePosixPath(portable)
    if path.is_absolute() or portable.startswith("//"):
        raise PolicyViolation(
            "absolute_client_path",
            "absolute client paths are not permitted",
            value=client_path,
        )
    if any(part == ".." for part in path.parts):
        raise PolicyViolation(
            "path_traversal",
            "client path must not escape its assigned root",
            value=client_path,
        )

    normalized_parts = tuple(part for part in path.parts if part not in {"", "."})
    if not normalized_parts:
        raise PolicyViolation(
            "invalid_client_path", "client path must identify a relative target"
        )
    return PurePosixPath(*normalized_parts)


def resolve_client_path(root: str | Path, client_path: str) -> Path:
    """Resolve a client path under *root*, including protection from symlinks."""

    root_path = Path(root).resolve()
    relative = validate_client_path(client_path)
    candidate = root_path.joinpath(*relative.parts).resolve(strict=False)
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise PolicyViolation(
            "path_traversal",
            "resolved client path escapes its assigned root",
            value=client_path,
        ) from exc
    return candidate


def ensure_within_root(path: str | Path, root: str | Path) -> Path:
    """Return *path* resolved under *root* or reject an escape.

    Unlike :func:`resolve_client_path`, this helper accepts a server-created
    absolute path.  It exists for postcondition checks on downloader and archive
    results; client input should always go through ``validate_client_path``.
    """

    root_path = Path(root).resolve()
    candidate = Path(path).resolve(strict=False)
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise PolicyViolation(
            "path_traversal",
            "path escapes its assigned root",
            value=str(path),
        ) from exc
    return candidate


def validate_public_http_url(
    url: str,
    *,
    allowed_hosts: Collection[str] | None = None,
    resolver: Resolver = system_resolver,
) -> ValidatedUrl:
    """Compatibility entry point for validating one public HTTP(S) URL.

    Workflows should pass an explicit ``allowed_hosts`` set or retain a
    ``NetworkPolicy`` instance across the initial request and all redirects.
    When omitted, the one-shot policy is limited to the URL's own host.  Only
    scheme, host and credential rules are enforced; no address-class blocking
    is applied.
    """

    if not isinstance(url, str) or not url:
        raise PolicyViolation("invalid_url", "URL must be a non-empty string")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise PolicyViolation("invalid_url", "URL authority is invalid", value=url) from exc
    effective_hosts = allowed_hosts
    if effective_hosts is None:
        if parsed.hostname is None:
            raise PolicyViolation("empty_host", "URL host must not be empty", value=url)
        effective_hosts = (parsed.hostname,)
    return NetworkPolicy(
        allowed_hosts=effective_hosts,
        resolver=resolver,
    ).validate_url(url)


__all__ = [
    "NetworkPolicy",
    "PolicyError",
    "PolicyViolation",
    "Resolver",
    "ValidatedUrl",
    "ensure_within_root",
    "resolve_client_path",
    "system_resolver",
    "validate_public_http_url",
    "validate_client_path",
]
