# Tenant package archive extraction

`safe_extract(archive_path, destination, max_total_bytes=1048576)` imports regular
files and directories from a ZIP archive and returns the sorted POSIX-style relative
paths of extracted files.

The destination may already be an empty directory. Existing content must never be
overwritten. Invalid input raises `ValueError`.

## Incident

Tenant `north-17` uploaded an archive containing `../shared/policy.json`. The import
was requested under `work/north-17`, but the adjacent shared policy changed. The ZIP
was otherwise readable and contained an ordinary `package.json` file.

Reproduce the boundary escape with the public suite, identify why the current
implementation delegates trust to the archive member name, and propose the smallest
product fix. Do not alter `operator_note.txt` or the existing public-test authority.
