# http_to_https

A Python script that replaces `http://` with `https://` across a project. Supports dry-run preview, per-file backup, URL verification, JSON audit reports, configurable exclusions, and full CI/non-interactive use via CLI flags.

## Requirements

```
Python >= 3.10
```

No third-party dependencies — uses only the standard library.

## Usage

```bash
# Interactive (prompts for path and extensions)
python http_to_https.py

# Non-interactive / CI-friendly
python http_to_https.py --path /my/project --extensions py,html,js

# Always preview first
python http_to_https.py --path . --extensions py,html --dry-run

# Full run with backup and audit report
python http_to_https.py --path . --extensions py,html --backup --report report.json
```

## Options

| Flag | Description |
|------|-------------|
| `--path PATH` | Project root directory. Prompts if omitted, defaults to cwd. |
| `--extensions EXTS` | Comma-separated extensions (e.g. `py,html,js`) or `*` for all. |
| `--dry-run` | Show what would change without modifying any files. |
| `--backup` | Write a `.bak` copy of each file before modifying it. |
| `--verbose` | Print every file scanned, including skipped ones and skip reasons. |
| `--quiet` | Print only the final summary line. |
| `--verify` | Send a `HEAD` request to each candidate `https://` URL before replacing. Skips URLs that don't resolve. |
| `--exclude-dir DIRS` | Extra comma-separated directory names to skip, on top of the defaults. |
| `--exclude-ext EXTS` | Extra comma-separated extensions to skip, on top of the defaults. |
| `--follow-symlinks` | Follow symlinks during directory traversal. Off by default. |
| `--report FILE` | Write a JSON audit report to `FILE` after the run. |

## Default Exclusions

The following are skipped automatically without needing any flags:

**Directories:** `.git`, `.hg`, `.svn`, `node_modules`, `vendor`, `venv`, `.venv`, `env`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.tox`, `dist`, `build`, `.next`, `.nuxt`, `coverage`

**Extensions:** `.pyc`, `.pyo`, `.pyd`, `.so`, `.dylib`, `.dll`, `.exe`, `.bin`, image formats, audio/video formats, archives, Office documents, `.lock`, `.bak`

Use `--exclude-dir` and `--exclude-ext` to add your own on top of these defaults.

## Examples

### Dry run — preview all matches with line numbers
```bash
python http_to_https.py --path ./myproject --extensions py,html,css --dry-run
```
```
─── DRY RUN MODE — no files will be modified ───

Project path: /home/user/myproject
Extensions:   ['.py', '.html', '.css']

Files to scan: 4

  [dry-run] /home/user/myproject/src/app.py
            3 replacement(s) on line(s): 1, 2, 3
  [dry-run] /home/user/myproject/templates/index.html
            2 replacement(s) on line(s): 1, 3

Found 5 replacement(s) across 2 file(s)  [0.01s]
```

### Real run with backup
```bash
python http_to_https.py --path ./myproject --extensions py,html --backup
```
Each modified file gets a `.bak` sibling (e.g. `app.py.bak`) preserving the original.

### Quiet mode for CI pipelines
```bash
python http_to_https.py --path . --extensions py,js --quiet
```
```
Made 9 replacement(s) across 4 file(s)  [0.02s]
```

### Verbose mode — see every file and skip reason
```bash
python http_to_https.py --path . --extensions py --dry-run --verbose
```
```
  [skip binary]  ./src/compiled.py
  [skip ext]     ./src/app.pyc
  [no match]     ./src/utils.py
  [dry-run] ./src/app.py
            2 replacement(s) on line(s): 4, 17
```

### URL verification before replacing
```bash
python http_to_https.py --path . --extensions py --verify
```
Sends a `HEAD` request to each candidate `https://` URL. Only replaces if the URL resolves (HTTP status < 400). Results are cached per run so each unique URL is only checked once.

### JSON audit report
```bash
python http_to_https.py --path . --extensions py,html --report audit.json
```
```json
{
  "generated": "2026-02-17T14:32:01.123456",
  "project_path": "/home/user/myproject",
  "extensions": [".py", ".html"],
  "dry_run": false,
  "elapsed_s": 0.021,
  "summary": {
    "files_scanned": 12,
    "files_modified": 4,
    "total_replacements": 9,
    "errors": 0
  },
  "files": [...]
}
```

### Custom exclusions
```bash
# Skip an additional directory and extension
python http_to_https.py --path . --extensions py \
    --exclude-dir docs,scripts \
    --exclude-ext cfg,ini
```

## Behaviour Notes

- **`https://` URLs are never double-upgraded.** A negative lookbehind ensures `https://` is never matched, so existing secure URLs are left untouched.
- **Binary files are skipped automatically** by checking for null bytes in the first 8 KB, regardless of extension.
- **Symlinks are skipped by default.** Use `--follow-symlinks` to opt in.
- **Git awareness:** if the project is a git repository with uncommitted changes, the script prints a warning before modifying anything and suggests using `--dry-run` or `--backup` first.
- **`--quiet` and `--verbose` are mutually exclusive.** If both are passed, `--quiet` wins.

## Permissions

If a file cannot be written, a `[denied]` message is printed and the file is skipped. To fix permissions:

```bash
sudo chown $USER:$USER /path/to/file
```
