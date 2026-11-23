"""Fetch a daily RSS, Atom, and Gemsub edition and write a Plucker record database."""

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from email.message import Message
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import os
import re
import signal
import socket
import ssl
import tempfile
import subprocess
import struct
import sys
import textwrap
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as XML

DB_NAME = b"J-Pilot RSS Today"
MAX_DOWNLOAD = 4 * 1024 * 1024
ARTICLES_PER_INDEX_PAGE = 100
MAX_ARTICLES = 500
pin_dir = Path.home() / ".jpilot" / "rss-plucker-gemini-pins"


@dataclass
class Article:
    title: str
    source: str
    published: dt.datetime
    url: str
    content: str
    summary: str
    base: str = ""
    media: tuple = ()


@dataclass(frozen=True)
class ArticleImage:
    url: str
    alt: str = ""


def http_url(url):
    parts = urlsplit(url)
    return parts.scheme in ("https", "http") and bool(parts.hostname)


def resolve(base, target):
    # urllib only joins relative references for a fixed list of schemes.
    if urlsplit(base).scheme == "gemini" and not urlsplit(target).scheme:
        return "gemini:" + urljoin("https:" + base.split(":", 1)[1], target)[6:]
    return urljoin(base, target)


def check_certificate(host, port, certificate):
    pin_dir.mkdir(mode=0o700, exist_ok=True)
    key = hashlib.sha256(f"{host}:{port}".encode()).hexdigest()
    pin = pin_dir / key
    digest = hashlib.sha256(certificate).hexdigest()
    if not pin.exists():
        with tempfile.NamedTemporaryFile(dir=pin_dir, mode="w") as tmp:
            tmp.write(digest)
            tmp.flush()
            try:
                os.link(tmp.name, pin)
            except FileExistsError:
                pass
    if pin.read_text() != digest:
        raise ValueError("Gemini certificate changed")


def read_payload(stream):
    payload = stream.read(MAX_DOWNLOAD + 1)
    if len(payload) > MAX_DOWNLOAD:
        raise ValueError("response exceeds 4 MiB")
    return payload


def fetch(url, timeout=8):
    for _ in range(6):
        parts = urlsplit(url)
        if http_url(url):
            request = Request(url, headers={"User-Agent": "J-Pilot-Feeds-to-Plucker/1.0"})
            with urlopen(request, timeout=timeout) as response:
                return read_payload(response), response.geturl(), response.headers
        if parts.scheme != "gemini" or not parts.hostname:
            raise ValueError("unsupported URL")
        if any(ord(c) < 33 for c in url):
            raise ValueError("invalid Gemini URL")
        url = parts._replace(fragment="").geturl()
        request = url.encode()
        if len(request) > 1024:
            raise ValueError("Gemini URL too long")
        host = parts.hostname
        port = parts.port or 1965
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # Verify the capsule's pinned certificate below.
        with socket.create_connection((host, port), timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                check_certificate(host, port, tls.getpeercert(binary_form=True))
                tls.sendall(request + b"\r\n")
                with tls.makefile("rb") as stream:
                    header = stream.readline(1030)
                    match = re.fullmatch(rb"([0-9]{2}) ([^\r\n]{0,1024})\r\n", header)
                    if not match:
                        raise ValueError("invalid Gemini response")
                    status, meta = match.groups()
                    if status.startswith(b"3") and meta:
                        url = resolve(url, meta.decode())
                        continue
                    if not status.startswith(b"2"):
                        raise ValueError("Gemini request failed")
                    headers = Message()
                    headers["Content-Type"] = meta.decode() or "text/gemini"
                    return read_payload(stream), url, headers
    raise ValueError("too many redirects")


def decode(payload, headers):
    try:
        return payload.decode(headers.get_content_charset() or "utf-8", errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def gemtext_lines(markup, base):
    literal = False
    for line in markup.splitlines():
        if line.startswith("```"):
            literal = not literal
        elif not literal and line.startswith("=>"):
            fields = line[2:].split(None, 1)
            if fields:
                yield "link", resolve(base, fields[0]), fields[1].strip() if len(fields) > 1 else ""
        elif not literal and line.startswith("# "):
            yield "heading", "", line[2:].strip()
        elif line.strip():
            yield "text", "", line


def gemsub(markup, base, today):
    articles = []
    source = None
    published = dt.datetime.combine(today, dt.time()).astimezone()
    for kind, url, label in gemtext_lines(markup, base):
        if kind == "heading" and not source:
            source = label
        if kind != "link" or urlsplit(url).scheme not in ("gemini", "http", "https"):
            continue
        date = today.isoformat()
        if not re.match(date + r"(?![0-9A-Za-z])", label):
            continue
        title = label[len(date):].lstrip(" :-–—\t") or url
        articles.append(Article(title, "", published, url, "", "", base))
    for article in articles:
        article.source = source or urlsplit(base).hostname
    return articles


def gemtext_body(markup, base):
    body = []
    for kind, url, label in gemtext_lines(markup, base):
        if (kind == "link" and urlsplit(url).scheme in ("gemini", "http", "https")
                and urlsplit(url).path.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))):
            body.append(ArticleImage(url, label))
        else:
            body.append(label or url)
    return body


