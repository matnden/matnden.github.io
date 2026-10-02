# matnden.github.io

Read Islamic Classics Easily

Static site for reading Islamic classics in Arabic. Each passage line is
split into word columns with a reserved space under every word - ready for
English translations to sit directly below the word they belong to.

## Build

```bash
pip install -r requirements.txt   # jamstack, livereload
python static.py                  # generates docs/ (GitHub Pages serves from here)
```

## Preview with auto-reload

```bash
python static.py --server         # http://127.0.0.1:5500/
```

## Source layout

```
data/books/<slug>/meta.toml   book metadata (title, author, summary, edition)
data/books/<slug>/text.md     the Arabic text:
                                # Section title
                                plain prose lines (paragraphs)
                                1 numbered passage
                                word|translation fills a word's slot
                                // a wide gap (poem hemistichs)
                                2 numbered passage
                                --- on its own line: horizontal rule
templates/                    Jinja2 templates (index.html, book.html, sections/)
docs/style.css                stylesheet - the source file lives in docs/ itself
static.py                     generator (jamstack + Jinja2), settings.py = config
```

Add a book: create `data/books/<slug>/` with `meta.toml` + `text.md`,
run `python static.py` - the front page picks it up automatically.

## Contributing translations

Every Arabic word on the page has a translation slot right below it.
The slot is empty until someone fills it - to translate a word, add
`|translation` directly after it in `data/books/<slug>/text.md`:

```text
1 نقول في توحيد|oneness الله معتقدين بتوفيق الله: إن الله واحد لا شريك|partner له.
```

That line renders as:

```text
نقول   في   توحيد    الله  معتقدين ...  شريك
              oneness              ...  partner
```

If this is not displayed correctly it's `arabic|english arabic arabic|english`, just add a pipe and add the translation.

Each book page has a **Contribute** button in its toolbar - it opens
that book's `text.md` in the GitHub editor, so the fastest path is:
click, edit, commit.

Rules:

- The `|` goes straight after the word it belongs to - no spaces around it.
- Use `_` instead of spaces for multi-word meanings:
  `محيي|giver_of_life` shows as "giver of life".
- Words without `|` show an empty slot - translate the words you find
  difficult and leave the rest; that is the point.
- Quranic verses (between `}` and `{`), verse references and plain prose
  all work the same way.
- Rebuild (`python static.py`) and eyeball your line before submitting.

Good candidates: theological and classical vocabulary - توحيد، مشيئة،
رؤية، خواتيم، ذريعة، اجتهاد، تأويل - rather than everyday words.
