#!/usr/bin/env python3
"""Every word in a help panel must be legible in EVERY Operations theme.

    python3 tools/test_help_contrast.py <path/to/MemoryTierAdvanced_X.Y.Z-rc.N.pak>

Copied from the netstats pack (tools/test_help_contrast.py), which is where this test and its
probes were proven; only panels() differs. It reads the help panels out of the SHIPPED PAK,
not the source tree, per the shared RELEASING.md section 2.

This panel has now regressed three times, each time shipping to Nick:

  1. color:#ffffff on every element      -- invisible on a LIGHT dashboard.
  2. no colour at all, inherit the theme -- invisible on a DARK one, because
     the TextDisplay widget hands its content no usable foreground and
     unstyled text falls back to black.
  3. correct colours, but applied by a regex that only matched BARE tags, so
     a fragment's own <p style="margin-left:12px"> kept no colour at all.

No fixed foreground can fix this. Clearing 4.5:1 on Operations' light page
(#ffffff) requires relative luminance <= 0.1833; clearing it on the dark page
(#1b1b1b) requires >= 0.2243. The ranges do not overlap -- the best any single
colour achieves balanced across both is about 4.15:1. That is arithmetic.

So the panel paints its OWN card and measures every colour against that card,
which makes contrast identical in every theme. This test holds that invariant:

  a. the panel declares its own background;
  b. EVERY text node carries an explicit colour (no inheritance anywhere);
  c. every colour used clears 4.5:1 against the card AND against the code-span
     surface that sits on top of it;
  d. nothing is muted with opacity, which is an unmeasured dimmer colour.

A failure here means the panel is unreadable on a real dashboard. Fix the
generator, do not relax the threshold.
"""
import html.parser
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "content", "dashboards")

MIN_RATIO = 4.5          # WCAG AA for body text at 13px
# Elements that cannot contain text. Everything else is checked, with NO
# allowlist: an earlier version of this test matched a fixed list of tags, so a
# fragment written with <strong> or <em> would have been both unstyled by the
# generator AND invisible to this check -- two silent failures that cancel into
# a clean pass. The vSAN pack shipped exactly that, as <code> and <i> nodes
# carrying no colour of their own.
VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col",
        "embed", "source", "track", "wbr"}
# Skipped because their contents are not rendered prose. `body` and `html` are
# deliberately NOT here: editor_html() extracts the fragment's body INNER html
# and wraps it in its own div, so neither should ever reach a panel -- and if
# one ever does, its text would render and must be checked, not skipped.
SKIP = {"style", "script", "head", "title"}
EDITOR = re.compile(r'"editorData":\s*"((?:[^"\\]|\\.)*)"')
# Value parsing is its own failure surface, and these patterns used to read ONLY
# a bare hex. Everything else -- rgb(), a named colour, var(), a gradient -- came
# back as ABSENT, which happened to fail in the safe direction but for the wrong
# reason: a legitimate `color:white` was reported as "states no colour". A check
# that is right by accident does not stay right, because the next person makes it
# more accurate and the safety quietly evaporates.
#
# So values are now RESOLVED where that is well defined, and anything else is
# reported as UNRESOLVABLE and fails on its own terms. Never scored on a guess:
# a gradient or a translucent rgba has no single ratio, so taking one stop out of
# `linear-gradient(#2b3137,#ffffff)` would score a dark card for a panel that is
# white at the other end.
DECL = re.compile(r'(?<!-)(?<![\w-])(color|background|background-color)\s*:'
                  r'\s*([^;]+)')
NAMED = {"white": "#ffffff", "black": "#000000", "red": "#ff0000",
         "silver": "#c0c0c0", "gray": "#808080", "grey": "#808080",
         "whitesmoke": "#f5f5f5", "transparent": None}
