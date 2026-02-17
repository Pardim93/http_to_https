# -*- coding: utf-8 -*-
"""Change http references to https.

Description:
    Replaces http:// with https:// in files of specified extensions
    within a given directory. Skips already-secure URLs, binary files,
    symlinks (unless --follow-symlinks), and ignored directories.

Usage:
    python http_to_https.py [options]

    # Fully interactive (prompts for path and extensions):
    python http_to_https.py

    # Non-interactive / CI-friendly:
    python http_to_https.py --path /my/project --extensions py,html,js

    # Safe preview first:
    python http_to_https.py --path . --extensions py --dry-run

    # With backup, verbose output, and verification:
    python http_to_https.py --path . --extensions py --backup --verbose --verify

Options:
    --path PATH             Project root (default: prompt, fallback cwd).
    --extensions EXTS       Comma-separated extensions, or '*' for all.
    --dry-run               Show what would change; modify nothing.
    --backup                Write .bak copy of each file before modifying.
    --verbose               Print every file scanned, not just modified ones.
    --quiet                 Print only the final summary line.
    --verify                Check each https:// URL resolves (HEAD request)
                            before replacing. Skips unresolvable URLs.
    --exclude-dir DIRS      Extra comma-separated directory names to skip.
    --exclude-ext EXTS      Extra comma-separated extensions to skip.
    --follow-symlinks       Follow symlinks during directory traversal.
    --report FILE           Write a JSON audit report to FILE after the run.

Observation:
    Be sure your user has write access to all files you want to modify.
    Use: sudo chown $USER:$USER /path/to/file  to fix permissions.
"""

import os
import re
import sys
import json
import shutil
import argparse
import datetime
import subprocess
import urllib.request
import urllib.error
from pathlib import Path


# ── Constants ─────────────────────────────────────────────────────────────────

# Matches http:// but NOT https:// (negative lookbehind for 's')
HTTP_PATTERN = re.compile(rb'(?<!s)(http://)')

# Directories always skipped unless overridden
DEFAULT_EXCLUDE_DIRS = {
    '.git', '.hg', '.svn',
    'node_modules', 'vendor', 'venv', '.venv', 'env',
    '__pycache__', '.mypy_cache', '.pytest_cache', '.tox',
    'dist', 'build', '.next', '.nuxt', 'coverage',
}

# Extensions always skipped (binary / compiled / lock files)
DEFAULT_EXCLUDE_EXTS = {
    '.pyc', '.pyo', '.pyd',
    '.so', '.dylib', '.dll', '.exe', '.bin',
    '.jpg', '.jpeg', '.png', '.gif', '.ico', '.webp', '.svg',
    '.mp3', '.mp4', '.wav', '.ogg',
    '.zip', '.tar', '.gz', '.bz2', '.xz', '.rar',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.lock', '.bak',
}


# ── Verbosity helpers ─────────────────────────────────────────────────────────

class Logger:
    """Simple verbosity-aware printer."""

    QUIET   = 0
    NORMAL  = 1
    VERBOSE = 2

    def __init__(self, level: int = NORMAL):
        self.level = level

    def quiet(self, msg: str)   -> None: print(msg)
    def normal(self, msg: str)  -> None:
        if self.level >= self.NORMAL:  print(msg)
    def verbose(self, msg: str) -> None:
        if self.level >= self.VERBOSE: print(msg)


# ── URL verification ──────────────────────────────────────────────────────────

_verified_cache: dict[str, bool] = {}

def url_resolves(url: str, timeout: int = 5) -> bool:
    """Return True if a HEAD request to url succeeds (2xx or 3xx)."""
    if url in _verified_cache:
        return _verified_cache[url]
    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = resp.status < 400
    except Exception:
        ok = False
    _verified_cache[url] = ok
    return ok


