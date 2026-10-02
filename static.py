#!/usr/bin/env python3
"""matnden.github.io static site generator.

Pattern follows compileralchemy.github.io / pymug (jamstack + Jinja2):

    data/books/<slug>/meta.toml     book metadata
    data/books/<slug>/text.md       Arabic text
    data/books/<slug>/glosses.json  word-by-word English glosses
    templates/                      Jinja2 templates
    python static.py                ->  docs/   (GitHub Pages output)
    python static.py --server       ->  build + livereload preview

text.md format:

    # Section title

    plain prose paragraph
    (consecutive plain lines render as one paragraph, <br> separated)

    1 first passage text...
    2 next passage text...

Display model: every passage line is split into words; each word is a
column with a translation slot directly below it. `word|translation`
inline in text.md fills the slot (use _ for spaces); words without a
translation leave the slot empty — one line Arabic, one line English,
aligned word for word.
"""

import html
import logging
import os
import re
import sys
from os.path import join

import toml
from jamstack.api.template import base_context, generate
from livereload import Server

import settings

logging.basicConfig(level=logging.INFO, format="[build] %(message)s")
log = logging.getLogger("static")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _cps(*ranges):
    """String of characters from codepoint ranges/tuples (escape-proof)."""
    out = []
    for r in ranges:
        if isinstance(r, tuple):
            out.extend(chr(c) for c in range(r[0], r[1] + 1))
        else:
            out.append(chr(r))
    return "".join(out)


# harakat + Quranic annotation marks + tatweel (kept for future glossing)
HARAKAT = _cps((0x0610, 0x061A), (0x064B, 0x065F), 0x0670, (0x06D6, 0x06ED), 0x0640)
_HARAKAT_RE = re.compile("[" + re.escape(HARAKAT) + "]+")

# Arabic letters (used to tell words apart from bare punctuation tokens)
AR_LETTER_RE = re.compile("[" + _cps((0x0621, 0x064A)) + "]")

AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"

SECTION_RE = re.compile(r"^#\s+(.*)$")
PASSAGE_RE = re.compile(r"^(\d+)\s+(.*)$")
REF_RE = re.compile(r"\[[^\]]*\]")
AYAH_RE = re.compile(r"\}(.+?)\{")


def to_arabic_num(n: int) -> str:
    return "".join(AR_DIGITS[int(d)] for d in str(n))


def strip_harakat(s: str) -> str:
    return _HARAKAT_RE.sub("", s)


def norm_word(s: str) -> str:
    """Normalised form for gloss matching: no harakat, no edge punctuation."""
    s = strip_harakat(s)
    return re.sub(r"^[^\w]+|[^\w]+$", "", s, flags=re.UNICODE)


# ---------------------------------------------------------------------------
# parse data/books/<slug>/text.md
# ---------------------------------------------------------------------------

def parse_book_text(text: str):
    """-> list of sections: {"title": str, "blocks": [block, ...]}"""
    sections = []
    current = None
    prose_buf = []

    def flush_prose():
        nonlocal prose_buf
        if prose_buf and current is not None:
            current["blocks"].append({"type": "prose", "lines": prose_buf})
        prose_buf = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush_prose()
            continue
        m = SECTION_RE.match(line)
        if m:
            flush_prose()
            current = {"title": m.group(1).strip(), "blocks": []}
            sections.append(current)
            continue
        if current is None:
            current = {"title": "", "blocks": []}
            sections.append(current)
        m = PASSAGE_RE.match(line)
        if m:
            flush_prose()
            current["blocks"].append(
                {"type": "passage", "num": int(m.group(1)), "text": m.group(2).strip()}
            )
            continue
        prose_buf.append(line)
    flush_prose()
    return sections


# ---------------------------------------------------------------------------
# render blocks -> html
# ---------------------------------------------------------------------------

def prose_html(lines) -> str:
    body = "<br>".join(html.escape(l) for l in lines)
    return f'<p class="prose">{body}</p>'


def _segments(text: str):
    """Yield (kind, content); kind in {"text", "ayah", "ref"}."""
    pos = 0
    while pos < len(text):
        m_ref = REF_RE.search(text, pos)
        m_ayah = AYAH_RE.search(text, pos)
        found = []
        if m_ref:
            found.append(("ref", m_ref))
        if m_ayah:
            found.append(("ayah", m_ayah))
        if not found:
            yield ("text", text[pos:])
            return
        kind, m = min(found, key=lambda kv: kv[1].start())
        if m.start() > pos:
            yield ("text", text[pos:m.start()])
        if kind == "ref":
            yield ("ref", m.group(0))
        else:
            yield ("ayah", m.group(1))
        pos = m.end()


def _word_html(token: str) -> str:
    """One Arabic word = one column, translation slot directly below.

    `word|translation` fills the slot (use _ for spaces in the
    translation); a plain word leaves it empty. `//` is the hemistich
    gap in poems — a wide blank between the two halves of a bayt.
    """
    if token == "//":
        return '<span class="hgap"></span>'
    if not AR_LETTER_RE.search(token):
        # bare punctuation stays inline instead of becoming a column
        return html.escape(token)
    word, sep, trans = token.partition("|")
    meaning = trans.replace("_", " ").strip() if sep else ""
    return (
        f'<span class="w"><span class="wt">{html.escape(word)}</span>'
        f'<span class="wg">{html.escape(meaning)}</span></span>'
    )