class PageText(HTMLParser):
    """Collect readable text, preferring an article or main region on web pages."""

    blocks = {"p", "li", "div", "br", "blockquote", "h1", "h2", "h3", "section", "pre"}
    hidden = {"head", "script", "style", "noscript", "nav", "footer", "aside", "svg"}

    def __init__(self, base):
        super().__init__()
        self.base = base
        self.parts = []
        self.regions = {"main": [], "article": [], "p": []}
        self.active = set()
        self.suppressed = []

    def append(self, text):
        if not self.suppressed:
            self.parts.append(text)
            for region in self.active:
                self.regions[region].append(text)

    def handle_starttag(self, tag, attrs):
        if tag.rsplit(":", 1)[-1] == "img" and not self.suppressed:
            attrs = dict(attrs)
            src = attrs.get("src") or attrs.get("data-src")
            if src:
                try:
                    url = resolve(self.base, src)
                    if urlsplit(url).scheme in ("gemini", "http", "https") and urlsplit(url).hostname:
                        self.append(ArticleImage(url, attrs.get("alt") or ""))
                except ValueError:
                    pass
        if tag in self.hidden:
            self.suppressed.append(tag)
        if not self.suppressed and tag in self.regions:
            self.active.add(tag)
        if tag in self.blocks:
            self.append("\n")

    def handle_endtag(self, tag):
        if self.suppressed and tag == self.suppressed[-1]:
            self.suppressed.pop()
        if tag in self.blocks:
            self.append("\n")
        self.active.discard(tag)

    def handle_data(self, data):
        self.append(data)

    def paragraphs(self, web_page=False):
        parts = self.parts
        if web_page:
            parts = self.regions["article"] or self.regions["main"] or self.regions["p"]
        body = []
        pending = []
        def flush_text():
            for line in "".join(pending).splitlines():
                if line.strip():
                    body.append(" ".join(line.split()))
            pending.clear()

        for part in parts:
            if isinstance(part, str):
                pending.append(part)
                continue
            flush_text()
            body.append(part)
        flush_text()
        return body


def plain_text(markup, web_page=False, base=""):
    parser = PageText(base)
    parser.feed(markup)
    parser.close()
    return parser.paragraphs(web_page)


def tag_name(element):
    return element.tag.rsplit("}", 1)[-1]


def field(element, *names):
    for name in names:
        for child in element:
            if tag_name(child) == name:
                if len(child):
                    return (child.text or "") + "".join(
                        XML.tostring(part, encoding="unicode", method="html") for part in child
                    )
                return (child.text or "").strip()
    return ""


def publication(value):
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
        except (ValueError, OverflowError):
            return None
    try:
        return stamp.astimezone()
    except (ValueError, OverflowError, OSError):
        return None


def entry_url(entry, base):
    for child in entry:
        if tag_name(child) != "link" or child.get("rel", "alternate") != "alternate":
            continue
        value = child.get("href") or (child.text or "").strip()
        if value:
            url = urljoin(base, value)
            if http_url(url):
                return url
    return ""


def read_feed(url, today):
    payload, base, headers = fetch(url)
    if urlsplit(url).scheme == "gemini":
        return gemsub(decode(payload, headers), base, today)
    root = XML.fromstring(payload)
    kind = tag_name(root)
    if kind == "rss":
        root = next((child for child in root if tag_name(child) == "channel"), None)
        if root is None:
            raise ValueError("RSS feed has no channel")
    elif kind not in ("feed", "RDF"):
        raise ValueError("expected an RSS or Atom feed")
    channel = next((child for child in root if tag_name(child) == "channel"), root)
    source = field(channel, "title") or urlsplit(base).hostname
    articles = []
    for entry in root:
        if tag_name(entry) not in ("item", "entry"):
            continue
        published = publication(field(entry, "pubDate", "published", "date", "issued"))
        if published is None or published.date() != today:
            continue
        media = []
        for child in entry.iter():
            name = tag_name(child)
            if (name == "thumbnail" or child.get("medium") == "image"
                    or child.get("type", "").startswith("image/")):
                src = child.get("url") or child.get("href")
                if src:
                    media.append(ArticleImage(urljoin(base, src)))
        articles.append(Article(
            field(entry, "title") or "Untitled", source, published,
            entry_url(entry, base), field(entry, "encoded", "content"),
            field(entry, "description", "summary"), base, tuple(media),
        ))
    return articles