def safe_https_replacement(
    original: bytes,
    verify: bool,
    log: Logger,
    filepath: str,
) -> tuple[bytes, int, list[str]]:
    """Replace http:// with https://, optionally verifying each URL.

    Returns:
        (updated_bytes, replacement_count, skipped_urls)
    """
    if not verify:
        updated, count = HTTP_PATTERN.subn(b'https://', original)
        return updated, count, []

    # Verify mode: replace one match at a time
    skipped: list[str] = []
    result  = original
    offset  = 0
    count   = 0

    for match in HTTP_PATTERN.finditer(original):
        # Extract the full URL (up to next whitespace / quote / bracket)
        url_start = match.start()
        rest = original[url_start:]
        end_match = re.search(rb'[\s\'"<>)\]]', rest)
        raw_url = rest[:end_match.start()] if end_match else rest
        https_url = b'https://' + raw_url[len(b'http://'):]

        if not url_resolves(https_url.decode('utf-8', errors='replace')):
            log.verbose(
                f"    [verify] SKIP (unresolvable): {https_url.decode('utf-8', errors='replace')}"
            )
            skipped.append(https_url.decode('utf-8', errors='replace'))
            continue

        # Apply this single replacement relative to current result
        adj_start = match.start() + offset
        result = result[:adj_start] + b'https://' + result[adj_start + len(b'http://'):]
        offset += 1  # 'https' is one byte longer than 'http'
        count  += 1

    return result, count, skipped


# ── Line-number reporting ─────────────────────────────────────────────────────

def find_match_lines(content: bytes) -> list[int]:
    """Return 1-based line numbers of every http:// match."""
    lines = content.split(b'\n')
    result = []
    for lineno, line in enumerate(lines, start=1):
        if HTTP_PATTERN.search(line):
            result.append(lineno)
    return result


# ── Git awareness ─────────────────────────────────────────────────────────────