class _Unresolvable:
    """A value IS set but has no single contrast ratio.

    A distinct class rather than a bare sentinel, because the vSAN session's
    equivalent used the string "?" and `UNRESOLVABLE = None` was then a
    one-line edit that silently made "unresolvable" equal to "absent" -- so an
    inherited colour was reported as unresolvable. Right for the wrong reason,
    inside the classifier itself.

    The reason-pinned probes DO catch that collapse here (two of them fire),
    but detected is weaker than impossible, so:

      - truthy, so it never behaves like an absent value in a boolean test;
      - not equal to None, so an `== None` comparison cannot confuse the two;
      - and `__set_name__`-free, with the identity guard below refusing a
        rebind to None at import time.

    This closes that one collapse. It does NOT make the reason pinning
    redundant: a refactor can still mislabel a reason without touching this
    class, which is what the "RIGHT FOR THE WRONG REASON" bucket is for.
    """

    __slots__ = ()

    def __bool__(self):
        return True

    def __eq__(self, other):
        return other is self

    def __hash__(self):
        return id(self)

    def __repr__(self):
        return "UNRESOLVABLE"


UNRESOLVABLE = _Unresolvable()

# Refuse the collapse rather than merely detecting it downstream. A raise and
# not an assert: `python -O` strips asserts, which would silently remove this
# guard -- the same shape of disappearing safety it exists to prevent.
if UNRESOLVABLE is None or not UNRESOLVABLE or UNRESOLVABLE == None:  # noqa: E711
    raise SystemExit("UNRESOLVABLE must stay distinct from, and truthy "
                     "unlike, an absent value -- collapsing the two reports "
                     "an inherited colour as unresolvable")


def resolve(value):
    """A hex string, None when absent, or UNRESOLVABLE.

    UNRESOLVABLE is not the same as absent: absent means the element inherits
    and must be flagged as leaning; unresolvable means a value IS set but has
    no single contrast ratio, which is a different fault with a different fix.
    """
    v = value.strip().lower()
    if not v:
        return None
    hexes = re.findall(r"#[0-9a-f]{3,6}\b", v)
    # A shorthand like `#2b3137 url(a.png)` resolves; two stops do not.
    if len(hexes) == 1 and "gradient" not in v:
        return hexes[0]
    if len(hexes) > 1 or "gradient" in v or "var(" in v:
        return UNRESOLVABLE
    m = re.fullmatch(r"rgb\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*\)", v)
    if m:
        return "#%02x%02x%02x" % tuple(int(g) for g in m.groups())
    if re.match(r"rgba?\(", v):
        return UNRESOLVABLE      # translucent over an unknown page
    if v in NAMED:
        return NAMED[v]
    return UNRESOLVABLE


def declared(style):
    """{property: resolved} for one style attribute. LAST declaration wins, as
    CSS does -- `.search()` took the first, so `color:#e9edf0;color:#2b3137`
    was scored on the colour the browser discards."""
    out = {}
    for prop, value in DECL.findall(style or ""):
        key = "background" if prop.startswith("background") else "color"
        out[key] = resolve(value)
    return out
# Entities that are punctuation, not words -- an em dash between two coloured
# runs needs no colour of its own.
PUNCT = {"&mdash;", "&bull;", "&middot;", "&ndash;", "&nbsp;", "-", "|"}


def luminance(hexcolour):
    h = hexcolour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    chan = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    chan = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in chan]
    return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]


def ratio(fg, bg):
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


class Panel(html.parser.HTMLParser):
    """Walk a panel and record, for every text node, the colour and background
    of the element that DIRECTLY encloses it.

    A stack rather than a regex, for two reasons a regex got wrong:

      - text following a void tag (`<br>`) belongs to the enclosing element,
        not to the void tag, and a regex attributes it to `<br>`;
      - `<b` matches the start of `<br`, so `<br>` was read as a `<b>` carrying
        the attribute `r`, which produced phantom failures.

    Leaning on an ancestor's colour counts as UNCOLOURED here even though it is
    valid CSS and renders correctly. That is deliberate: the inheritance hop is
    exactly what this editor has already broken once, in the release that set a
    colour on <p> only and left <code> and <i> to inherit it.
    """

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []          # [(tag, colour|None, background|None)]
        self.nodes = []          # [(tag, text, colour, nearest background)]
        self.wrapper = None      # (tag, colour, background) of the root element
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skipping += 1
            return
        style = dict(attrs).get("style") or ""
        decl = declared(style)
        frame = (tag, decl.get("color"), decl.get("background"))
        if self.wrapper is None and not self.stack:
            self.wrapper = frame
        if tag not in VOID:
            self.stack.append(frame)

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skipping = max(0, self.skipping - 1)
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_entityref(self, name):
        self.handle_data("&" + name + ";")

    def handle_charref(self, name):
        self.handle_data("&#" + name + ";")

    def handle_data(self, data):
        if self.skipping or not data.strip() or data.strip() in PUNCT:
            return
        if not self.stack:
            self.nodes.append(("(root)", data.strip(), None, None))
            return
        tag, colour, _ = self.stack[-1]
        background = next((f[2] for f in reversed(self.stack)
                           if f[2] is not None), None)
        self.nodes.append((tag, data.strip(), colour, background))


