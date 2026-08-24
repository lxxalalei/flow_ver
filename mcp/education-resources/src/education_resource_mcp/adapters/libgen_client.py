"""Synchronous LibGen client shared by search and download adapters.

The client uses public HTML mirrors, stdlib urllib and BeautifulSoup.
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request

from bs4 import BeautifulSoup

from .http_client import urlopen_with_fallback


@dataclass
class Book:
    md5: str
    title: str
    author: str = ""
    publisher: str = ""
    year: str = ""
    language: str = ""
    pages: str = ""
    size: str = ""
    extension: str = ""
    edition_id: str = ""
    file_id: str = ""
    isbn: str = ""
    series: str = ""
    description: str = ""
    mirrors: dict[str, str] = field(default_factory=dict)


@dataclass
class LibgenDownloadResult:
    path: Path
    size_bytes: int
    mirror: str
    url: str
    filename: str


class LibgenError(RuntimeError):
    pass


class MirrorUnavailable(LibgenError):
    pass


class BookNotFound(LibgenError):
    pass


_MD5_RE = re.compile(r"[a-f0-9]{32}")


def _clean(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return unicodedata.normalize("NFKC", text)


def _mirror_links_from_badges(badge_td: str, md5: str, base: str) -> dict[str, str]:
    links: dict[str, str] = {}
    for a in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*title="([^"]*)"', badge_td):
        href, title = a.group(1), _clean(a.group(2))
        if title:
            links[title.lower()] = urljoin(base, href)
    return links


class LibgenClient:
    """Synchronous Libgen search & download client (mirror-failover)."""

    def __init__(
        self,
        mirrors: list[str],
        user_agent: str,
        timeout: float = 30.0,
    ) -> None:
        self.mirrors = [m.rstrip("/") for m in mirrors]
        self.timeout = timeout
        self._headers = {"User-Agent": user_agent}

    # -- low level ----------------------------------------------------------

    def _get(self, mirror: str, path: str, **params: Any) -> str:
        url = f"{mirror}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers=self._headers)
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:
            status = getattr(exc, "code", None)
            if status in (403, 429, 503):
                raise MirrorUnavailable(f"{url} -> HTTP {status}") from exc
            raise LibgenError(f"{url} -> {type(exc).__name__}: {exc}") from exc

    def _try_mirrors(self, path: str, **params: Any) -> tuple[str, str]:
        last_err: Optional[Exception] = None
        for mirror in self.mirrors:
            try:
                return mirror, self._get(mirror, path, **params)
            except Exception as exc:
                last_err = exc
        raise MirrorUnavailable(
            f"All mirrors failed for {path}: {last_err}"
        ) from last_err

    # -- search -------------------------------------------------------------

    def search(
        self,
        query: str,
        page: int = 1,
        limit: int = 20,
        language: Optional[str] = None,
        extension: Optional[str] = None,
    ) -> list[Book]:
        params: dict[str, Any] = {"req": query, "page": page}
        if language:
            params["lang"] = language
        if extension:
            params["extension"] = extension
        mirror, html_text = self._try_mirrors("/index.php", **params)
        books = self._parse_search(html_text, mirror, limit)
        return books

    def _parse_search(self, page_html: str, mirror: str, limit: int) -> list[Book]:
        soup = BeautifulSoup(page_html, "lxml")
        books: list[Book] = []
        for tr in soup.find_all("tr"):
            if "ads.php" not in str(tr):
                continue
            md5_match = _MD5_RE.search(str(tr))
            if not md5_match:
                continue
            md5 = md5_match.group(0)
            cells = tr.find_all("td")
            if len(cells) < 9:
                continue
            title_td, badge_td = cells[0], cells[8]
            title_a = title_td.find("a", href=re.compile(r"edition\.php\?id="))
            title = _clean(title_a.get_text(" ", strip=True)) if title_a else _clean(title_td.get_text(" ", strip=True))
            edition_id = ""
            if title_a and (m := re.search(r"edition\.php\?id=(\d+)", title_a.get("href", ""))):
                edition_id = m.group(1)
            isbn = ""
            green = title_td.find("font", attrs={"color": re.compile("green", re.I)})
            if green:
                isbn = _clean(green.get_text(" ", strip=True))
            size_td = cells[6]
            size_a = size_td.find("a", href=re.compile(r"file\.php\?id="))
            size = _clean(size_a.get_text(" ", strip=True)) if size_a else _clean(size_td.get_text(" ", strip=True))
            file_id = ""
            if size_a and (m := re.search(r"file\.php\?id=(\d+)", size_a.get("href", ""))):
                file_id = m.group(1)
            books.append(Book(
                md5=md5, title=title,
                author=_clean(cells[1].get_text(" ", strip=True)),
                publisher=_clean(cells[2].get_text(" ", strip=True)),
                year=_clean(cells[3].get_text(" ", strip=True)),
                language=_clean(cells[4].get_text(" ", strip=True)),
                pages=_clean(cells[5].get_text(" ", strip=True)),
                size=size,
                extension=_clean(cells[7].get_text(" ", strip=True)),
                edition_id=edition_id, file_id=file_id, isbn=isbn,
                mirrors=_mirror_links_from_badges(str(badge_td), md5, mirror),
            ))
            if len(books) >= limit:
                break
        return books

    # -- detail -------------------------------------------------------------

    def get_book(self, md5: str) -> Book:
        md5 = md5.lower().strip()
        if not _MD5_RE.fullmatch(md5):
            raise LibgenError(f"Invalid md5: {md5!r}")
        mirror, html_text = self._try_mirrors("/ads.php", md5=md5)
        book = self._parse_detail(html_text, md5, mirror)
        if not book:
            raise BookNotFound(f"No book found for md5 {md5}")
        if book.file_id:
            try:
                file_html = self._get(mirror, "/file.php", id=book.file_id)
                self._parse_file_record(file_html, book)
            except LibgenError:
                pass
        return book

    def _parse_detail(self, page_html: str, md5: str, mirror: str) -> Optional[Book]:
        soup = BeautifulSoup(page_html, "lxml")
        book = Book(md5=md5, title="", mirrors={})
        info_cell = None
        for td in soup.find_all("td"):
            text = _clean(td.get_text(" ", strip=True))
            if text.lower().startswith("title:"):
                info_cell = td
                break
        if info_cell is None:
            return None
        parts = [p for p in re.split(r"<br\s*/?>", str(info_cell)) if p.strip()]
        labels = {
            "title": "title", "author(s)": "author", "series": "series",
            "periodical": "series", "publisher": "publisher", "year": "year",
            "edition": "edition_id", "language": "language", "pages": "pages",
            "isbn": "isbn", "size": "size", "extension": "extension",
        }
        for part in parts:
            text = _clean(BeautifulSoup(part, "lxml").get_text(" ", strip=True))
            if ":" not in text:
                continue
            label, _, value = text.partition(":")
            key = label.strip().lower()
            if key in labels:
                setattr(book, labels[key], _clean(value))
        bib = soup.find("textarea", attrs={"id": re.compile("bib", re.I)})
        if bib:
            m = re.search(r"@\w+\{book:\{(\d+)\}", bib.get_text("", strip=True))
            if m:
                book.file_id = m.group(1)
        if not book.file_id:
            m = re.search(r"@\w+\{book:\{(\d+)\}", page_html)
            if m:
                book.file_id = m.group(1)
        for a in soup.find_all("a", href=re.compile(r"get\.php\?md5=")):
            book.mirrors["libgen_download"] = urljoin(mirror + "/", a.get("href", ""))
            break
        book.mirrors.setdefault("libgen", f"{mirror}/ads.php?md5={md5}")
        if not book.title:
            return None
        return book

    def _parse_file_record(self, page_html: str, book: Book) -> None:
        soup = BeautifulSoup(page_html, "lxml")
        mapping = {
            "filesize": "size", "extension": "extension", "pages (in file)": "pages",
            "file id": "file_id", "language": "language",
        }
        seen: set[str] = set()
        for strong in soup.find_all("strong"):
            key = _clean(strong.get_text(" ", strip=True)).rstrip(":").strip().lower()
            if key not in mapping or key in seen:
                continue
            container = strong.parent
            parts, started = [], False
            for child in container.children:
                if child is strong:
                    started = True
                    continue
                if started and getattr(child, "name", None) in ("p", "div", "br", "table"):
                    break
                if started:
                    parts.append(child.get_text(" ", strip=True) if hasattr(child, "get_text") else str(child))
            value = _clean(" ".join(parts)).strip(" :")
            attr = mapping[key]
            if attr and value:
                setattr(book, attr, value)
            seen.add(key)
        if not book.language:
            m = re.search(r"Languages?:\s*([^\n<]{2,60})", page_html)
            if m:
                book.language = _clean(m.group(1))
        if not book.description:
            m = re.search(r"Annotation:\s*(.{1,500}?)(?:<br|</p>|<div|$)", page_html, re.S)
            if m:
                book.description = _clean(m.group(1))

    # -- download -----------------------------------------------------------

    def download(
        self, md5: str, dest_dir: str | Path,
        cancel_event: Optional[Any] = None,
    ) -> LibgenDownloadResult:
        md5 = md5.lower().strip()
        if not _MD5_RE.fullmatch(md5):
            raise LibgenError(f"Invalid md5: {md5!r}")
        last_err: Optional[Exception] = None
        for mirror in self.mirrors:
            try:
                return self._download_from(mirror, md5, dest_dir, cancel_event)
            except Exception as exc:
                last_err = exc
        raise LibgenError(f"Download failed on all mirrors: {last_err}") from last_err

    def _download_from(
        self, mirror: str, md5: str, dest_dir: str | Path,
        cancel_event: Optional[Any] = None,
    ) -> LibgenDownloadResult:
        ads_html = self._get(mirror, "/ads.php", md5=md5)
        soup = BeautifulSoup(ads_html, "lxml")
        get_a = None
        for a in soup.find_all("a", href=re.compile(r"get\.php\?md5=")):
            get_a = a
            break
        if get_a is None:
            raise BookNotFound(f"No download link for md5 {md5} on {mirror}")
        get_url = urljoin(mirror + "/", get_a.get("href", ""))
        title = ""
        for td in soup.find_all("td"):
            t = _clean(td.get_text(" ", strip=True))
            if t.lower().startswith("title:"):
                for part in re.split(r"<br\s*/?>", str(td)):
                    text = _clean(BeautifulSoup(part, "lxml").get_text(" ", strip=True))
                    if text.lower().startswith("title:"):
                        title = _clean(text.partition(":")[2])
                        break
                break
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        request = Request(get_url, headers=self._headers)
        with urlopen_with_fallback(request, timeout=self.timeout * 3) as resp:
            filename = self._filename_from(resp, title, md5)
            out = dest / filename
            size = 0
            with open(out, "wb") as fh:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        out.unlink(missing_ok=True)
                        raise LibgenError("JOB_CANCELLED")
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    fh.write(chunk)
        return LibgenDownloadResult(path=out, size_bytes=size, mirror=mirror, url=get_url, filename=filename)

    @staticmethod
    def _filename_from(resp: Any, title: str, md5: str) -> str:
        from urllib.parse import unquote
        cd = resp.headers.get("content-disposition", "")
        name = ""
        m = re.search(r'filename\*\s*=\s*(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
        if m and "%" in m.group(1):
            try:
                name = unquote(m.group(1).strip())
            except Exception:
                name = m.group(1).strip()
        if not name:
            m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
            if m:
                name = m.group(1).strip().strip('"')
        if not name:
            name = str(resp.url).split("/")[-1].split("?")[0] or md5
        ext = Path(name).suffix or ""
        if title:
            safe = re.sub(r'[\\/:*?"<>|]+', "_", title).strip().strip(" .")
            if len(safe) >= 2:
                name = f"{safe}{ext}" if ext else safe
        if len(name) > 180:
            name = name[: 180 - len(ext)] + ext
        return name


_DEFAULT_MIRRORS = ["https://libgen.bz", "https://libgen.gl"]
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def create_libgen_client(timeout: float = 30.0) -> LibgenClient:
    """Factory: mirrors/UA overridable via env vars ANNA_LIBGEN_MIRRORS / ANNA_USER_AGENT."""
    import os
    raw = os.environ.get("ANNA_LIBGEN_MIRRORS", "").strip()
    mirrors = [m.strip().rstrip("/") for m in raw.split(",") if m.strip()] or _DEFAULT_MIRRORS
    ua = os.environ.get("ANNA_USER_AGENT", "").strip() or _DEFAULT_UA
    return LibgenClient(mirrors, ua, timeout)
