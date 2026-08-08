"""Resource identity normalisation and conservative identity matching.

This module is deliberately independent of the public MCP schemas.  It can
normalise adapter output for internal retrieval without changing the public
``resource_id`` or teaching the model to manufacture one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from typing import Any

from .models import CandidateResourceInternal, ResourceIdentity


@dataclass(frozen=True)
class URLIdentityProfile:
    """Explicit rules for URL query canonicalisation.

    With no profile, the resolver removes only the URL fragment.  A profile
    may remove selected tracking/query keys or retain an explicit allow-list;
    it must never silently remove all query parameters.
    """

    platform: str | None = None
    remove_query_keys: frozenset[str] = frozenset()
    keep_query_keys: frozenset[str] | None = None
    sort_query: bool = False

    @classmethod
    def from_value(
        cls,
        value: "URLIdentityProfile | Mapping[str, Any] | str | None",
        *,
        platform: str | None = None,
    ) -> "URLIdentityProfile | None":
        if value is None:
            return None
        if isinstance(value, URLIdentityProfile):
            return value
        if isinstance(value, str):
            return get_url_identity_profile(value)
        if isinstance(value, Mapping):
            remove = value.get("remove_query_keys")
            if remove is None:
                remove = value.get("drop_query_keys")
            keep = value.get("keep_query_keys")
            return cls(
                platform=str(value.get("platform") or platform or "") or None,
                remove_query_keys=frozenset(
                    str(item).casefold() for item in (remove or ())
                ),
                keep_query_keys=(
                    frozenset(str(item).casefold() for item in keep)
                    if keep is not None
                    else None
                ),
                sort_query=bool(value.get("sort_query")),
            )
        raise TypeError("URL identity profile must be a profile, mapping, platform, or None")


# Only parameters known to be tracking for the named platform are removed.
# SmartEdu intentionally has an explicit empty profile: contentId,
# catalogType, courseId and similar query parameters are identity-bearing.
_PLATFORM_URL_PROFILES: dict[str, URLIdentityProfile] = {
    "bilibili": URLIdentityProfile(
        platform="bilibili",
        remove_query_keys=frozenset(
            {"from", "spm_id_from", "vd_source", "share_source", "share_medium"}
        ),
    ),
    "douyin": URLIdentityProfile(
        platform="douyin",
        remove_query_keys=frozenset(
            {"from_tab", "previous_page", "mode", "enter_from", "share_token"}
        ),
    ),
    "zhihu": URLIdentityProfile(
        platform="zhihu",
        remove_query_keys=frozenset(
            {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
        ),
    ),
    "ximalaya": URLIdentityProfile(
        platform="ximalaya",
        remove_query_keys=frozenset({"from", "source", "utm_source"}),
    ),
    "smartedu": URLIdentityProfile(platform="smartedu"),
    "annas-archive": URLIdentityProfile(platform="annas-archive"),
}


def get_url_identity_profile(platform: str | None) -> URLIdentityProfile | None:
    """Return a copyable built-in profile for *platform*, if one is known."""

    if not platform:
        return None
    return _PLATFORM_URL_PROFILES.get(str(platform).strip().casefold())


def _normalise_host(netloc: str) -> str:
    # URL identity is only used after the service's URL policy check.  Keep
    # userinfo/port syntax intact while applying the safe host case fold.
    if not netloc:
        return netloc
    return netloc.lower()


def normalize_url(
    value: str,
    profile: URLIdentityProfile | Mapping[str, Any] | str | None = None,
    *,
    platform: str | None = None,
) -> str | None:
    """Normalise a locator for identity comparison.

    The default operation is fragment removal plus scheme/host case
    normalisation.  Query text and ordering remain unchanged unless an
    explicit profile requests query filtering/sorting.
    """

    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    active_profile = URLIdentityProfile.from_value(profile, platform=platform)
    if active_profile is None and platform:
        active_profile = get_url_identity_profile(platform)

    query = parsed.query
    if active_profile is not None and query:
        pairs = parse_qsl(query, keep_blank_values=True)
        remove = active_profile.remove_query_keys
        keep = active_profile.keep_query_keys
        if keep is not None:
            pairs = [(key, val) for key, val in pairs if key.casefold() in keep]
        elif remove:
            pairs = [(key, val) for key, val in pairs if key.casefold() not in remove]
        if active_profile.sort_query:
            pairs = sorted(pairs, key=lambda pair: (pair[0], pair[1]))
        query = urlencode(pairs, doseq=True)

    # ``urlsplit`` is intentionally permissive here.  URL safety/HTTP(S)
    # validation belongs to the existing service policy layer.
    return urlunsplit(
        (
            parsed.scheme.lower(),
            _normalise_host(parsed.netloc),
            parsed.path or ("/" if parsed.netloc else ""),
            query,
            "",
        )
    )


# Common spelling aliases keep the resolver easy to discover without making
# callers import the existing search module.
normalize_canonical_url = normalize_url
canonicalize_url = normalize_url
canonical_url = normalize_url


def _isbn_digits(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"^ISBN(?:[-\s]?1[03])?\s*[:：]?\s*", "", text, flags=re.I)
    direct = re.sub(r"[^0-9Xx]", "", text).upper()
    if len(direct) in {10, 13}:
        return direct

    # If a label or prose surrounds the number, take a structurally plausible
    # ISBN substring instead of allowing unrelated digits into the identity.
    pattern = re.compile(
        r"(?:97[89](?:[\s-]*\d){10}|(?:\d[\s-]*){9}[\dXx])",
        re.I,
    )
    for match in pattern.finditer(text):
        candidate = re.sub(r"[^0-9Xx]", "", match.group(0)).upper()
        if len(candidate) in {10, 13}:
            return candidate
    return ""


def is_valid_isbn(value: str) -> bool:
    """Validate a normalised ISBN-10 or ISBN-13 check digit."""

    if len(value) == 10 and re.fullmatch(r"\d{9}[\dX]", value):
        total = sum((10 - index) * int(char) for index, char in enumerate(value[:9]))
        total += 10 if value[-1] == "X" else int(value[-1])
        return total % 11 == 0
    if len(value) == 13 and re.fullmatch(r"97[89]\d{10}", value):
        total = sum(
            (1 if index % 2 == 0 else 3) * int(char)
            for index, char in enumerate(value[:12])
        )
        return (10 - total % 10) % 10 == int(value[-1])
    return False


def normalize_isbn(value: Any) -> str | None:
    """Return a validated, separator-free ISBN-10/ISBN-13 or ``None``."""

    digits = _isbn_digits(value)
    return digits if digits and is_valid_isbn(digits) else None


def _normalize_isbn_for_identity(value: Any) -> str | None:
    """Return the ISBN-13 identity equivalent of a valid ISBN-10/ISBN-13.

    ``normalize_isbn`` intentionally retains its direct-format compatibility:
    callers that pass ISBN-10 still receive ISBN-10.  Identity comparison uses
    this stricter helper so the equivalent ISBN-10 and ISBN-13 share one key.
    Invalid check digits remain ``None`` and therefore cannot cause a merge.
    """

    normalized = normalize_isbn(value)
    if normalized is None or len(normalized) == 13:
        return normalized
    payload = "978" + normalized[:9]
    weighted_sum = sum(
        (1 if index % 2 == 0 else 3) * int(char)
        for index, char in enumerate(payload)
    )
    isbn13 = payload + str((10 - weighted_sum % 10) % 10)
    return isbn13 if is_valid_isbn(isbn13) else None


def _trim_doi(value: str) -> str:
    return value.strip().rstrip(".,;:)]}>'\"")


_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def normalize_doi(value: Any) -> str | None:
    """Normalise DOI labels and doi.org URLs to lower-case DOI values."""

    if value is None:
        return None
    text = unquote(unicodedata.normalize("NFKC", str(value)).strip())
    text = re.sub(r"^doi\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
    match = _DOI_RE.search(text)
    if not match:
        return None
    return _trim_doi(match.group(0)).casefold()


def _doi_from_url(value: Any) -> str | None:
    """Extract a DOI only from an authoritative doi.org resolver URL."""

    if value is None:
        return None
    parsed = urlsplit(str(value).strip())
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if hostname not in {"doi.org", "dx.doi.org"}:
        return None
    return normalize_doi(value)


def normalize_text(value: Any) -> str:
    """Stable, non-fuzzy text normalisation for weak fingerprints."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip().casefold()