def panels():
    """Every help panel in every dashboard inside the pak named on the command line."""
    import zipfile
    out = []
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        return out
    with zipfile.ZipFile(sys.argv[1]) as pak:
        for name in sorted(pak.namelist()):
            if name.startswith("content/dashboards/") and name.endswith(".json"):
                body = pak.read(name).decode()
                for raw in EDITOR.findall(body):
                    out.append((name.split("/")[2], json.loads('"' + raw + '"')))
    return out


def check(doc):
    """Return (problems, stats) for one panel."""
    panel = Panel()
    panel.feed(doc)
    panel.close()
    problems = []

    # 1. The CARD is the OUTERMOST element's own background. It is not enough
    #    that some background exists somewhere: an earlier version of this test
    #    read the first background found anywhere in the document, which on a
    #    panel with no card at all was a code-span fill -- so the fixed-white
    #    panel that shipped and was unreadable on a light dashboard PASSED. The
    #    wrapper is what sits against the theme, and its padding and the gaps
    #    between its children show the page through regardless of what any
    #    inner fill scores.
    card = panel.wrapper[2] if panel.wrapper else None
    if card is UNRESOLVABLE:
        problems.append("the outermost element's background has no single "
                        "value (gradient, translucent or var()), so no "
                        "contrast ratio can be computed against it")
        return problems, {}
    if not card:
        problems.append("the outermost element declares NO background of its "
                        "own, so the text sits on the theme's page and its "
                        "contrast is the theme's decision, not ours")
        return problems, {}

    # 2. Every text node's OWN element carries a colour -- no inheritance.
    for tag, text, colour, _ in panel.nodes:
        if colour is UNRESOLVABLE:
            problems.append(f"<{tag}> sets a colour with no single value "
                            f"(gradient, translucent or var()), so its "
                            f"contrast cannot be computed: {text[:45]!r}")
        elif not colour:
            problems.append(f"<{tag}> states no colour of its own, so it "
                            f"leans on an ancestor (or on the theme, which "
                            f"gives black): {text[:55]!r}")

    # 3. Nothing is muted by opacity, which is an unmeasured dimmer colour.
    if "opacity:" in doc:
        problems.append("muting by opacity -- use a colour with a measured "
                        "ratio instead")

    # 4. Every colour clears MIN_RATIO against the background it actually sits
    #    on, falling back to the card.
    worst = None
    for tag, text, colour, background in panel.nodes:
        if not colour or colour is UNRESOLVABLE:
            continue
        if background is UNRESOLVABLE:
            problems.append(f"<{tag}> sits on a background with no single "
                            f"value, so its contrast cannot be computed: "
                            f"{text[:45]!r}")
            continue
        bg = background or card
        r = ratio(colour, bg)
        if worst is None or r < worst[0]:
            worst = (r, colour, bg)
        if r < MIN_RATIO:
            problems.append(f"{colour} on {bg} is {r:.2f}:1, under "
                            f"{MIN_RATIO}:1 (<{tag}>: {text[:40]!r})")

    stats = {"nodes": len(panel.nodes), "card": card,
             "colours": sorted({c for _, _, c, _ in panel.nodes
                                if c and c is not UNRESOLVABLE}),
             "worst": worst}
    return problems, stats