def check_git_status(project_path: str, log: Logger) -> None:
    """Warn if project is a git repo with uncommitted changes."""
    try:
        result = subprocess.run(
            ['git', '-C', project_path, 'status', '--porcelain'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            log.normal(
                "  ⚠  Warning: git repo has uncommitted changes.\n"
                "     Consider committing or stashing before running.\n"
                "     Use --dry-run to preview, or --backup to protect files.\n"
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # git not installed or timed out — not a problem


# ── File collection ───────────────────────────────────────────────────────────

def collect_filepaths(
    project_path: str,
    extensions: list[str] | str,
    exclude_dirs: set[str],
    exclude_exts: set[str],
    follow_symlinks: bool,
    log: Logger,
) -> list[str]:
    """Walk project_path and return files matching the given extensions.

    Args:
        project_path:    Root directory to search.
        extensions:      List of extensions or '*' for all.
        exclude_dirs:    Directory names to skip entirely.
        exclude_exts:    File extensions to skip.
        follow_symlinks: Whether to follow symlinks.
        log:             Logger instance.

    Returns:
        Sorted list of file paths to process.
    """
    filepaths = []

    for root, dirs, files in os.walk(project_path, followlinks=follow_symlinks):
        # Prune excluded directories in-place so os.walk doesn't descend
        dirs[:] = [
            d for d in dirs
            if d not in exclude_dirs and not (
                os.path.islink(os.path.join(root, d)) and not follow_symlinks
            )
        ]

        for filename in files:
            filepath = os.path.join(root, filename)

            if not follow_symlinks and os.path.islink(filepath):
                log.verbose(f"  [skip symlink] {filepath}")
                continue

            ext = os.path.splitext(filename)[-1].lower()

            if ext in exclude_exts:
                log.verbose(f"  [skip ext]     {filepath}")
                continue

            if extensions != '*' and ext not in extensions:
                log.verbose(f"  [skip ext]     {filepath}")
                continue

            filepaths.append(filepath)

    return sorted(filepaths)


# ── Single file processing ────────────────────────────────────────────────────

def process_file(
    filepath: str,
    dry_run: bool,
    backup: bool,
    verify: bool,
    log: Logger,
) -> dict:
    """Process a single file: find and optionally replace http:// URLs.

    Returns:
        A result dict for the audit report.
    """
    record = {
        'file': filepath,
        'replacements': 0,
        'skipped_urls': [],
        'lines': [],
        'status': 'unchanged',
    }

    try:
        with open(filepath, 'rb') as f:
            original = f.read()

        if not original:
            log.verbose(f"  [skip empty]   {filepath}")
            record['status'] = 'empty'
            return record

        # Detect likely binary files by checking for null bytes
        if b'\x00' in original[:8192]:
            log.verbose(f"  [skip binary]  {filepath}")
            record['status'] = 'binary'
            return record

        match_lines = find_match_lines(original)
        if not match_lines:
            log.verbose(f"  [no match]     {filepath}")
            return record

        updated, count, skipped = safe_https_replacement(
            original, verify=verify, log=log, filepath=filepath
        )

        record['replacements'] = count
        record['skipped_urls'] = skipped
        record['lines']        = match_lines

        if count == 0:
            log.verbose(f"  [no change]    {filepath}  (all URLs skipped by --verify)")
            record['status'] = 'skipped_verify'
            return record

        if dry_run:
            lines_str = ', '.join(str(l) for l in match_lines)
            log.normal(f"  [dry-run] {filepath}")
            log.normal(f"            {count} replacement(s) on line(s): {lines_str}")
            record['status'] = 'dry-run'
            return record

        if backup:
            shutil.copy2(filepath, filepath + '.bak')

        with open(filepath, 'wb') as f:
            f.write(updated)

        lines_str = ', '.join(str(l) for l in match_lines)
        log.normal(f"  Modified:  {filepath}")
        log.normal(f"             {count} replacement(s) on line(s): {lines_str}")
        record['status'] = 'modified'

    except PermissionError as e:
        log.normal(f"  [denied]   {filepath}\n             {e}")
        record['status'] = 'permission_error'
    except FileNotFoundError as e:
        log.normal(f"  [missing]  {filepath} (broken symlink?)\n             {e}")
        record['status'] = 'not_found'
    except OSError as e:
        log.normal(f"  [os error] {filepath}\n             {e}")
        record['status'] = 'os_error'

    return record


# ── Report writer ─────────────────────────────────────────────────────────────

def write_report(
    report_path: str,
    project_path: str,
    extensions: list[str] | str,
    dry_run: bool,
    records: list[dict],
    elapsed: float,
) -> None:
    """Write a JSON audit report summarising the run."""
    modified  = [r for r in records if r['status'] == 'modified']
    dry_found = [r for r in records if r['status'] == 'dry-run']
    errors    = [r for r in records if 'error' in r['status']]

    report = {
        'generated':    datetime.datetime.now().isoformat(),
        'project_path': project_path,
        'extensions':   extensions,
        'dry_run':      dry_run,
        'elapsed_s':    round(elapsed, 3),
        'summary': {
            'files_scanned':  len(records),
            'files_modified': len(modified) if not dry_run else len(dry_found),
            'total_replacements': sum(r['replacements'] for r in records),
            'errors':         len(errors),
        },
        'files': records,
    }

    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written: {report_path}")


# ── Argument parsing & interactive fallbacks ──────────────────────────────────

def parse_extensions(raw: str) -> list[str] | str:
    """Normalise a comma-separated extension string."""
    if raw.strip() == '*':
        return '*'
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    if not parts:
        print("No extensions entered. Aborting.")
        sys.exit(1)
    return [('.' + p.lstrip('.').lower()) for p in parts]


def resolve_path(raw: str) -> str:
    path = raw.strip() if raw.strip() else os.getcwd()
    if not os.path.isdir(path):
        print(f"Path does not exist: {path!r}. Aborting.")
        sys.exit(1)
    return os.path.abspath(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replace http:// with https:// across a project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--path',             help="Project root directory.")
    parser.add_argument('--extensions',       help="Comma-separated extensions or '*'.")
    parser.add_argument('--dry-run',          action='store_true', help="Preview only.")
    parser.add_argument('--backup',           action='store_true', help="Write .bak files.")
    parser.add_argument('--verbose',          action='store_true', help="Show all scanned files.")
    parser.add_argument('--quiet',            action='store_true', help="Summary only.")
    parser.add_argument('--verify',           action='store_true', help="HEAD-check each URL.")
    parser.add_argument('--follow-symlinks',  action='store_true', help="Follow symlinks.")
    parser.add_argument('--exclude-dir',      help="Extra dirs to skip (comma-separated).")
    parser.add_argument('--exclude-ext',      help="Extra extensions to skip (comma-separated).")
    parser.add_argument('--report',           metavar='FILE',      help="Write JSON report to FILE.")
    return parser


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import time

    parser = build_parser()
    args   = parser.parse_args()

    # Verbosity level
    if args.quiet:
        log_level = Logger.QUIET
    elif args.verbose:
        log_level = Logger.VERBOSE
    else:
        log_level = Logger.NORMAL
    log = Logger(log_level)

    if args.dry_run:
        log.quiet("─── DRY RUN MODE — no files will be modified ───\n")

    # ── Path ──────────────────────────────────────────────────────────────────
    if args.path:
        project_path = resolve_path(args.path)
    else:
        raw = input(
            "Enter the absolute project path, or press Enter for current directory:\n> "
        )
        project_path = resolve_path(raw)
    log.normal(f"Project path: {project_path}")

    # ── Extensions ────────────────────────────────────────────────────────────
    if args.extensions:
        extensions = parse_extensions(args.extensions)
    else:
        raw = input(
            "Enter file extensions to modify (comma-separated), or '*' for all:\n> "
        )
        extensions = parse_extensions(raw)
    log.normal(f"Extensions:   {extensions}\n")

    # ── Excluded dirs / exts ──────────────────────────────────────────────────
    exclude_dirs = set(DEFAULT_EXCLUDE_DIRS)
    if args.exclude_dir:
        extras = [d.strip() for d in args.exclude_dir.split(',') if d.strip()]
        exclude_dirs.update(extras)
        log.normal(f"Excluding dirs: {sorted(exclude_dirs)}")

    exclude_exts = set(DEFAULT_EXCLUDE_EXTS)
    if args.exclude_ext:
        extras = parse_extensions(args.exclude_ext)
        if isinstance(extras, list):
            exclude_exts.update(extras)
        log.normal(f"Excluding exts: {sorted(exclude_exts)}")

    # ── Git check ─────────────────────────────────────────────────────────────
    if not args.dry_run:
        check_git_status(project_path, log)

    # ── Collect files ─────────────────────────────────────────────────────────
    filepaths = collect_filepaths(
        project_path, extensions,
        exclude_dirs=exclude_dirs,
        exclude_exts=exclude_exts,
        follow_symlinks=args.follow_symlinks,
        log=log,
    )
    log.normal(f"Files to scan: {len(filepaths)}\n")

    if not filepaths:
        log.quiet("Nothing to do.")
        return

    # ── Process ───────────────────────────────────────────────────────────────
    start   = time.monotonic()
    records = []

    for filepath in filepaths:
        record = process_file(
            filepath,
            dry_run=args.dry_run,
            backup=args.backup,
            verify=args.verify,
            log=log,
        )
        records.append(record)

    elapsed = time.monotonic() - start

    # ── Summary ───────────────────────────────────────────────────────────────
    modified     = [r for r in records if r['status'] in ('modified', 'dry-run')]
    total_repls  = sum(r['replacements'] for r in records)
    errors       = [r for r in records if 'error' in r['status']]

    action = "Found" if args.dry_run else "Made"
    log.quiet(
        f"\n{action} {total_repls} replacement(s) across "
        f"{len(modified)} file(s)  [{elapsed:.2f}s]"
    )
    if errors:
        log.quiet(f"Errors: {len(errors)} file(s) could not be processed.")

    # ── Report ────────────────────────────────────────────────────────────────
    if args.report:
        write_report(
            args.report, project_path, extensions,
            dry_run=args.dry_run, records=records, elapsed=elapsed,
        )


if __name__ == "__main__":
    main()