def normalize_native_id(
    platform: str | None,
    native_id: Any,
    native_type: str | None = None,
) -> str | None:
    """Normalise a platform-native ID without removing its namespace."""

    if native_id is None:
        return None
    value = unicodedata.normalize("NFKC", str(native_id)).strip()
    if not value:
        return None
    platform_key = str(platform or "generic").strip().casefold()
    type_key = normalize_text(native_type).replace(" ", "_") or "id"

    if platform_key == "bilibili":
        bvid = re.search(r"\bBV[0-9A-Za-z]+\b", value, re.I)
        if bvid:
            token = bvid.group(0)
            return "BV" + token[2:]
        avid = re.search(r"\bav\d+\b", value, re.I)
        if avid:
            return "AV" + avid.group(0)[2:]
    elif platform_key == "annas-archive" and type_key in {"md5", "file", "book"}:
        match = re.search(r"\b[0-9a-f]{32}\b", value, re.I)
        if match:
            return match.group(0).casefold()
    elif platform_key in {"douyin", "ximalaya", "smartedu", "zhihu"}:
        # These native IDs are generally opaque strings or decimal IDs.  Do
        # not coerce numeric values to integers: leading zeroes can be facts.
        return value
    return value


def normalize_native_identity(
    platform: str | None,
    native_id: Any,
    native_type: str | None = None,
) -> ResourceIdentity | None:
    """Build a namespaced :class:`ResourceIdentity` from a native ID."""

    platform_value = str(platform or "generic").strip().casefold() or "generic"
    type_value = normalize_text(native_type).replace(" ", "_") or "id"
    id_value = normalize_native_id(platform_value, native_id, type_value)
    if not id_value:
        return None
    return ResourceIdentity(
        platform=platform_value,
        native_type=type_value,
        native_id=id_value,
    )