# ---------------------------------------------------------------------------
# Probes: the checker's OWN regression suite.
#
# These existed only as ad-hoc commands for most of their life, which is the
# exact failure this file keeps catching elsewhere -- behaviour that was
# verified once and never encoded, so the next edit is free to break it
# silently. Every entry below is a case that was actually got wrong at some
# point, by this checker or by the vSAN pack's equivalent.
#
# `want` is what a BROWSER would do, not what is convenient to implement.
#
# A fourth field, `because`, pins the REASON. Without it this suite could not
# tell a case that fails correctly from one that fails by luck: collapsing
# UNRESOLVABLE back into "absent" left every pass/fail verdict unchanged, so
# all 22 probes still agreed while the checker had lost the distinction between
# "this element inherits" and "this element sets a value with no computable
# ratio". A suite that only checks the verdict certifies the author's belief
# about the verdict, which is the failure this whole file exists to prevent.
CARD = 'background:#2b3137'
PROBES = [
    # (name, panel html, "pass" | "fail")
    ("plain hex",
     f'<div style="{CARD};color:#e9edf0"><p style="color:#e9edf0">x</p></div>',
     "pass"),
    # The three historical shipping failures.
    ("fixed white, no card of its own",
     '<div style="color:#ffffff"><p style="color:#ffffff">x</p></div>',
     "fail", "declares NO background"),
    ("inherit the theme, no colour anywhere",
     f'<div style="{CARD}"><p>x</p></div>',
     "fail", "states no colour of its own"),
    ("styled tag left uncoloured inside a good card",
     f'<div style="{CARD};color:#e9edf0"><p style="margin-left:12px">x</p></div>',
     "fail"),
    # Muting. House rule: never opacity, because it is a dimmer colour with no
    # measured ratio. Enforced on an ancestor as well as the declaring element.
    ("opacity on the text",
     f'<div style="{CARD};color:#e9edf0"><p style="color:#e9edf0;opacity:.35">x</p></div>',
     "fail"),
    ("opacity on an ancestor",
     f'<div style="{CARD};color:#e9edf0;opacity:.35"><p style="color:#e9edf0">x</p></div>',
     "fail", "opacity"),
    # Ratios, against the card and against a surface sitting on it.
    ("ink too dark against a correct card",
     f'<div style="{CARD};color:#e9edf0"><p style="color:#4a5560">x</p></div>',
     "fail"),
    ("named colour too dark",
     f'<div style="{CARD};color:#e9edf0"><p style="color:black">x</p></div>',
     "fail"),
    ("inner code surface, legible",
     f'<div style="{CARD};color:#e9edf0"><p style="color:#e9edf0">a'
     '<code style="background:#363d45;color:#8fd3ff">k</code></p></div>',
     "pass"),
    ("inner surface too light for its ink",
     f'<div style="{CARD};color:#e9edf0"><p style="color:#e9edf0">a'
     '<code style="background:#e9edf0;color:#8fd3ff">k</code></p></div>',
     "fail"),
    # Value resolution. These read as ABSENT before, which failed in the safe
    # direction for the wrong reason -- a legitimate colour reported missing.
    ("rgb() resolves",
     f'<div style="{CARD};color:rgb(233,237,240)">'
     '<p style="color:rgb(233,237,240)">x</p></div>',
     "pass"),
    ("named colour resolves",
     f'<div style="{CARD};color:white"><p style="color:white">x</p></div>',
     "pass"),
    ("hex + url() shorthand resolves",
     '<div style="background:#2b3137 url(a.png);color:#e9edf0">'
     '<p style="color:#e9edf0">x</p></div>',
     "pass"),
    # No single value -> no ratio. Scoring one stop of a gradient would credit
    # a dark card to a panel that is white at the other end.
    ("gradient background is unresolvable",
     '<div style="background:linear-gradient(#2b3137,#ffffff);color:#e9edf0">'
     '<p style="color:#e9edf0">x</p></div>',
     "fail", "no single value"),
    ("translucent rgba background is unresolvable",
     '<div style="background:rgba(43,49,55,.95);color:#e9edf0">'
     '<p style="color:#e9edf0">x</p></div>',
     "fail", "no single value"),
    # A colour function this resolver does not implement must FAIL LOUDLY,
    # not be treated as absent. hsl() and oklch() are perfectly valid CSS and
    # resolvable in principle; refusing them is honest, guessing is not, and
    # silently calling them absent credits an ancestor that may not exist.
    # Without this probe, collapsing the fallback to None went unnoticed.
    ("a colour function this resolver does not implement",
     f'<div style="{CARD};color:#e9edf0">'
     '<p style="color:hsl(210 10% 90%)">x</p></div>',
     "fail", "no single value"),
    ("var() colour is unresolvable",
     f'<div style="{CARD};color:var(--ink)"><p style="color:var(--ink)">x</p></div>',
     "fail", "no single value"),
    # Declaration order, twice. CSS applies the LAST declaration; .search()
    # took the first. The second case is the vSAN pack's find: the same bug
    # one level out, BETWEEN the two background properties rather than within
    # one of them, where a dark card overridden to white passed the gate.
    ("duplicate colour declarations, last wins",
     f'<div style="{CARD};color:#e9edf0">'
     '<p style="color:#e9edf0;color:#2b3137">x</p></div>',
     "fail", "1.00:1"),
    ("background then background-color, last wins",
     '<div style="background:#2b3137;background-color:#ffffff;color:#e9edf0">'
     '<p style="color:#e9edf0">x</p></div>',
     "fail", "1.18:1"),
    ("background-color then background, last wins",
     '<div style="background-color:#ffffff;background:#2b3137;color:#e9edf0">'
     '<p style="color:#e9edf0">x</p></div>',
     "pass"),
    # Structural. A void tag must not be credited with the text that follows
    # it, and prose must not escape the check by appearing somewhere the
    # walker used to skip.
    ("text after a void tag belongs to the parent",
     f'<div style="{CARD};color:#e9edf0">'
     '<p style="color:#e9edf0">a<br>b</p></div>',
     "pass"),
    ("prose leaking into a <body> is still checked",
     f'<div style="{CARD};color:#e9edf0"><p style="color:#e9edf0">fine</p>'
     '<body>stray prose</body></div>',
     "fail"),
    # An unknown tag must fail the AUDIT even though the generator never
    # emitted a style for it -- the generator's table and this checker must
    # not have holes that line up.
    ("unknown text-bearing tag",
     f'<div style="{CARD};color:#e9edf0"><small>injected</small></div>',
     "fail"),
]


