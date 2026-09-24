"""How much of the client/driver screen text in the stage-2 client goes through the dictionary - measured.

The dictionary (`mobile-app/src/i18n/messages.ts`) holds every sentence in Uzbek and Russian. A screen string that
is still written as an Uzbek literal in a component cannot follow the language switch, so the switch stays hidden
until almost nothing is left (wave cards: a half-translated UI is worse than one honest language). This script
counts both sides so that "almost nothing" is a number.

Scope - the files a client or a driver reads (staff screens stay Uzbek and are out of scope):

* `mobile-app/src/app/ConnectedApp.tsx`
* every non-test `.tsx` in `mobile-app/src/app/v2/`
* every non-test `.tsx` under `mobile-app/src/components/`
* every other non-test `.tsx` directly in `mobile-app/src/app/` and `mobile-app/src/app/ui/` that is not a staff
  screen (`Admin*.tsx` is excluded)
* the pure `.ts` helpers in `mobile-app/src/app/` whose strings those screens render (`promo.ts`, `tripIntent.ts`,
  `auction.ts`, ...): a label built in a helper reaches the reader just like one written in JSX. Staff-only helpers
  (`admin*.ts`, `finance.ts`) are excluded with the staff screens.

Heuristic (read-only, no dependencies, no TypeScript parser - so it is an estimate with known edges):

1. Comments are removed and every string literal (`"..."`, `'...'`, template literals with their `${...}`
   replaced by a placeholder) is collected with its line number.
2. A literal is **user-visible Uzbek** when, after dropping placeholders, it contains a letter and either has two
   or more words, or is a single capitalised word, or contains an Uzbek apostrophe inside a word (`o'`, `g'`,
   `e'lon`). Excluded as code: import paths; `className=`/`key=`/`type=`/`id=`/`name=`/`role=`/`href=`/`src=`/
   `inputMode=`/`autoComplete=`/`variant=`/`tone=`/`size=`/`icon=`/`data-*=`/`aria-*=` values except
   `aria-label=`; Tailwind class lists; URLs and paths; MIME types; dotted keys (`a.b.c` - that is a dictionary
   key); identifiers (`snake_case`, `camelCase`, `kebab-case`, `SCREAMING_CASE`); CSS values (`var(--x)`,
   `color-mix(...)`, `12px`); English HTTP header names; regex literals; literals in `console.*` lines, `case "x":`
   labels and `=== "x"` / `!== "x"` comparisons (enum values); Cyrillic-only literals (already Russian, e.g. the
   language picker's own label); and lines under an `// i18n-ignore` pragma - reserved for data that looks like
   prose but is matched rather than read (city search aliases).
3. **JSX text** (prose between tags) is found per line after blanking strings, comments, `{...}` expressions and
   `<...>` tags on that line: what remains counts when it reads as prose by the same rule as (2). Lines that start
   with a JS/TS keyword or look like `prop: type` are skipped.
4. **Translated** strings are the call sites of `translate(`, `translateDynamic(` and a `useT()` translator `t(`
   in the same files. A helper that translates internally (e.g. `inboxTitle`) is not counted - the percentage is
   therefore a lower bound on what the reader actually sees translated.

Percentage = translated / (translated + untranslated).

Usage::

    py scripts/i18n_coverage.py            # summary
    py scripts/i18n_coverage.py --list     # plus every remaining literal as file:line
    py scripts/i18n_coverage.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "mobile-app" / "src"

PLACEHOLDER = "\u0000"


def target_files() -> list[Path]:
    files: set[Path] = {SRC / "app" / "ConnectedApp.tsx"}
    for directory in (SRC / "app", SRC / "app" / "ui", SRC / "app" / "v2"):
        files.update(p for p in directory.glob("*.tsx"))
    files.update(SRC.joinpath("components").rglob("*.tsx"))
    files.update(p for p in (SRC / "app").glob("*.ts") if p.name not in STAFF_ONLY_HELPERS)
    return sorted(
        p
        for p in files
        if p.is_file()
        and ".test." not in p.name
        and not p.name.lower().startswith("admin")
        and p.name != "App.tsx"
    )


#: Helpers only staff screens import (`AdminFinancePanel.tsx`); staff copy stays Uzbek and is out of scope.
STAFF_ONLY_HELPERS = {"finance.ts"}


# --- lexing -----------------------------------------------------------------------------------------------------


def lex(source: str) -> tuple[str, list[tuple[int, int, str, str]]]:
    """Return the source with comments and string contents blanked, plus the string literals found.

    Each literal is `(start, end, quote, text)`; `text` has template `${...}` parts replaced by PLACEHOLDER.
    Blanking keeps offsets and newlines, so line numbers stay true.
    """
    out = list(source)
    literals: list[tuple[int, int, str, str]] = []
    i, n = 0, len(source)
    prev_significant = ""

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = source.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
            continue
        if c == "/" and nxt == "*":
            j = source.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(i, j)
            i = j
            continue
        if c == "/" and (
            (prev_significant and prev_significant in "(,=:[!&|?{};")
            or source[max(0, i - 7) : i].rstrip().endswith("return")
        ):
            # A regex literal: skip it whole so a quote inside (`/[ʻ'`]/g`) does not open a string.
            j, in_class = i + 1, False
            while j < n and source[j] != "\n":
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                elif source[j] == "/" and not in_class:
                    break
                j += 1
            if j < n and source[j] == "/":
                blank(i + 1, j)
                i = j + 1
                prev_significant = "/"
                continue
        if c in "\"'":
            # An apostrophe inside JSX text ("e'lon") is not a string start: JSX text follows `>` or text.
            if c == "'" and prev_significant and (prev_significant.isalpha() or prev_significant == ">"):
                i += 1
                prev_significant = c
                continue
            j = i + 1
            buf = []
            while j < n and source[j] != c:
                if source[j] == "\\" and j + 1 < n:
                    buf.append(source[j : j + 2])
                    j += 2
                    continue
                if source[j] == "\n":  # unterminated: it was not a string (JSX text with a quote)
                    break
                buf.append(source[j])
                j += 1
            if j < n and source[j] == c:
                literals.append((i, j + 1, c, "".join(buf)))
                blank(i + 1, j)
                i = j + 1
                prev_significant = c
                continue
            i += 1
            continue
        if c == "`":
            j = i + 1
            buf = []
            while j < n and source[j] != "`":
                if source[j] == "\\" and j + 1 < n:
                    buf.append(source[j : j + 2])
                    j += 2
                    continue
                if source[j] == "$" and j + 1 < n and source[j + 1] == "{":
                    depth, k = 1, j + 2
                    while k < n and depth:
                        if source[k] == "{":
                            depth += 1
                        elif source[k] == "}":
                            depth -= 1
                        k += 1
                    buf.append(PLACEHOLDER)
                    j = k
                    continue
                buf.append(source[j])
                j += 1
            literals.append((i, j + 1, "`", "".join(buf)))
            blank(i + 1, j)
            i = j + 1
            prev_significant = "`"
            continue
        if not c.isspace():
            prev_significant = c
        i += 1
    return "".join(out), literals


# --- classification ---------------------------------------------------------------------------------------------

NON_UI_ATTRS = re.compile(
    r"\b(?:className|key|type|id|name|role|href|src|inputMode|autoComplete|variant|tone|size|icon|method|"
    r"accept|capture|target|rel|htmlFor|mode|kind|status|side|align|data-[\w-]+|aria-(?!label)[\w-]+)\s*=\s*\{?\s*$"
)
TAILWIND_WORDS = {
    "flex", "grid", "hidden", "block", "inline", "relative", "absolute", "fixed", "sticky", "truncate", "italic",
    "underline", "uppercase", "lowercase", "capitalize", "shadow", "rounded", "border", "transition", "grow",
    "shrink", "container", "contents", "static", "invisible", "visible", "antialiased", "sr-only", "group", "peer",
}
HEADERS = {"Content-Type", "Authorization", "Idempotency-Key", "Accept", "Bearer"}
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
LATIN = re.compile(r"[A-Za-z]")
UZ_APOSTROPHE = re.compile(r"[A-Za-z][‘’ʻʼ'][A-Za-z]")
IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*(?:[-.:/][\w$]+)*$")
CAPITALISED_WORD = re.compile(r"^[A-Z][a-z‘’ʻʼ']+[.!?:…]*$")
KEY_LIKE = re.compile(r"^[a-z][\w]*(?:\.[\w-]+)+$")


def is_class_list(text: str) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    return all(
        re.fullmatch(r"[a-z0-9:/\[\]\.\-_%#()!,>&*~+=]+", t) and ("-" in t or ":" in t or t in TAILWIND_WORDS or t.isdigit())
        for t in tokens
    )


def reads_as_prose(text: str) -> bool:
    bare = text.replace(PLACEHOLDER, " ").strip()
    if not LATIN.search(bare):
        return False
    if CYRILLIC.search(bare) and not LATIN.search(re.sub(r"[Ѐ-ӿ]+", "", bare)):
        return False
    if bare in HEADERS or "://" in bare or bare.startswith(("/", "./", "#", "http", "data:", "image/", "application/")):
        return False
    if "var(--" in bare or "color-mix(" in bare or re.search(r"\d(?:px|%|deg|fr)\b|:\s*[\w#-]+;|\brepeat\(", bare):
        return False  # a CSS value, not prose
    if KEY_LIKE.match(text.replace(PLACEHOLDER, "x").strip()):  # `notification.${code}.title` is a key too
        return False
    if is_class_list(bare):
        return False
    words = re.findall(r"[A-Za-z‘’ʻʼ']+", bare)
    if not words:
        return False
    if len(bare.split()) >= 2 and len(words) >= 2:
        # Two identifiers with a space are rare; two lowercase English-ish tokens like "max-age=0" are handled above.
        return True
    if UZ_APOSTROPHE.search(bare):
        return True
    if CAPITALISED_WORD.match(bare) and not bare.isupper():
        return True
    if IDENTIFIER.match(bare):
        return False
    # Single token with punctuation, e.g. "Yuborilmoqda..." or "so'm".
    return bool(re.match(r"^[A-Z][a-z]", bare))


JS_LINE_START = re.compile(
    r"^\s*(?:import|export|const|let|var|function|return|if|else|for|while|switch|case|default|type|interface|"
    r"await|throw|try|catch|finally|new|async|break|continue|do|yield|typeof|void|delete|in|of|as|from|enum|"
    r"declare|readonly|public|private|protected|static|extends|implements)\b"
)


def jsx_text_segments(blanked_line: str) -> list[str]:
    """Prose left on a blanked line once tags and expressions are removed."""
    line = blanked_line
    # remove {...} (innermost first, repeatedly) and <...> tags
    for _ in range(6):
        line2 = re.sub(r"\{[^{}]*\}", " ", line)
        if line2 == line:
            break
        line = line2
    line = re.sub(r"</?[A-Za-z][^<>]*?/?>", " ", line)
    line = re.sub(r"<>|</>", " ", line)
    stripped = line.strip()
    if not stripped:
        return []
    if JS_LINE_START.match(stripped):
        return []
    if re.match(r"^[a-z_$][\w$]*\??\s*[:(=]", stripped):  # prop: type, call(, assignment
        return []
    if re.search(r"[;=(){}\[\]<>|&]|=>|\?\.|\.\w+\(", stripped):
        return []
    if stripped.endswith((",", "(", "[", "{", "=>")) or stripped.startswith(("}", ")", "]", ".", "?", ":", "*", "+", "-", "|", "&", "!")):
        return []
    return [stripped]


def analyse(path: Path) -> tuple[int, list[tuple[int, str]]]:
    source = path.read_text(encoding="utf-8")
    blanked, literals = lex(source)
    line_starts = [0]
    for m in re.finditer("\n", source):
        line_starts.append(m.end())

    def line_of(offset: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    translated = len(re.findall(r"\b(?:translate|translateDynamic)\s*\(", blanked)) + len(
        re.findall(r"(?<![\w.$])t\s*\(\s*[\"'`]", source)
    )
    # translate( appears once in the import line as a name, not a call - `import { translate }` has no `(`.

    found: list[tuple[int, str]] = []
    lines = source.split("\n")
    for start, end, quote, text in literals:
        line_no = line_of(start)
        line_text = lines[line_no - 1]
        before = blanked[max(0, start - 80) : start]
        after = blanked[end : end + 6]
        if re.search(r"\b(?:import|from)\s*$", before) or re.match(r"^\s*(?:import|export)\b.*\bfrom\b", line_text):
            continue
        if "console." in line_text:
            continue
        if NON_UI_ATTRS.search(before):
            continue
        if re.search(r"\bcase\s*$", before) or re.search(r"[!=]==?\s*$", before) or re.match(r"^\s*[!=]==?", after):
            continue
        if re.search(r"\b(?:translate|translateDynamic|t)\s*\(\s*$", before):
            continue
        if re.match(r"^\s*:", after) and re.search(r"[{,]\s*$", before):  # object key "foo":
            continue
        if re.search(r"\b(?:getItem|setItem|removeItem|querySelector|getElementById|addEventListener|startsWith|endsWith|includes|split|join|replace|test|match|padStart|toLocaleString|toLocaleDateString|toLocaleTimeString|Intl\.\w+)\s*\(\s*[^()]*$", before):
            continue
        if reads_as_prose(text):
            found.append((line_no, text.replace(PLACEHOLDER, "${…}")))

    blanked_lines = blanked.split("\n")
    for index, blanked_line in enumerate(blanked_lines):
        for segment in jsx_text_segments(blanked_line):
            if reads_as_prose(segment) and len(re.findall(r"[A-Za-z']{2,}", segment)) >= 1:
                # Skip segments that are only TS types or keywords left over from multi-line constructs.
                if re.fullmatch(r"[A-Za-z_$][\w$]*", segment) and not segment[:1].isupper():
                    continue
                found.append((index + 1, segment))
    ignored = ignored_lines(lines)
    found = [item for item in found if item[0] not in ignored]
    found.sort()
    return translated, found


def ignored_lines(lines: list[str]) -> set[int]:
    """Lines under an `i18n-ignore` pragma: data that looks like prose but is matched, not read (search aliases).

    `// i18n-ignore` covers its own line and the next one; `// i18n-ignore-start` ... `// i18n-ignore-end` a block.
    """
    ignored: set[int] = set()
    inside = False
    for number, text in enumerate(lines, start=1):
        if "i18n-ignore-start" in text:
            inside = True
        if inside:
            ignored.add(number)
        if "i18n-ignore-end" in text:
            inside = False
        elif "i18n-ignore" in text and "i18n-ignore-start" not in text:
            ignored.update({number, number + 1})
    return ignored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--list", action="store_true", help="print every remaining literal as file:line")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    per_file = []
    total_translated = total_untranslated = 0
    for path in target_files():
        translated, found = analyse(path)
        total_translated += translated
        total_untranslated += len(found)
        per_file.append((path, translated, found))

    total = total_translated + total_untranslated
    percent = (100.0 * total_translated / total) if total else 100.0
    if args.json:
        print(
            json.dumps(
                {
                    "total": total,
                    "translated": total_translated,
                    "untranslated": total_untranslated,
                    "percent": round(percent, 1),
                    "files": {
                        str(p.relative_to(ROOT)).replace("\\", "/"): {
                            "translated": t,
                            "untranslated": [{"line": ln, "text": tx} for ln, tx in f],
                        }
                        for p, t, f in per_file
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    out = sys.stdout
    try:
        out.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    print(f"{'file':60} {'translated':>10} {'literal':>8}")
    for path, translated, found in per_file:
        print(f"{str(path.relative_to(SRC)).replace(chr(92), '/'):60} {translated:>10} {len(found):>8}")
    print()
    print(f"total user-visible strings: {total}")
    print(f"translated:                 {total_translated}")
    print(f"untranslated:               {total_untranslated}")
    print(f"percentage:                 {percent:.1f}%")
    if args.list:
        print()
        for path, _translated, found in per_file:
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            for line_no, text in found:
                print(f"{rel}:{line_no}: {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
