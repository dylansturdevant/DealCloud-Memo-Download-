"""Pure-stdlib helpers shared by UI and local tests."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
import zipfile

MAX_CREDENTIAL_BYTES = 65536
MAX_ZIP_SOURCE_BYTES = 150 * 1024 * 1024


def parse_credentials(raw: bytes) -> dict[str, str]:
    if len(raw) > MAX_CREDENTIAL_BYTES:
        raise ValueError('Credentials file must be smaller than 64 KiB.')
    try:
        value = json.loads(raw.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise ValueError('Use a UTF-8 JSON credentials file.') from None
    required = {'site_url', 'client_id', 'client_secret'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('JSON must contain exactly site_url, client_id and client_secret.')
    if any(not isinstance(value[key], str) or not value[key].strip() for key in required):
        raise ValueError('All three credential values must be nonempty strings.')
    if any('your-' in value[key].lower() or 'replace_' in value[key].lower() for key in required):
        raise ValueError('Replace the template placeholders with your actual credentials.')
    url = value['site_url'].strip().rstrip('/')
    try:
        parsed = urlsplit(url)
        invalid = (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                   or parsed.password is not None or parsed.query or parsed.fragment
                   or parsed.path not in ('', '/') or parsed.port not in (None, 443))
    except ValueError:
        invalid = True
    if invalid:
        raise ValueError('Use an HTTPS tenant base URL without credentials, path, query or custom port.')
    # A client secret is not trimmed or case-normalized.
    return {'site_url': url, 'client_id': value['client_id'].strip(), 'client_secret': value['client_secret']}


def fingerprint(settings, timezone, credentials):
    # Used only in session memory to tie a preview to the same settings/credentials.
    payload = {'settings': settings, 'timezone': timezone, 'credentials': credentials}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def lines(text):
    return list(dict.fromkeys(line.strip() for line in text.splitlines() if line.strip()))


def output_directory(job_dir: Path, result: dict) -> Path | None:
    relative = result.get('output')
    if not relative:
        return None
    target = (job_dir / relative).resolve()
    if job_dir.resolve() not in target.parents or not target.is_dir():
        raise ValueError('Invalid worker output path.')
    return target


def create_archive(output: Path, destination: Path):
    # Deliberately allow only known result filenames plus memo files.
    allowed = {'run_settings.json', 'download_summary.csv', 'downloaded_files.csv',
               'candidate_attempts.csv', 'event_issues.csv', 'population_error.txt'}
    files = [p for p in output.rglob('*') if p.is_file() and not p.is_symlink()
             and output.resolve() in p.resolve().parents
             and ('Memos' in p.relative_to(output).parts or p.name in allowed)]
    if sum(p.stat().st_size for p in files) > MAX_ZIP_SOURCE_BYTES:
        raise ValueError('Results exceed the 150 MiB browser-package limit. Open the local output folder instead.')
    temporary = destination.with_suffix('.partial')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for path in files:
                archive.write(path, path.relative_to(output))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
