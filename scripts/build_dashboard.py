#!/usr/bin/env python3
"""Build a self-contained static dashboard bundle from dashboard/ + dashboard-data/ + wiki/."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_SRC = PROJECT_ROOT / "dashboard"
DATA_SRC = PROJECT_ROOT / "dashboard-data"
DIST_DIR = PROJECT_ROOT / "dashboard-dist"
WIKI_DIR = PROJECT_ROOT / "wiki"


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(src: Path, dst: Path) -> int:
    count = 0
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        count += 1
    return count


def _md_to_html(md: str) -> str:
    """Convert simple markdown to HTML (no external deps)."""
    html_lines = []
    lines = md.splitlines()
    in_table = False
    in_list = False
    i = 0

    def inline(text: str) -> str:
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        # Avoid treating intra-word underscores like `ev_news` as emphasis.
        text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<em>\1</em>', text)
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
        return text

    while i < len(lines):
        line = lines[i]

        # headings
        if line.startswith('### '):
            if in_list: html_lines.append('</ul>'); in_list = False
            if in_table: html_lines.append('</table>'); in_table = False
            html_lines.append(f'<h3>{inline(line[4:])}</h3>')
        elif line.startswith('## '):
            if in_list: html_lines.append('</ul>'); in_list = False
            if in_table: html_lines.append('</table>'); in_table = False
            html_lines.append(f'<h2>{inline(line[3:])}</h2>')
        elif line.startswith('# '):
            if in_list: html_lines.append('</ul>'); in_list = False
            if in_table: html_lines.append('</table>'); in_table = False
            html_lines.append(f'<h1>{inline(line[2:])}</h1>')

        # table rows
        elif line.startswith('|'):
            cells = [c.strip() for c in line.strip('|').split('|')]
            # skip separator rows
            if all(re.match(r'^[-: ]+$', c) for c in cells):
                i += 1
                continue
            if not in_table:
                html_lines.append('<table>')
                in_table = True
                tag = 'th'
            else:
                tag = 'td'
            html_lines.append('<tr>' + ''.join(f'<{tag}>{inline(c)}</{tag}>' for c in cells) + '</tr>')

        # list items
        elif line.startswith('- ') or line.startswith('* '):
            if in_table: html_lines.append('</table>'); in_table = False
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            html_lines.append(f'<li>{inline(line[2:])}</li>')

        # blank line
        elif line.strip() == '':
            if in_list: html_lines.append('</ul>'); in_list = False
            if in_table: html_lines.append('</table>'); in_table = False
            html_lines.append('')

        # paragraph
        else:
            if in_list: html_lines.append('</ul>'); in_list = False
            if in_table: html_lines.append('</table>'); in_table = False
            html_lines.append(f'<p>{inline(line)}</p>')

        i += 1

    if in_list: html_lines.append('</ul>')
    if in_table: html_lines.append('</table>')
    return '\n'.join(html_lines)


SECTION_ORDER = ['meta', 'strategies', 'patterns']
SECTION_LABELS = {'meta': 'Meta', 'strategies': 'Strategies', 'patterns': 'Patterns'}


def build_wiki_json(dest: Path) -> int:
    """Convert wiki markdown files to JSON for the dashboard."""
    if not WIKI_DIR.exists():
        return 0

    pages = []
    for section in SECTION_ORDER:
        section_dir = WIKI_DIR / section
        if not section_dir.exists():
            continue
        for md_file in sorted(section_dir.glob("*.md")):
            if md_file.name.startswith('.'):
                continue
            text = md_file.read_text()
            # Extract title from first # heading
            title_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
            title = title_match.group(1) if title_match else md_file.stem
            pages.append({
                "section": section,
                "section_label": SECTION_LABELS.get(section, section),
                "slug": md_file.stem,
                "title": title,
                "html": _md_to_html(text),
            })

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(pages, ensure_ascii=False, indent=2))
    return len(pages)


def main() -> None:
    if not DASHBOARD_SRC.exists():
        raise SystemExit("dashboard/ not found")
    if not DATA_SRC.exists():
        raise SystemExit("dashboard-data/ not found; run scripts/export_dashboard_data.py first")

    reset_dir(DIST_DIR)
    site_count = copy_tree(DASHBOARD_SRC, DIST_DIR)
    data_count = copy_tree(DATA_SRC, DIST_DIR / "data")
    wiki_count = build_wiki_json(DIST_DIR / "data" / "wiki.json")

    print("Built dashboard bundle:")
    print(f"- site files: {site_count}")
    print(f"- data files: {data_count}")
    print(f"- wiki pages: {wiki_count}")
    print(f"- output: {DIST_DIR}")
    print("Open locally with a static server rooted at dashboard-dist/.")


if __name__ == "__main__":
    main()