def diagnostic(url, error):
    # Feed URLs may carry a private subscription token.
    try:
        host = urlsplit(url).hostname or "feed"
    except ValueError:
        host = "feed"
    reason = getattr(error, "code", type(error).__name__)
    print(f"Feeds to Plucker: {host} ({reason}).", file=sys.stderr)


def load_feed(url, today):
    try:
        return read_feed(url, today)
    except (OSError, ValueError, XML.ParseError) as error:
        diagnostic(url, error)
        return []


def article_body(article):
    content = plain_text(article.content, base=article.url or article.base)
    if content:
        return content
    if article.url:
        try:
            payload, base, headers = fetch(article.url)
            mime = headers.get_content_type()
            if mime.startswith("image/"):
                return [ArticleImage(base, article.title)]
            markup = decode(payload, headers)
            if mime == "text/gemini":
                content = gemtext_body(markup, base)
            elif mime == "text/plain":
                content = markup.splitlines()
            else:
                content = plain_text(markup, web_page=True, base=base)
            if content:
                return content
        except (OSError, ValueError) as error:
            diagnostic(article.url, error)
    return plain_text(article.summary, base=article.url or article.base) or ["No article text was available."]


def load_image(url, deadline=None):
    try:
        if deadline is not None and time.monotonic() + 6 >= deadline:
            return None
        data, _, _ = fetch(url, timeout=4)
        formats = [(b"\xff\xd8\xff", "jpeg"), (b"\x89PNG\r\n\x1a\n", "png"),
                   (b"GIF87a", "gif"), (b"GIF89a", "gif")]
        fmt = next((name for signature, name in formats if data.startswith(signature)), None)
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            fmt = "webp"
        if not fmt:
            return None
        # Select a raster decoder explicitly. PBM uses Palm's MSB-first, black-is-one bits.
        command = ["magick", "-limit", "thread", "1", "-limit", "memory", "64MiB",
                   "-limit", "map", "0", "-limit", "disk", "0", fmt + ":-[0]",
                   "-auto-orient", "-background", "white", "-alpha", "remove",
                   "-resize", "160x160>", "-colorspace", "gray", "-dither", "FloydSteinberg",
                   "-remap", "pattern:gray50", "pbm:-"]
        pbm = subprocess.run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5, check=True).stdout
        magic, dimensions, pixels = pbm.split(b"\n", 2)
        width, height = map(int, dimensions.split())
        row = (width + 7) // 8
        stride = (row + 1) & ~1
        if magic != b"P4" or len(pixels) != height * row:
            raise ValueError("invalid bitmap")
        header = struct.pack(">4HBB6x", width, height, stride, 0, 1, 0)
        return header + b"".join(pixels[i:i+row].ljust(stride, b"\0")
                                 for i in range(0, len(pixels), row))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        diagnostic(url, error)
        return None


def palm_text(text):
    replacements = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"',
                                  "–": "-", "—": "--", "…": "...", "\x00": ""})
    return " ".join(text.translate(replacements).split()).encode("latin-1", "replace")


def link(title, target):
    return b"\0\x0a" + struct.pack(">H", target) + palm_text(title) + b"\0\x08"


def text_record(uid, paragraphs):
    body = b"".join(paragraphs)
    headers = b"".join(struct.pack(">HH", len(p), 1) for p in paragraphs)
    return struct.pack(">HHHBB", uid, len(paragraphs), len(body), 0, 0) + headers + body


def article_paragraphs(article, content, image_ids):
    paragraphs = [link("Contents", 2), palm_text(article.title)[:240],
                  palm_text(f"{article.source} | {article.published:%H:%M}")[:240]]
    if article.url:
        paragraphs.append(palm_text(article.url)[:512])
    remaining = 30000
    for paragraph in content:
        if isinstance(paragraph, ArticleImage):
            if paragraph.url in image_ids:
                remaining -= 8
                if remaining < 0:
                    return paragraphs + [b"[Article shortened for Palm OS.]"]
                paragraphs.append(b"\0\x1a" + struct.pack(">H", image_ids[paragraph.url]))
                continue
            paragraph = paragraph.alt
        for line in textwrap.wrap(paragraph[:30000], width=1500):
            encoded = palm_text(line)
            remaining -= len(encoded) + 4
            if remaining < 0:
                return paragraphs + [b"[Article shortened for Palm OS.]"]
            paragraphs.append(encoded)
    return paragraphs