def probe():
    """Run PROBES. Returns the number that misbehaved."""
    bad = 0
    for case in PROBES:
        name, doc, want = case[0], case[1], case[2]
        because = case[3] if len(case) > 3 else None
        problems, _ = check(doc)
        got = "fail" if problems else "pass"
        if got != want:
            bad += 1
            print(f"  PROBE WRONG  {name}: wanted {want}, got {got}")
            if problems:
                print(f"               {problems[0][:90]}")
        elif because and not any(because in p for p in problems):
            # Right verdict, wrong reason -- which is how a check rots without
            # any test noticing.
            bad += 1
            print(f"  PROBE RIGHT FOR THE WRONG REASON  {name}: "
                  f"expected {because!r}")
            print(f"               got {problems[0][:90]!r}")
    if not bad:
        pinned = sum(1 for c in PROBES if len(c) > 3)
        print(f"  {len(PROBES)} self-probes behave as intended "
              f"({pinned} with the reason pinned, not just the verdict)")
    return bad


def main():
    if probe():
        return 1
    found = panels()
    if not found:
        print("FAIL  no help panels found in the pak -- pass the .pak path")
        return 1

    failures = 0
    for name, doc in found:
        problems, stats = check(doc)
        if problems:
            failures += 1
            print(f"FAIL  {name}")
            seen = []
            for problem in problems:
                if problem not in seen:
                    seen.append(problem)
            for problem in seen[:10]:
                print(f"        {problem}")
            if len(seen) > 10:
                print(f"        ... and {len(seen) - 10} more distinct")
        else:
            r, colour, bg = stats["worst"]
            print(f"ok    {name}: {stats['nodes']} text nodes, each stating "
                  f"its own colour; {len(stats['colours'])} colours on "
                  f"{stats['card']}; worst {r:.2f}:1 ({colour} on {bg})")

    print(f"\n{len(found) - failures}/{len(found)} help panels legible in "
          f"every theme")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