def _words_html(seg: str) -> str:
    return " ".join(_word_html(t) for t in seg.split())


def passage_html(num: int, text: str) -> str:
    segs = []
    for kind, content in _segments(text):
        if kind == "ref":
            inner = content[1:-1] if content.startswith("[") else content
            segs.append(f'<span class="ref">{html.escape(inner)}</span>')
        elif kind == "ayah":
            segs.append('<span class="ayah">' + _words_html(content) + "</span>")
        else:
            segs.append(_words_html(content))
    body = " ".join(segs)
    return (
        f'<p class="passage" id="p{num}">'
        f'<span class="pnum">{to_arabic_num(num)}</span>'
        f"{body}</p>"
    )


# ---------------------------------------------------------------------------
# load books
# ---------------------------------------------------------------------------

def load_books() -> list:
    books = []
    if not os.path.isdir(settings.BOOKS_DIR):
        return books

    for name in sorted(os.listdir(settings.BOOKS_DIR)):
        book_dir = join(settings.BOOKS_DIR, name)
        meta_path = join(book_dir, "meta.toml")
        text_path = join(book_dir, "text.md")
        if not (os.path.isfile(meta_path) and os.path.isfile(text_path)):
            continue

        with open(meta_path, encoding="utf-8") as f:
            meta = toml.load(f)

        slug = meta.get("slug", name)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            raise ValueError(f"invalid slug {slug!r} in {meta_path}")

        with open(text_path, encoding="utf-8") as f:
            sections = parse_book_text(f.read())

        passage_count = 0
        for sec in sections:
            for block in sec["blocks"]:
                if block["type"] == "prose":
                    block["html"] = prose_html(block["lines"])
                else:
                    passage_count += 1
                    block["html"] = passage_html(block["num"], block["text"])

        books.append(
            {
                "slug": slug,
                "title_ar": meta.get("title_ar", slug),
                "title_en": meta.get("title_en", slug),
                "author_ar": meta.get("author_ar", ""),
                "author_en": meta.get("author_en", ""),
                "summary": meta.get("summary", ""),
                "edition": meta.get("edition", ""),
                "sections": sections,
                "passage_count": passage_count,
            }
        )
    return books


# ---------------------------------------------------------------------------
# generate pages
# ---------------------------------------------------------------------------

def ensure_output_folder():
    os.makedirs(settings.OUTPUT_FOLDER, exist_ok=True)
    # tell GitHub Pages not to run Jekyll
    open(join(settings.OUTPUT_FOLDER, ".nojekyll"), "w").close()


def gen_home(books):
    context = base_context()
    context.update(
        {
            "settings": settings,
            "path": "",
            "books": books,
            "seo_title": f"{settings.SITE['name']} | {settings.SITE['tagline']}",
            "seo_description": settings.SITE["description"],
            "page_path": "",
            "og_type": "website",
            "repo_links": True,
        }
    )
    generate("index.html", join(settings.OUTPUT_FOLDER, "index.html"), **context)


def gen_book(book):
    slug = book["slug"]
    out_dir = join(settings.OUTPUT_FOLDER, "books", slug)
    os.makedirs(out_dir, exist_ok=True)

    context = base_context()
    context.update(
        {
            "settings": settings,
            "path": "../../",
            "book": book,
            "slug": slug,
            "seo_title": f"{book['title_en']} | {settings.SITE['name']}",
            "seo_description": book["summary"],
            "page_path": f"books/{slug}/",
            "og_type": "book",
            "contribute_url": f"{settings.REPO_EDIT_URL}/data/books/{slug}/text.md",
        }
    )
    generate("book.html", join(out_dir, "index.html"), **context)


def gen_seo(books):
    urls = ["/"] + [f"/books/{b['slug']}/" for b in books]

    with open(join(settings.OUTPUT_FOLDER, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nAllow: /\n\n")
        f.write(f"Sitemap: {settings.BASE_URL}/sitemap.xml\n")

    with open(join(settings.OUTPUT_FOLDER, "sitemap.txt"), "w", encoding="utf-8") as f:
        for url in urls:
            f.write(f"{settings.BASE_URL}{url}\n")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{html.escape(settings.BASE_URL + url)}</loc>")
        lines.append("  </url>")
    lines.append("</urlset>")
    with open(join(settings.OUTPUT_FOLDER, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(args):
    def gen():
        ensure_output_folder()
        books = load_books()
        gen_home(books)
        for book in books:
            gen_book(book)
        gen_seo(books)

        passages = sum(b["passage_count"] for b in books)
        pages = 2 + len(books)
        log.info("pages: %d  books: %d  passages: %d", pages, len(books), passages)
        log.info("output: %s", settings.OUTPUT_FOLDER)

    if len(args) > 1 and args[1] == "--server":
        gen()  # build once before serving
        server = Server()
        for watch_path in ("data", "templates", join(settings.OUTPUT_FOLDER, "style.css"), "static.py", "settings.py"):
            server.watch(watch_path, gen, delay=1)
        log.info("serving %s at http://127.0.0.1:5500/", settings.OUTPUT_FOLDER)
        server.serve(root=settings.OUTPUT_FOLDER, port=5500, host="127.0.0.1")
    else:
        gen()


if __name__ == "__main__":
    main(sys.argv)
