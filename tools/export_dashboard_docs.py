"""Write docs/dashboards/<dashboard>/text-panels.txt: the text panels of each v3 dashboard as plain text.

    python3 tools/export_dashboard_docs.py

Reads the generated v3/dashboards/*.yaml (run tools/build_v3_content.py first). Screenshots in the same
folders are taken separately from a lab, with object names redacted (see docs/dashboards/README.md).
"""
import glob, html, os, re
from html.parser import HTMLParser
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK = {"p", "div", "h3", "h4", "ol", "ul", "li", "br"}


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.lists, self.head = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("ol", "ul"):
            self.lists.append([tag, 0])
        elif tag == "li":
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            self.out.append("\n" + "   " * len(self.lists) + (f"{kind[1]}. " if kind[0] == "ol" else "- "))
        elif tag in ("h3", "h4"):
            self.out.append("\n\n"); self.head = len(self.out)
        elif tag in BLOCK:
            self.out.append("\n" if tag == "br" else "\n\n")

    def handle_endtag(self, tag):
        if tag in ("ol", "ul") and self.lists:
            self.lists.pop(); self.out.append("\n")
        elif tag in ("h3", "h4") and self.head is not None:
            title = "".join(self.out[self.head:]).strip()
            self.out.append("\n" + ("=" if tag == "h3" else "-") * len(title) + "\n")
            self.head = None

    def handle_data(self, data):
        self.out.append(re.sub(r"\s+", " ", data))


def to_text(fragment):
    t = Text(); t.feed(fragment)
    s = html.unescape("".join(t.out))
    s = "\n".join(line.strip() if not line.lstrip().startswith(("-", *"123456789")) else line.rstrip()
                  for line in s.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", s).strip() + "\n"


def main():
    for path in sorted(glob.glob(os.path.join(ROOT, "v3", "dashboards", "*.yaml"))):
        d = yaml.safe_load(open(path))
        slug = re.sub(r"[^a-z0-9]+", "-", d["name"].lower()).strip("-")
        out_dir = os.path.join(ROOT, "docs", "dashboards", slug)
        os.makedirs(out_dir, exist_ok=True)
        full = d.get("name_path", "") + " › " + d["name"] if d.get("name_path") else d["name"]
        parts = [f"{full}: dashboard text panels", "Generated from " + os.path.relpath(path, ROOT)
                 + " by tools/export_dashboard_docs.py. Do not edit by hand.", ""]
        for w in d["widgets"]:
            if w.get("type") == "TextDisplay":
                bar = "#" * (len(w["title"]) + 8)
                parts += [bar, f"### {w['title']} ###", bar, "", to_text(w["html"]), ""]
        open(os.path.join(out_dir, "text-panels.txt"), "w").write("\n".join(parts).rstrip() + "\n")
        print("wrote", os.path.relpath(os.path.join(out_dir, "text-panels.txt"), ROOT))


if __name__ == "__main__":
    main()