def build_database(today, articles, bodies, deadline=None):
    index_count = max(1, (len(articles) + ARTICLES_PER_INDEX_PAGE - 1) // ARTICLES_PER_INDEX_PAGE)
    first_article = 2 + index_count
    # Non-compressed text records can use the DOC index version without a decoder.
    records = [struct.pack(">5H", 1, 1, 1, 0, 2)]
    for page in range(index_count):
        start = page * ARTICLES_PER_INDEX_PAGE
        end = start + ARTICLES_PER_INDEX_PAGE
        paragraphs = [palm_text(f"Feeds Today | {today:%Y-%m-%d}")]
        for index, article in enumerate(articles[start:end], start):
            label = palm_text(f"{article.title} ({article.source})")[:240].decode("latin-1")
            paragraphs.append(link(label, first_article + index))
        if not articles:
            paragraphs.append(b"No articles published today were available at this HotSync.")
        if page:
            paragraphs.append(link("Previous page", 1 + page))
        if page + 1 < index_count:
            paragraphs.append(link("Next page", 3 + page))
        records.append(text_record(2 + page, paragraphs))
    urls = dict.fromkeys(part.url for body in bodies for part in body if isinstance(part, ArticleImage))
    image_ids = {}
    images = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for url, bitmap in zip(urls, pool.map(lambda url: load_image(url, deadline), urls)):
            uid = first_article + len(articles) + len(images)
            if bitmap and uid <= 65535:
                image_ids[url] = uid
                images.append(struct.pack(">HHHBB", uid, 0, len(bitmap), 2, 0) + bitmap)
    for index, (article, content) in enumerate(zip(articles, bodies)):
        records.append(text_record(first_article + index, article_paragraphs(article, content, image_ids)))
    records.extend(images)

    timestamp = int(time.time()) + 2082844800  # Palm epoch starts in 1904.
    header = struct.pack(">32sHH6I8sIIH", DB_NAME, 0, 1, timestamp, timestamp,
                         0, 0, 0, 0, b"DataPlkr", 0, 0, len(records))
    offset = len(header) + 8 * len(records) + 2
    entries = []
    for uid, record in enumerate(records, 1):
        entries.append(struct.pack(">II", offset, uid))
        offset += len(record)
    return b"".join([header, *entries, b"\0\0", *records])


def main(config, output):
    global pin_dir
    pin_dir = Path(config).parent / "rss-plucker-gemini-pins"
    today = dt.datetime.now().astimezone().date()
    try:
        urls = list(dict.fromkeys(line.strip() for line in Path(config).read_text(
            encoding="utf-8").splitlines() if line.strip()))
    except FileNotFoundError:
        urls = []

    # Bound network waiting while J-Pilot has the handheld connection open.
    deadline = time.monotonic() + 42
    signal.alarm(45)
    with ThreadPoolExecutor(max_workers=12) as pool:
        articles = [item for feed in pool.map(lambda url: load_feed(url, today), urls)
                    for item in feed]
    articles.sort(key=lambda article: article.published, reverse=True)
    seen = set()
    edition = []
    for article in articles:
        key = article.url or (article.source, article.title, article.published)
        if key not in seen:
            seen.add(key)
            edition.append(article)
    if len(edition) > MAX_ARTICLES:
        print(f"Feeds to Plucker: keeping the newest {MAX_ARTICLES} entries.", file=sys.stderr)
        edition = edition[:MAX_ARTICLES]

    with ThreadPoolExecutor(max_workers=12) as pool:
        bodies = list(pool.map(article_body, edition))
    for article, body in zip(edition, bodies):
        inline = {part.url for part in body if isinstance(part, ArticleImage)}
        body.extend(image for image in dict.fromkeys(article.media) if image.url not in inline)
    Path(output).write_bytes(build_database(today, edition, bodies, deadline))
    signal.alarm(0)
    print(f"Feeds to Plucker: synced {len(edition)} article(s) for {today}.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python3 rss_plucker.py FEEDS.txt OUTPUT.pdb", file=sys.stderr)
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
