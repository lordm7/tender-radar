"""Turn a saved Etimad page (File > Save as, .html) into plain text.

The saved page has the same cards as a copy-paste, wrapped in HTML. We keep only
the visible text, one block element per line, so `parse_etimad_text` can read it.
Uses only the standard library's HTML parser.
"""

from __future__ import annotations

from html.parser import HTMLParser

_BLOCK_TAGS = {
    "address", "article", "aside", "br", "dd", "div", "dl", "dt", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "section", "table", "tbody",
    "td", "th", "thead", "tr", "ul",
}
_HIDDEN_TAGS = {"script", "style", "noscript", "template", "head"}


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _HIDDEN_TAGS:
            self.hidden_depth += 1
        else:  # inline tags (<span>, <b>…) still separate words: "label</span><span>value"
            self.parts.append("\n" if tag in _BLOCK_TAGS else " ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        else:
            self.parts.append("\n" if tag in _BLOCK_TAGS else " ")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Visible text of an HTML page, one block per line, blank lines removed."""
    collector = _TextCollector()
    collector.feed(html)
    collector.close()
    lines = (" ".join(line.split()) for line in "".join(collector.parts).splitlines())
    return "\n".join(line for line in lines if line)
