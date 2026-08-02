#!/usr/bin/env python3
"""Build and verify the pilot-v2 atomic holdout package.

The command deliberately emits only the package-manifest digest and the six
public task basenames.  Holdout contents and private filesystem paths never
cross the CLI output boundary.

Stdlib only.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


MANIFEST_NAME = "seal-manifest.json"
HOLDOUT_TASKS = tuple(f"holdout-v2-{number}.md" for number in range(1, 7))
ABLATION_TASKS = (HOLDOUT_TASKS[0], HOLDOUT_TASKS[2])
ROLES = ("scorer", "verifier")
CANONICAL_JUDGE_PROMPTS = {
    "scorer": "judge-prompts/scorer.md",
    "verifier": "judge-prompts/verifier.md",
}
CANONICAL_JUDGE_SCHEMAS = {
    "scorer": "judge-schemas/scorer.json",
    "verifier": "judge-schemas/verifier.json",
}
CANONICAL_QUALITY_RUBRIC = "quality-rubric.md"
CANONICAL_COVERAGE_MATRIX = "coverage-matrix.json"
CANONICAL_TASK_CONTEXTS = {
    task: f"task-contexts/{task}" for task in HOLDOUT_TASKS
}

PROTOCOL_VERSION = 2
MAX_JUDGE_ATTEMPTS = 3
JUDGE_RETRY_POLICY = {
    "max_attempts": MAX_JUDGE_ATTEMPTS,
    "fresh_session_each_attempt": True,
    "repair": "none",
}
AGGREGATION_POLICY = {
    "id": "pilot-v2-all-docs-v1",
    "telemetry": "all-final-scheduled-workflow-outcomes-v1",
    "critical": "candidate-absolute-zero-v1",
}

METADATA_KEYS = {
    "protocol_version",
    "max_judge_attempts",
    "judge_retry_policy",
    "aggregation_policy",
    "judge_prompts",
    "judge_response_schemas",
    "quality_rubric",
    "coverage_matrix",
    "task_contexts",
    "ablation_tasks",
    "snapshot_sources",
    "judge_config",
}
MANIFEST_KEYS = METADATA_KEYS | {"files"}
JUDGE_CONFIG_KEYS = {
    "judge_backend_cmd",
    "judge_model",
    "judge_effort",
}

_JUDGE_CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "seal_package_judge_contract", Path(__file__).with_name("judge_contract.py")
)
if _JUDGE_CONTRACT_SPEC is None or _JUDGE_CONTRACT_SPEC.loader is None:
    raise RuntimeError("judge contract module is unavailable")
judge_contract = importlib.util.module_from_spec(_JUDGE_CONTRACT_SPEC)
_JUDGE_CONTRACT_SPEC.loader.exec_module(judge_contract)


class SealError(ValueError):
    """The package or its metadata violates the sealed protocol."""


def _reject_constant(token):
    raise SealError(f"non-finite JSON number is forbidden: {token}")


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SealError("duplicate JSON object key is forbidden")
        result[key] = value
    return result


def _strict_json(data, what):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SealError(f"{what} is not UTF-8 JSON") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except SealError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise SealError(f"{what} is not strict JSON") from exc


def _lstat(path, what):
    try:
        return path.lstat()
    except OSError as exc:
        raise SealError(f"cannot inspect {what}") from exc


def _require_ordinary_directory(path):
    info = _lstat(path, "package directory")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise SealError("package must be an existing ordinary directory")
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise SealError("cannot resolve package directory") from exc


def _read_regular_bytes(path, what):
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SealError(f"cannot open {what} as an ordinary file") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise SealError(f"{what} is not an ordinary file")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise SealError(f"{what} changed while it was read")
        current = _lstat(Path(path), what)
        identity_current = (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
            current.st_ctime_ns,
        )
        if not stat.S_ISREG(current.st_mode) or identity_current != identity_after:
            raise SealError(f"{what} changed while it was read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _hash_regular_file(path):
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SealError("cannot open a package entry as an ordinary file") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise SealError("package contains a non-ordinary file")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise SealError("package file changed while it was hashed")
        current = _lstat(Path(path), "package file")
        identity_current = (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
            current.st_ctime_ns,
        )
        if not stat.S_ISREG(current.st_mode) or identity_current != identity_after:
            raise SealError("package file changed while it was hashed")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _canonical_relative(value, what):
    if not isinstance(value, str) or not value:
        raise SealError(f"{what} must be a nonempty relative path")
    if "\\" in value or "\x00" in value:
        raise SealError(f"{what} is not a canonical POSIX relative path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in ("", ".", "..") for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise SealError(f"{what} is not a canonical POSIX relative path")
    return value


def _scan_package(package_root, allow_manifest):
    """Return every ordinary package file under its canonical POSIX key."""

    found = {}

    def descend(directory, prefix):
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise SealError("cannot enumerate package directory") from exc
        for entry in sorted(entries, key=lambda item: item.name):
            relative = entry.name if not prefix else f"{prefix}/{entry.name}"
            _canonical_relative(relative, "package entry")
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SealError("cannot inspect package entry") from exc
            if stat.S_ISLNK(info.st_mode):
                raise SealError("package contains a symbolic link")
            if stat.S_ISDIR(info.st_mode):
                descend(Path(entry.path), relative)
            elif stat.S_ISREG(info.st_mode):
                if relative == MANIFEST_NAME:
                    if not allow_manifest:
                        raise SealError("seal manifest already exists")
                else:
                    found[relative] = Path(entry.path)
            else:
                raise SealError("package contains a special file")

    descend(package_root, "")
    return {key: found[key] for key in sorted(found)}


def _exact_keys(value, expected, what):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise SealError(f"{what} must contain exactly its registered keys")


def _validate_association_map(value, name, files):
    _exact_keys(value, ROLES, name)
    result = {}
    for role in ROLES:
        relative = _canonical_relative(value[role], f"{name}.{role}")
        if relative not in files:
            raise SealError(f"{name} association does not refer to a package file")
        result[role] = relative
    if len(set(result.values())) != len(ROLES):
        raise SealError(f"{name} must use a distinct file for each role")
    return result


def _validate_file_map(files):
    if not isinstance(files, dict):
        raise SealError("files must be an object")
    for relative, digest in files.items():
        _canonical_relative(relative, "files key")
        if relative == MANIFEST_NAME:
            raise SealError("the manifest must not enumerate itself")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise SealError("files values must be lowercase SHA-256 digests")


def _validate_metadata(metadata, files, package_root):
    _exact_keys(metadata, METADATA_KEYS, "metadata")
    if metadata["protocol_version"] != PROTOCOL_VERSION:
        raise SealError("protocol_version must be exactly 2")
    if metadata["max_judge_attempts"] != MAX_JUDGE_ATTEMPTS:
        raise SealError("max_judge_attempts must be exactly 3")
    if metadata["judge_retry_policy"] != JUDGE_RETRY_POLICY:
        raise SealError("judge_retry_policy differs from pilot v2")
    if metadata["aggregation_policy"] != AGGREGATION_POLICY:
        raise SealError("aggregation_policy differs from pilot v2")
    if metadata["judge_prompts"] != CANONICAL_JUDGE_PROMPTS:
        raise SealError(
            "judge_prompts must use the registered generic package paths")
    if metadata["judge_response_schemas"] != CANONICAL_JUDGE_SCHEMAS:
        raise SealError(
            "judge_response_schemas must use the registered generic "
            "package paths")
    if metadata["quality_rubric"] != CANONICAL_QUALITY_RUBRIC:
        raise SealError(
            "quality_rubric must use the registered generic package path")
    if metadata["coverage_matrix"] != CANONICAL_COVERAGE_MATRIX:
        raise SealError(
            "coverage_matrix must use the registered generic package path")
    if metadata["task_contexts"] != CANONICAL_TASK_CONTEXTS:
        raise SealError(
            "task_contexts must use the registered generic package paths")

    prompt_paths = _validate_association_map(
        metadata["judge_prompts"], "judge_prompts", files
    )
    schema_paths = _validate_association_map(
        metadata["judge_response_schemas"], "judge_response_schemas", files
    )
    for role, prompt_path in prompt_paths.items():
        try:
            prompt_text = _read_regular_bytes(
                package_root / prompt_path,
                f"sealed {role} judge prompt",
            ).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SealError(
                f"sealed {role} judge prompt is not UTF-8") from exc
        if not prompt_text.strip():
            raise SealError(
                f"sealed {role} judge prompt must be nonempty")

    rubric = _canonical_relative(metadata["quality_rubric"], "quality_rubric")
    if rubric not in files:
        raise SealError("quality_rubric does not refer to a package file")
    try:
        rubric_text = _read_regular_bytes(
            package_root / rubric, "sealed quality rubric"
        ).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SealError("sealed quality rubric is not UTF-8") from exc
    if not rubric_text.strip():
        raise SealError("sealed quality rubric must be nonempty")

    coverage_ref = _canonical_relative(
        metadata["coverage_matrix"], "coverage_matrix"
    )
    if coverage_ref not in files:
        raise SealError("coverage_matrix does not refer to a package file")
    coverage = _strict_json(
        _read_regular_bytes(package_root / coverage_ref, "sealed coverage matrix"),
        "sealed coverage matrix",
    )
    _exact_keys(coverage, HOLDOUT_TASKS, "coverage matrix")
    if not all(isinstance(value, dict) and value for value in coverage.values()):
        raise SealError("coverage matrix entries must be nonempty objects")

    task_contexts = metadata["task_contexts"]
    _exact_keys(task_contexts, HOLDOUT_TASKS, "task_contexts")
    context_paths = []
    for task in HOLDOUT_TASKS:
        if task not in files:
            raise SealError("a registered holdout task is absent from the package")
        context = _canonical_relative(task_contexts[task], "task context")
        if context not in files:
            raise SealError("task context does not refer to a package file")
        try:
            context_text = _read_regular_bytes(
                package_root / context,
                f"sealed task context for {task}",
            ).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SealError(
                f"sealed task context for {task} is not UTF-8") from exc
        if not context_text.strip():
            raise SealError(
                f"sealed task context for {task} must be nonempty")
        context_paths.append(context)
    if len(set(context_paths)) != len(HOLDOUT_TASKS):
        raise SealError("each holdout task must have a distinct scoring context")
    try:
        external_task_text = _read_regular_bytes(
            package_root / HOLDOUT_TASKS[4],
            "sealed external-context holdout task",
        ).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SealError(
            "sealed external-context holdout task is not UTF-8") from exc
    frontmatter = re.match(
        r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)",
        external_task_text,
        re.DOTALL,
    )
    if (frontmatter is None or not re.search(
            r"^external-snapshots:\s*true\s*$",
            frontmatter.group(1), re.MULTILINE)):
        raise SealError(
            "holdout-v2-5.md must declare `external-snapshots: true` "
            "in frontmatter")
    associated_paths = [
        *prompt_paths.values(),
        *schema_paths.values(),
        rubric,
        coverage_ref,
        *context_paths,
    ]
    if (len(set(associated_paths)) != len(associated_paths)
            or set(associated_paths).intersection(HOLDOUT_TASKS)):
        raise SealError(
            "tasks, contexts, rubric, coverage matrix, prompts, and schemas "
            "must be distinct package files"
        )
    if metadata["ablation_tasks"] != list(ABLATION_TASKS):
        raise SealError(
            "ablation_tasks must be exactly holdout-v2-1.md then "
            "holdout-v2-3.md"
        )

    snapshot_sources = metadata["snapshot_sources"]
    if not isinstance(snapshot_sources, dict):
        raise SealError("snapshot_sources must be an object")
    for snapshot, source in snapshot_sources.items():
        relative = _canonical_relative(snapshot, "snapshot_sources key")
        if relative not in files:
            raise SealError("snapshot source association has no package file")
        if (not isinstance(source, str) or not source
                or source != source.strip() or "\x00" in source
                or any(char.isspace() for char in source)):
            raise SealError("snapshot source URL must be a nonempty string")
        parsed_source = urlsplit(source)
        if (parsed_source.scheme != "https" or not parsed_source.hostname
                or parsed_source.username is not None
                or parsed_source.password is not None
                or parsed_source.query or parsed_source.fragment):
            raise SealError(
                "snapshot source URL must be credential-free HTTPS without "
                "a query or fragment")

    snapshot_files = {
        relative for relative in files if relative.startswith("snapshots/")
    }
    if not snapshot_files:
        raise SealError(
            "protocol-v2 package must contain sealed snapshots for "
            "external-context archetype 5")
    if set(snapshot_sources) != snapshot_files:
        raise SealError(
            "snapshot_sources must map every and only snapshots/ package file")

    judge_config = metadata["judge_config"]
    _exact_keys(judge_config, JUDGE_CONFIG_KEYS, "judge_config")
    command = judge_config["judge_backend_cmd"]
    if (
        not isinstance(command, list)
        or not command
        or any(
            not isinstance(part, str)
            or not part
            or "\x00" in part
            for part in command
        )
    ):
        raise SealError("judge_backend_cmd must be a nonempty string array")
    if any("{installation}" in part for part in command):
        raise SealError("judge_backend_cmd must be installation-free")
    if not any("{effort}" in part for part in command):
        raise SealError("judge_backend_cmd must pin effort")
    for name in ("judge_model", "judge_effort"):
        value = judge_config[name]
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or "\x00" in value
        ):
            raise SealError(f"{name} must be a nonempty string")

    for role in ROLES:
        schema_bytes = _read_regular_bytes(
            package_root / schema_paths[role], "sealed judge response schema"
        )
        schema = _strict_json(schema_bytes, "sealed judge response schema")
        if schema != judge_contract.contract_schema(role):
            raise SealError("sealed judge response schema differs from its contract")


def _manifest_bytes(document):
    try:
        text = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise SealError("manifest is not deterministic JSON data") from exc
    return (text + "\n").encode("utf-8")


def _metadata_file(path, package_root):
    info = _lstat(path, "metadata file")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SealError("metadata must be an ordinary file")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SealError("cannot resolve metadata file") from exc
    try:
        resolved.relative_to(package_root)
    except ValueError:
        pass
    else:
        raise SealError("metadata must be outside the package")
    return resolved


def _atomic_write_manifest(package_root, data):
    destination = package_root / MANIFEST_NAME
    if os.path.lexists(destination):
        raise SealError("seal manifest already exists")
    temporary = package_root / f".{MANIFEST_NAME}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = None
    try:
        descriptor = os.open(temporary, flags, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SealError("short write while creating seal manifest")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        if os.path.lexists(destination):
            raise SealError("seal manifest appeared during build")
        os.replace(temporary, destination)
        directory_fd = os.open(package_root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise SealError("cannot atomically create seal manifest") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _sanitized_result(manifest_bytes):
    return {
        "holdout_tasks": list(HOLDOUT_TASKS),
        "seal_package_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }


def build_package(package, metadata_path):
    """Create ``package/seal-manifest.json`` and return sanitized metadata."""

    package_root = _require_ordinary_directory(Path(package))
    if os.path.lexists(package_root / MANIFEST_NAME):
        raise SealError("seal manifest already exists")
    metadata_file = _metadata_file(Path(metadata_path), package_root)
    metadata = _strict_json(
        _read_regular_bytes(metadata_file, "metadata file"), "metadata file"
    )
    package_files = _scan_package(package_root, allow_manifest=False)
    file_digests = {
        relative: _hash_regular_file(package_files[relative])
        for relative in sorted(package_files)
    }
    _validate_file_map(file_digests)
    _validate_metadata(metadata, file_digests, package_root)
    document = dict(metadata)
    document["files"] = file_digests
    _exact_keys(document, MANIFEST_KEYS, "manifest")
    manifest_bytes = _manifest_bytes(document)
    _atomic_write_manifest(package_root, manifest_bytes)
    return verify_package(package_root, package_root / MANIFEST_NAME)


def verify_package(package, manifest_path):
    """Verify an existing package and return its sanitized registration."""

    package_root = _require_ordinary_directory(Path(package))
    manifest = Path(manifest_path)
    if manifest.name != MANIFEST_NAME:
        raise SealError("manifest must use the fixed seal-manifest.json name")
    try:
        manifest_parent = manifest.parent.resolve(strict=True)
    except OSError as exc:
        raise SealError("cannot resolve manifest parent") from exc
    if manifest_parent != package_root:
        raise SealError("manifest must be package/seal-manifest.json")
    info = _lstat(manifest, "seal manifest")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SealError("seal manifest must be an ordinary file")

    manifest_bytes = _read_regular_bytes(manifest, "seal manifest")
    document = _strict_json(manifest_bytes, "seal manifest")
    _exact_keys(document, MANIFEST_KEYS, "manifest")
    files = document["files"]
    _validate_file_map(files)
    if manifest_bytes != _manifest_bytes(document):
        raise SealError("seal manifest is not in deterministic canonical form")

    package_files = _scan_package(package_root, allow_manifest=True)
    if set(package_files) != set(files):
        raise SealError("package has missing or extra files")
    actual_digests = {
        relative: _hash_regular_file(package_files[relative])
        for relative in sorted(package_files)
    }
    if set(_scan_package(package_root, allow_manifest=True)) != set(files):
        raise SealError("package changed while it was verified")
    if actual_digests != files:
        raise SealError("package file digest mismatch")

    metadata = {key: value for key, value in document.items() if key != "files"}
    _validate_metadata(metadata, files, package_root)
    return _sanitized_result(manifest_bytes)


def _parser():
    parser = argparse.ArgumentParser(
        description="Build or verify a fail-closed pilot-v2 atomic seal"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--package", required=True)
    parser.add_argument("--metadata")
    parser.add_argument("--manifest")
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.build:
        if not args.metadata or args.manifest:
            parser.error("--build requires --metadata and refuses --manifest")
    else:
        if not args.manifest or args.metadata:
            parser.error("--verify requires --manifest and refuses --metadata")
    try:
        if args.build:
            result = build_package(args.package, args.metadata)
        else:
            result = verify_package(args.package, args.manifest)
    except (SealError, OSError):
        # The private package path, metadata, and contents never cross this
        # boundary.  Detailed exceptions remain available to library callers.
        print("seal_package: validation failed", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
