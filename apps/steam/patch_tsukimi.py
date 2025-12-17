#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable


TSUKIMI_RGB = {
    "focus": "205,177,149",
    "clientBG": "13,14,18",
    "header_dark": "13,14,18",
    "online": "138,159,186",
    "ingame": "138,154,128",
    "offline": "184,179,170",
    "golden": "229,213,184",
    "textentry": "13,14,18",
    "frameBorder": "37,42,54",
    "bgGameList": "10,11,15",
    "white03": "240,235,229,0.03",
    "white05": "240,235,229,0.05",
    "white08": "240,235,229,0.08",
    "white10": "240,235,229,0.10",
    "white12": "240,235,229,0.12",
    "white20": "240,235,229,0.20",
    "white24": "240,235,229,0.24",
    "white25": "240,235,229,0.25",
    "white35": "240,235,229,0.35",
    "white45": "240,235,229,0.45",
    "white50": "240,235,229,0.50",
    "white75": "240,235,229,0.75",
    "white": "240,235,229",
}

TSUKIMI_WHITE05_ON_BG_GAMELIST = "15,16,21"

TSUKIMI_COMMENT = "Tsukimi-inspired palette"

CUSTOM_CSS_SNIPPET = """/* Tsukimi (dark):

--focus: 205, 177, 149;
--clientBG: 13, 14, 18;
--header_dark: 13, 14, 18;
--bgGameList: 10, 11, 15;
--frameBorder: 37, 42, 54;
--textentry: 13, 14, 18;
--white05onbgGameList: 15, 16, 21;
--white: 240, 235, 229;
--white45: 240, 235, 229, 0.45;

*/
"""


def _detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _with_spaced_commas(rgb: str) -> str:
    # "13,14,18" -> "13, 14, 18" (also supports alpha: "240,235,229,0.03")
    return ", ".join([part.strip() for part in rgb.split(",")])


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", errors="strict")