def _candidate_mapping(candidate: CandidateResourceInternal | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(candidate, CandidateResourceInternal):
        return {
            "resource_id": candidate.resource_id,
            "platform": candidate.platform,
            "resource_type": candidate.resource_type,
            "title": candidate.title,
            "canonical_url": candidate.canonical_url,
            "summary": candidate.summary,
            "author": candidate.author,
            "creator": candidate.creator,
            "published_at": candidate.published_at,
            "availability": candidate.availability,
            "native_identity": candidate.native_identity,
            "native_type": candidate.native_type,
            "native_id": candidate.native_id,
            "isbn": candidate.isbn,
            "doi": candidate.doi,
            "edition": candidate.edition,
            "version": candidate.version,
            "signals": candidate.signals,
            "metadata": candidate.metadata,
        }
    return dict(candidate)


def _sources(candidate: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = [candidate]
    for key in ("signals", "platform_signals", "metadata"):
        value = candidate.get(key)
        if isinstance(value, Mapping):
            result.append(value)
            nested = value.get("platform_signals")
            if isinstance(nested, Mapping):
                result.append(nested)
    metadata = candidate.get("metadata")
    if isinstance(metadata, Mapping):
        for key in ("signals", "identifiers", "identity"):
            value = metadata.get(key)
            if isinstance(value, Mapping):
                result.append(value)
    return result


def _first_value(sources: list[Mapping[str, Any]], *keys: str) -> Any:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value is not None and value != "":
                return value
    return None


def _native_from_url(
    platform: str,
    url: str | None,
) -> tuple[str | None, str | None]:
    if not url:
        return None, None
    parsed = urlsplit(url)
    path = parsed.path
    platform_key = platform.casefold()
    if platform_key == "bilibili":
        match = re.search(r"/video/((?:BV|av)[0-9A-Za-z]+)", path, re.I)
        if match:
            token = match.group(1)
            return ("video", normalize_native_id(platform, token, "video"))
    elif platform_key == "douyin":
        match = re.search(r"/(?:video|note)/(\d+)", path, re.I)
        if match:
            return "video", match.group(1)
    elif platform_key == "zhihu":
        match = re.search(r"/question/(\d+)/answer/(\d+)", path, re.I)
        if match:
            return "answer", match.group(2)
        match = re.search(r"/question/(\d+)", path, re.I)
        if match:
            return "question", match.group(1)
        match = re.search(r"/(?:zhuanlan/)?p/(\d+)", path, re.I)
        if match:
            return "article", match.group(1)
    elif platform_key == "ximalaya":
        match = re.search(r"/album/(\d+)", path, re.I)
        if match:
            return "album", match.group(1)
    elif platform_key == "annas-archive":
        match = re.search(r"/md5/([0-9a-f]{32})", path, re.I)
        if match:
            return "md5", match.group(1).casefold()
    elif platform_key == "smartedu":
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        native_id = next(
            (
                query.get(key)
                for key in (
                    "contentId",
                    "content_id",
                    "resourceId",
                    "resource_id",
                    "activityId",
                    "activity_id",
                    "courseId",
                    "course_id",
                    "id",
                )
                if query.get(key)
            ),
        )
        if native_id:
            native_type = query.get("contentType") or query.get("resourceType") or "content"
            return normalize_text(native_type).replace(" ", "_") or "content", native_id
    return None, None


def _explicit_native(
    candidate: Mapping[str, Any],
    sources: list[Mapping[str, Any]],
    platform: str,
) -> tuple[str | None, str | None]:
    raw = candidate.get("native_identity")
    if isinstance(raw, ResourceIdentity):
        if raw.native_id:
            return raw.native_type or "id", raw.native_id
    if isinstance(raw, Mapping):
        raw_type = raw.get("native_type") or raw.get("type") or raw.get("kind")
        raw_id = raw.get("native_id") or raw.get("id") or raw.get("value")
        if str(raw_type or "").casefold() in {"platform_id", "native_id", "native"}:
            raw_type = raw.get("native_type") or "id"
        if raw_id:
            return str(raw_type or "id"), str(raw_id)
    if raw and not isinstance(raw, Mapping):
        return str(candidate.get("native_type") or "id"), str(raw)

    direct_type = _first_value(sources, "native_type", "nativeType", "object_type", "objectType")
    direct_id = _first_value(sources, "native_id", "nativeId", "external_id", "externalId")
    if direct_id:
        return str(direct_type or "id"), str(direct_id)

    platform_key = platform.casefold()
    key_groups: dict[str, tuple[str, ...]] = {
        "bilibili": ("bvid", "bv", "aid", "av"),
        "douyin": ("aweme_id", "awemeId", "video_id", "videoId"),
        "zhihu": (
            "answer_id",
            "answerId",
            "question_id",
            "questionId",
            "article_id",
            "articleId",
            "object_id",
            "objectId",
        ),
        "ximalaya": ("album_id", "albumId"),
        "annas-archive": ("md5", "MD5"),
        "smartedu": (
            "content_id",
            "contentId",
            "resource_id",
            "resourceId",
            "activity_id",
            "activityId",
            "course_id",
            "courseId",
        ),
        "weibo": ("bid", "blog_id", "blogId", "mid"),
    }
    keys = key_groups.get(platform_key, ("external_id", "externalId"))
    native_id = _first_value(sources[1:], *keys)
    if native_id is None:
        # For adapter signal dictionaries, a platform-specific ID is safe;
        # root resource_id is intentionally never used as native identity.
        native_id = _first_value(
            [source for source in sources if source is not candidate],
            "id",
        )
    if native_id is None:
        return None, None

    if platform_key == "bilibili":
        native_type = "video"
    elif platform_key == "douyin":
        native_type = "video"
    elif platform_key == "zhihu":
        if any(_first_value(sources, key) is not None for key in ("answer_id", "answerId")):
            native_type = "answer"
        elif any(_first_value(sources, key) is not None for key in ("question_id", "questionId")):
            native_type = "question"
        elif any(_first_value(sources, key) is not None for key in ("article_id", "articleId")):
            native_type = "article"
        else:
            native_type = str(direct_type or "object")
    elif platform_key == "ximalaya":
        native_type = "album"
    elif platform_key == "annas-archive":
        native_type = "md5"
    elif platform_key == "smartedu":
        native_type = str(
            _first_value(sources, "content_type", "contentType", "resource_type", "resourceType")
            or "content"
        )
    elif platform_key == "weibo":
        native_type = "post"
    else:
        native_type = str(direct_type or "id")
    return native_type, str(native_id)


def _extract_identifier(
    sources: list[Mapping[str, Any]],
    key_names: tuple[str, ...],
    normalizer: Any,
) -> str | None:
    for source in sources:
        for key in key_names:
            value = source.get(key)
            if value is None or value == "":
                continue
            normalised = normalizer(value)
            if normalised:
                return normalised
    return None


def weak_fingerprint(
    *,
    title: Any,
    creator: Any = None,
    edition: Any = None,
) -> str | None:
    """Create the deliberately weak title/creator/edition identity.

    A title alone is not sufficient.  This prevents two editions or two
    unrelated resources with the same generic title from being merged.
    """

    title_value = normalize_text(title)
    creator_value = normalize_text(creator)
    edition_value = normalize_text(edition)
    if not title_value or not (creator_value or edition_value):
        return None
    return "|".join((title_value, creator_value, edition_value))


def resolve_identity(
    candidate: CandidateResourceInternal | Mapping[str, Any],
    profile: URLIdentityProfile | Mapping[str, Any] | str | None = None,
) -> ResourceIdentity:
    """Resolve all available identity evidence from an adapter candidate."""

    if isinstance(candidate, ResourceIdentity):
        return candidate
    raw = _candidate_mapping(candidate)
    sources = _sources(raw)
    platform = normalize_text(raw.get("platform") or raw.get("platform_id") or "generic")
    platform = platform.replace(" ", "-") or "generic"

    native_type, native_id = _explicit_native(raw, sources, platform)
    if native_id:
        native_id = normalize_native_id(platform, native_id, native_type)
    if not native_id:
        url_for_native = raw.get("canonical_url") or raw.get("source_url") or raw.get("url")
        inferred_type, inferred_id = _native_from_url(platform, str(url_for_native) if url_for_native else None)
        native_type = inferred_type
        native_id = inferred_id

    raw_url = raw.get("canonical_url") or raw.get("source_url") or raw.get("url")
    isbn = _extract_identifier(
        sources,
        ("isbn", "ISBN", "isbn10", "isbn13", "isbn_10", "isbn_13"),
        _normalize_isbn_for_identity,
    )
    doi = _extract_identifier(
        sources,
        ("doi", "DOI", "doi_url", "doiUrl"),
        normalize_doi,
    )
    if doi is None:
        doi = _doi_from_url(raw_url)
    canonical = normalize_url(
        str(raw_url),
        profile if profile is not None else platform,
    ) if raw_url else None

    creator = _first_value(sources, "creator", "author", "author_name", "authorName")
    edition = _first_value(
        sources,
        "edition",
        "edition_id",
        "editionId",
        "version",
        "curriculum_version",
        "curriculumVersion",
    )
    fingerprint = weak_fingerprint(
        title=raw.get("title") or raw.get("name"),
        creator=creator,
        edition=edition,
    )
    return ResourceIdentity(
        platform=platform,
        native_type=(normalize_text(native_type).replace(" ", "_") if native_type else None),
        native_id=native_id,
        isbn=isbn,
        doi=doi,
        canonical_url=canonical,
        fingerprint=fingerprint,
    )


def _native_tuple(identity: ResourceIdentity) -> tuple[str, str, str] | None:
    if not identity.native_id:
        return None
    return (
        identity.platform or "generic",
        identity.native_type or "id",
        identity.native_id,
    )


def identities_conflict(left: ResourceIdentity, right: ResourceIdentity) -> bool:
    """Return whether two identity evidence sets contain a hard conflict."""

    left_native = _native_tuple(left)
    right_native = _native_tuple(right)
    # Native IDs are namespaced locators. Different IDs inside the same
    # platform are conflicting evidence, while IDs from different platforms
    # are not directly comparable (for example NLC and Anna/Libgen records for
    # the same ISBN).
    if (
        left_native
        and right_native
        and left_native[0] == right_native[0]
        and left_native != right_native
    ):
        return True
    if left.isbn and right.isbn and left.isbn != right.isbn:
        return True
    if left.doi and right.doi and left.doi != right.doi:
        return True

    shared_stronger = bool(
        left_native
        and right_native
        and left_native == right_native
    ) or bool(left.isbn and right.isbn and left.isbn == right.isbn) or bool(
        left.doi and right.doi and left.doi == right.doi
    )
    if (
        left.canonical_url
        and right.canonical_url
        and left.canonical_url != right.canonical_url
        and not shared_stronger
    ):
        return True
    return False


def identities_match(left: ResourceIdentity, right: ResourceIdentity) -> bool:
    """Conservatively decide whether two candidates are the same resource."""

    if identities_conflict(left, right):
        return False
    if left.native_id and right.native_id and _native_tuple(left) == _native_tuple(right):
        return True
    if left.isbn and right.isbn and left.isbn == right.isbn:
        return True
    if left.doi and right.doi and left.doi == right.doi:
        return True
    if left.canonical_url and right.canonical_url and left.canonical_url == right.canonical_url:
        return True
    if (
        left.fingerprint
        and right.fingerprint
        and left.fingerprint == right.fingerprint
        and not left.is_strong
        and not right.is_strong
    ):
        return True
    return False


identity_conflicts = identities_conflict
same_resource_identity = identities_match


__all__ = [
    "URLIdentityProfile",
    "canonical_url",
    "canonicalize_url",
    "get_url_identity_profile",
    "identities_conflict",
    "identities_match",
    "identity_conflicts",
    "is_valid_isbn",
    "normalize_canonical_url",
    "normalize_doi",
    "normalize_isbn",
    "normalize_native_id",
    "normalize_native_identity",
    "normalize_text",
    "normalize_url",
    "resolve_identity",
    "same_resource_identity",
    "weak_fingerprint",
]