def _backup_file(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{path.name}.{timestamp}.bak"
    shutil.copy2(path, backup_path)
    return backup_path


def _replace_css_vars_in_root_block(text: str, replacements: dict[str, str]) -> tuple[str, list[str]]:
    """
    Replaces --var: ...; inside the first :root { ... } block of the file.
    Returns (updated_text, changed_var_names).
    """
    m = re.search(r"(?s)(:root\s*\{)(.*?)(\n\})", text)
    if not m:
        return text, []

    before, root_body, after = text[: m.start(2)], m.group(2), text[m.end(2) :]
    changed: list[str] = []

    for var, value in replacements.items():
        pattern = re.compile(rf"(?m)^([ \t]*--{re.escape(var)}\s*:\s*)([^;]*)(;)")
        new_root_body, n = pattern.subn(rf"\g<1>{value}\g<3>", root_body, count=1)
        if n:
            root_body = new_root_body
            changed.append(var)

    return before + root_body + after, changed


def _ensure_comment_before_var_in_root_block(
    text: str, *, var: str, comment: str
) -> tuple[str, bool]:
    """
    Ensures a comment line exists directly above the first `--{var}:` line
    within the first :root { ... } block.
    """
    m = re.search(r"(?s)(:root\s*\{)(.*?)(\n\})", text)
    if not m:
        return text, False

    nl = _detect_newline(text)
    root_body = m.group(2)
    # Find the var line, capturing indentation.
    var_re = re.compile(rf"(?m)^(?P<indent>[ \t]*)--{re.escape(var)}\s*:")
    vm = var_re.search(root_body)
    if not vm:
        return text, False

    indent = vm.group("indent")
    comment_line = f"{indent}/* {comment} */"

    # Check if the preceding non-empty line is already our comment.
    lines = root_body.splitlines()
    # Compute which line contains the var.
    var_line_idx = None
    for i, line in enumerate(lines):
        if var_re.match(line):
            var_line_idx = i
            break
    if var_line_idx is None:
        return text, False

    j = var_line_idx - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j >= 0 and TSUKIMI_COMMENT in lines[j]:
        return text, False

    lines.insert(var_line_idx, comment_line)
    new_root_body = nl.join(lines) + (nl if root_body.endswith(("\n", "\r\n")) else "")

    new_text = text[: m.start(2)] + new_root_body + text[m.end(2) :]
    return new_text, True


def _ensure_webkit_body_bg_uses_clientbg(text: str) -> tuple[str, bool]:
    # Normalize within body { ... } to: background: rgb(var(--clientBG));
    body_re = re.compile(r"(?sm)^(\s*body\s*\{)(.*?)(^\s*\}\s*)")
    m = body_re.search(text)
    if not m:
        return text, False

    head, body, close = m.group(1), m.group(2), m.group(3)
    nl = _detect_newline(text)
    bg_re = re.compile(r"(?m)^(\s*background:\s*)rgb\([^)]*\)\s*;.*$")
    bm = bg_re.search(body)
    if not bm:
        return text, False
    new_line = f"{bm.group(1)}rgb(var(--clientBG));"
    new_body, n = bg_re.subn(new_line, body, count=1)
    if not n:
        return text, False
    new_text = text[: m.start()] + head + new_body + close + text[m.end() :]
    return new_text, True


def _ensure_selector_properties(
    text: str, *, selector: str, properties: dict[str, str]
) -> tuple[str, bool]:
    """
    Ensures the first `selector { ... }` block contains/updates the given CSS properties.
    Property values should include any !important and end without a trailing semicolon.
    """
    pattern = re.compile(rf"(?sm)^(\s*{re.escape(selector)}\s*\{{)(.*?)(^\s*\}}\s*)")
    m = pattern.search(text)
    if not m:
        return text, False

    head, body, close = m.group(1), m.group(2), m.group(3)
    nl = _detect_newline(text)
    updated_body = body
    changed = False

    for prop, value in properties.items():
        line_re = re.compile(rf"(?m)^(\s*{re.escape(prop)}\s*:)\s*[^;]*;.*$")
        desired_line = f"    {prop}: {value};"
        if line_re.search(updated_body):
            new_body, n = line_re.subn(desired_line, updated_body, count=1)
            if n:
                updated_body = new_body
                changed = True
        else:
            if not updated_body.endswith(("\n", "\r\n")):
                updated_body += nl
            updated_body += desired_line + nl
            changed = True

    if not changed:
        return text, False

    new_text = text[: m.start()] + head + updated_body + close + text[m.end() :]
    return new_text, True


def patch_css_file(path: Path, replacements: dict[str, str], *, webkit_body_bg: bool = False) -> tuple[bool, list[str]]:
    text = _read_text(path)
    updated, changed_vars = _replace_css_vars_in_root_block(text, replacements)
    changed = updated != text
    if webkit_body_bg:
        updated2, changed_bg = _ensure_webkit_body_bg_uses_clientbg(updated)
        changed = changed or changed_bg
        updated = updated2
    if changed:
        _write_text(path, updated)
    return changed, changed_vars


def patch_theme_json(path: Path) -> bool:
    raw = _read_text(path)
    data = json.loads(raw)

    patches = data.get("patches", {})
    variation = patches.get("Variation", {})
    values = variation.get("values", {})
    if not isinstance(values, dict):
        raise ValueError("theme.json: patches.Variation.values is not an object")

    tsukimi_values = {
        "--focus": [TSUKIMI_RGB["focus"], "all"],
        "--clientBG": [TSUKIMI_RGB["clientBG"], "all"],
        "--header_dark": [TSUKIMI_RGB["header_dark"], "all"],
        "--bgGameList": [TSUKIMI_RGB["bgGameList"], "all"],
        "--white05onbgGameList": [TSUKIMI_WHITE05_ON_BG_GAMELIST, "all"],
        "--frameBorder": [TSUKIMI_RGB["frameBorder"], "all"],
        "--textentry": [TSUKIMI_RGB["textentry"], "all"],
        "--online": [TSUKIMI_RGB["online"], "all"],
        "--ingame": [TSUKIMI_RGB["ingame"], "all"],
        "--offline": [TSUKIMI_RGB["offline"], "all"],
        "--golden": [TSUKIMI_RGB["golden"], "all"],
        "--white03": [TSUKIMI_RGB["white03"], "all"],
        "--white05": [TSUKIMI_RGB["white05"], "all"],
        "--white08": [TSUKIMI_RGB["white08"], "all"],
        "--white10": [TSUKIMI_RGB["white10"], "all"],
        "--white12": [TSUKIMI_RGB["white12"], "all"],
        "--white20": [TSUKIMI_RGB["white20"], "all"],
        "--white24": [TSUKIMI_RGB["white24"], "all"],
        "--white25": [TSUKIMI_RGB["white25"], "all"],
        "--white35": [TSUKIMI_RGB["white35"], "all"],
        "--white45": [TSUKIMI_RGB["white45"], "all"],
        "--white50": [TSUKIMI_RGB["white50"], "all"],
        "--white75": [TSUKIMI_RGB["white75"], "all"],
        "--white": [TSUKIMI_RGB["white"], "all"],
    }

    existing = values.get("Tsukimi")
    if existing == tsukimi_values:
        return False

    values["Tsukimi"] = tsukimi_values
    variation["values"] = values
    patches["Variation"] = variation
    data["patches"] = patches

    dumped = json.dumps(data, indent=4, ensure_ascii=False) + "\n"
    if dumped == raw:
        return False
    _write_text(path, dumped)
    return True


def patch_custom_css(path: Path) -> bool:
    text = _read_text(path)
    if "Tsukimi (dark)" in text:
        return False

    marker = "/* Metro White:"
    idx = text.find(marker)
    if idx == -1:
        # Fallback: append at end, with a separating newline.
        updated = text.rstrip() + "\n\n" + CUSTOM_CSS_SNIPPET + "\n"
    else:
        updated = text[:idx] + CUSTOM_CSS_SNIPPET + "\n" + text[idx:]

    if updated == text:
        return False
    _write_text(path, updated)
    return True


def _tsukimi_theme_json_block(indent: str, nl: str) -> str:
    # Keep this formatted exactly like our manual patch to avoid reformatting the file.
    lines = [
        f'{indent}"Tsukimi": {{',
        f'{indent}    "--focus": ["205,177,149", "all"],',
        f'{indent}    "--clientBG": ["13,14,18", "all"],',
        f'{indent}    "--header_dark": ["13,14,18", "all"],',
        f'{indent}    "--bgGameList": ["10,11,15", "all"],',
        f'{indent}    "--white05onbgGameList": ["15,16,21", "all"],',
        f'{indent}    "--frameBorder": ["37,42,54", "all"],',
        f'{indent}    "--textentry": ["13,14,18", "all"],',
        f'{indent}    "--online": ["138,159,186", "all"],',
        f'{indent}    "--ingame": ["138,154,128", "all"],',
        f'{indent}    "--offline": ["184,179,170", "all"],',
        f'{indent}    "--golden": ["229,213,184", "all"],',
        f'{indent}    "--white03": ["240,235,229,0.03", "all"],',
        f'{indent}    "--white05": ["240,235,229,0.05", "all"],',
        f'{indent}    "--white08": ["240,235,229,0.08", "all"],',
        f'{indent}    "--white10": ["240,235,229,0.10", "all"],',
        f'{indent}    "--white12": ["240,235,229,0.12", "all"],',
        f'{indent}    "--white20": ["240,235,229,0.20", "all"],',
        f'{indent}    "--white24": ["240,235,229,0.24", "all"],',
        f'{indent}    "--white25": ["240,235,229,0.25", "all"],',
        f'{indent}    "--white35": ["240,235,229,0.35", "all"],',
        f'{indent}    "--white45": ["240,235,229,0.45", "all"],',
        f'{indent}    "--white50": ["240,235,229,0.50", "all"],',
        f'{indent}    "--white75": ["240,235,229,0.75", "all"],',
        f'{indent}    "--white": ["240,235,229", "all"]',
        f"{indent}}},",
    ]
    return nl.join(lines)


def _upsert_tsukimi_variation_in_theme_json(raw: str) -> tuple[str, bool]:
    nl = _detect_newline(raw)
    if '"Variation"' not in raw:
        raise ValueError("theme.json: could not find Variation patch")

    # If Tsukimi already exists, replace its object block with canonical content.
    if '"Tsukimi"' in raw:
        # Find the indentation of the Tsukimi key.
        key_m = re.search(r'(?m)^(\s*)"Tsukimi"\s*:\s*\{', raw)
        if not key_m:
            return raw, False
        indent = key_m.group(1)
        start = key_m.start()
        # Find the opening brace for Tsukimi and the matching closing brace.
        brace_start = raw.find("{", key_m.end() - 1)
        if brace_start == -1:
            return raw, False
        depth = 0
        i = brace_start
        while i < len(raw):
            ch = raw[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    brace_end = i
                    break
            i += 1
        else:
            raise ValueError("theme.json: unterminated Tsukimi object")

        # Extend to include trailing comma if present.
        j = brace_end + 1
        while j < len(raw) and raw[j] in " \t":
            j += 1
        if j < len(raw) and raw[j] == ",":
            j += 1
        replacement = _tsukimi_theme_json_block(indent, nl)
        new_raw = raw[:start] + replacement + raw[j:]
        return (new_raw, new_raw != raw)

    # Otherwise insert after the Midnight block.
    midnight_m = re.search(r'(?m)^(\s*)"Midnight"\s*:\s*\{', raw)
    if not midnight_m:
        raise ValueError('theme.json: could not find "Midnight" variation block')
    indent = midnight_m.group(1)
    # Find matching closing brace for Midnight object.
    brace_start = raw.find("{", midnight_m.end() - 1)
    depth = 0
    i = brace_start
    while i < len(raw):
        ch = raw[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                brace_end = i
                break
        i += 1
    else:
        raise ValueError("theme.json: unterminated Midnight object")

    # Find end of the Midnight entry (include following comma/newline).
    insert_at = brace_end + 1
    while insert_at < len(raw) and raw[insert_at] in " \t":
        insert_at += 1
    if insert_at < len(raw) and raw[insert_at] == ",":
        insert_at += 1
    # Preserve existing newline right after Midnight entry if present.
    if raw[insert_at : insert_at + len(nl)] == nl:
        insert_at += len(nl)
        prefix = ""
    else:
        prefix = nl
    block = _tsukimi_theme_json_block(indent, nl)
    new_raw = raw[:insert_at] + prefix + block + nl + raw[insert_at:]
    return new_raw, True


def _must_exist(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing expected file: {path}")


def _iter_files(base: Path, names: Iterable[str]) -> list[Path]:
    return [base / name for name in names]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Patch MetroSteam (Metro by Rose) colors to a Tsukimi-inspired palette."
    )
    parser.add_argument(
        "metrosteam_dir",
        nargs="?",
        default=".",
        help="Path to MetroSteam skin folder (default: current directory)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would change, without writing")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create backups (default: create backups in ./_tsukimi_patch_backups/)",
    )
    args = parser.parse_args(argv)

    base = Path(args.metrosteam_dir).expanduser().resolve()
    expected = _iter_files(
        base,
        [
            "libraryroot.custom.css",
            "friends.custom.css",
            "notifications.custom.css",
            "webkit.css",
            "theme.json",
        ],
    )
    for p in expected:
        _must_exist(p)

    backup_dir = base / "_tsukimi_patch_backups"

    # Stage changes in memory for dry-run, or apply with backups.
    file_ops: list[tuple[Path, str]] = []

    def stage_write(path: Path, new_text: str) -> None:
        file_ops.append((path, new_text))

    def apply_or_stage(path: Path, new_text: str) -> None:
        if args.dry_run:
            stage_write(path, new_text)
            return
        if not args.no_backup:
            _backup_file(path, backup_dir)
        _write_text(path, new_text)

    # CSS: common replacements
    tsukimi_compact = dict(TSUKIMI_RGB)
    tsukimi_spaced = {k: _with_spaced_commas(v) for k, v in TSUKIMI_RGB.items()}

    css_targets = {
        "libraryroot.custom.css": dict(tsukimi_compact, white05onbgGameList=TSUKIMI_WHITE05_ON_BG_GAMELIST),
        "friends.custom.css": dict(tsukimi_spaced),
        "notifications.custom.css": dict(tsukimi_spaced),
        "webkit.css": dict(tsukimi_compact),
    }

    changed_any = False

    for filename, replacements in css_targets.items():
        path = base / filename
        text = _read_text(path)
        updated, _changed_vars = _replace_css_vars_in_root_block(text, replacements)
        updated, _ = _ensure_comment_before_var_in_root_block(
            updated, var="focus", comment=TSUKIMI_COMMENT
        )
        if filename == "webkit.css":
            updated2, _ = _ensure_webkit_body_bg_uses_clientbg(updated)
            updated = updated2
        if filename == "friends.custom.css":
            updated2, _ = _ensure_selector_properties(
                updated,
                selector=".friendlist",
                properties={
                    "box-sizing": "border-box !important",
                    "border": "1px solid rgb(var(--frameBorder)) !important",
                    "border-right": "none !important",
                },
            )
            updated3, _ = _ensure_selector_properties(
                updated2,
                selector=".chatDialogs",
                properties={
                    "box-sizing": "border-box !important",
                    "border": "1px solid rgb(var(--frameBorder)) !important",
                    "border-left": "none !important",
                },
            )
            updated = updated3
        if updated != text:
            changed_any = True
            apply_or_stage(path, updated)

    # theme.json
    theme_path = base / "theme.json"
    theme_raw = _read_text(theme_path)
    # Sanity check: still valid JSON.
    json.loads(theme_raw)
    updated_theme_raw, theme_changed = _upsert_tsukimi_variation_in_theme_json(theme_raw)
    if theme_changed:
        changed_any = True
        apply_or_stage(theme_path, updated_theme_raw)

    # custom.css snippet
    custom_path = base / "custom.css"
    if custom_path.exists():
        custom_text = _read_text(custom_path)
        if "Tsukimi (dark)" not in custom_text:
            marker = "/* Metro White:"
            idx = custom_text.find(marker)
            nl = _detect_newline(custom_text)
            if idx == -1:
                updated = custom_text.rstrip() + nl + nl + CUSTOM_CSS_SNIPPET + nl
            else:
                updated = custom_text[:idx] + CUSTOM_CSS_SNIPPET + nl + custom_text[idx:]
            if updated != custom_text:
                changed_any = True
                apply_or_stage(custom_path, updated)

    if args.dry_run:
        if not file_ops:
            print("No changes needed (already patched).")
            return 0
        print("Would patch the following files:")
        for path, new_text in file_ops:
            old = _read_text(path)
            print(f"- {path}")
            print(f"  bytes: {len(old)} -> {len(new_text)}")
        return 0

    if not changed_any:
        print("No changes needed (already patched).")
        return 0

    if not args.no_backup:
        print(f"Patched. Backups saved to: {backup_dir}")
    else:
        print("Patched (no backups).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
