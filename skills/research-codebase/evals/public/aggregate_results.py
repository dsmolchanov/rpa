#!/usr/bin/env python3
"""Deterministic, fail-closed aggregation for the registered pilot-v2 round.

This module deliberately consumes only immutable manifests and their canonical
per-run/per-judge records.  It never parses judge prose heuristically, pools
runs across tasks, or silently drops a final workflow outcome.
"""

import argparse
import hashlib
import json
import math
import random
import re
import sys
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import judge_contract
import runner
import seal_package


PROTOCOL_VERSION = 2
REPLICATES = 3
AXIS = "all-docs"
SCHEMA_VERSION = judge_contract.RESPONSE_SCHEMA_VERSION
TELEMETRY_POLICY_ID = "all-final-scheduled-workflow-outcomes-v1"
AGGREGATION_POLICY = {
    "id": "pilot-v2-all-docs-v1",
    "telemetry": TELEMETRY_POLICY_ID,
    "critical": "candidate-absolute-zero-v1",
}
JUDGE_RETRY_POLICY = {
    "max_attempts": 3,
    "fresh_session_each_attempt": True,
    "repair": "none",
}
FINAL_RESPONSE_CONTRACT_SHA256 = {
    "scorer":
        "6276198554f6a13544cb8a1f39102ddb290d16d6311a982a4ca9d3919c80c14c",
    "verifier":
        "5db809fa94dd4027078f58bb5e51406963e6f57087b141927cb7112e9dd51505",
}
JUDGE_OUTPUT_POLICY = {
    "id": "claude-cli-json-schema-semantic-reminder-v2",
    "schema": "public-structural-exact-keys-v1",
    "argv": "generic-public-schema-only",
    "result_binding": "result-equals-structured-output",
    "final_response_contract_sha256": dict(
        FINAL_RESPONSE_CONTRACT_SHA256),
}
FINAL_STATUSES = {"completed", "workflow_failure"}
FAILURE_KINDS = {
    "artifact_contract",
    "timeout",
    "abort",
    "missing_document",
    "subagent_policy",
    "workflow_failure",
}
ACCOUNTING_BUCKETS = ("main", "subagents", "auxiliary", "tree")
ACCOUNTING_FIELDS = ("input_tokens", "output_tokens", "tool_calls")


def _require(condition, message):
    if not condition:
        raise runner.InfraFailure(message)


def _file_bytes(path, what):
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise runner.InfraFailure(f"cannot read {what}: {exc}") from exc


def _reject_json_constant(token):
    raise ValueError(f"non-finite JSON constant {token}")


def _json_object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _strict_json_object_bytes(data, what):
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError,
            RecursionError) as exc:
        raise runner.InfraFailure(f"{what} is not strict UTF-8 JSON") from exc
    _require(isinstance(value, dict), f"{what} must be a JSON object")
    return value


def _strict_json_path(path, what):
    return _strict_json_object_bytes(_file_bytes(path, what), what)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _json_sha(items):
    material = json.dumps(
        items, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256(material)


def _number(value, what, *, nonnegative=False, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise runner.InfraFailure(f"{what} must be a finite JSON number")
    if isinstance(value, float) and not math.isfinite(value):
        raise runner.InfraFailure(f"{what} must be finite")
    result = Fraction(str(value))
    if nonnegative and result < 0:
        raise runner.InfraFailure(f"{what} must be nonnegative")
    if positive and result <= 0:
        raise runner.InfraFailure(f"{what} must be positive")
    return result


def _nonnegative_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise runner.InfraFailure(f"{what} must be a nonnegative integer")
    return value


def _median(values, what):
    _require(len(values) == REPLICATES,
             f"{what} requires exactly {REPLICATES} values")
    return sorted(values)[1]


def _mean(values, what):
    _require(bool(values), f"{what} has no values")
    return sum(values, Fraction(0, 1)) / len(values)


def _decimal_text(value):
    with localcontext() as context:
        context.prec = 40
        rendered = format(
            Decimal(value.numerator) / Decimal(value.denominator), ".12f"
        ).rstrip("0").rstrip(".")
    return rendered or "0"


def _rational(value):
    if value is None:
        return None
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": _decimal_text(value),
    }


def _resolve_reference(value, base, what):
    _require(isinstance(value, str) and value, f"{what} path is missing")
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [Path(base) / raw, raw]
    existing = []
    for candidate in candidates:
        try:
            if candidate.exists():
                resolved = candidate.resolve()
                if resolved not in existing:
                    existing.append(resolved)
        except OSError as exc:
            raise runner.InfraFailure(f"cannot resolve {what}: {exc}") from exc
    _require(existing, f"{what} file does not exist")
    _require(len(existing) == 1,
             f"relative {what} path resolves ambiguously")
    return existing[0]


def _inside(root, relative, what):
    _require(isinstance(relative, str) and relative,
             f"{what} package path is missing")
    rel = Path(relative)
    _require(not rel.is_absolute(), f"{what} package path must be relative")
    root = Path(root).resolve()
    target = (root / rel).resolve()
    _require(target == root or root in target.parents,
             f"{what} package path escapes the sealed package")
    return target


def _verify_seal(config, seal_manifest_path):
    configured_seal = config.get("seal_manifest")
    _require(isinstance(configured_seal, str) and configured_seal,
             "runtime config has no seal manifest binding")
    try:
        same_configured_seal = (Path(configured_seal).resolve()
                                == Path(seal_manifest_path).resolve())
    except OSError as exc:
        raise runner.InfraFailure(
            "cannot resolve runtime seal binding") from exc
    _require(same_configured_seal,
             "aggregate seal differs from the runtime config binding")
    seal_bytes = _file_bytes(seal_manifest_path, "seal manifest")
    seal_sha = _sha256(seal_bytes)
    _require(config.get("seal_package_sha256") == seal_sha,
             "seal manifest does not match registered package SHA-256")
    try:
        registration = seal_package.verify_package(
            Path(seal_manifest_path).resolve().parent, seal_manifest_path)
    except (seal_package.SealError, OSError) as exc:
        raise runner.InfraFailure(
            "atomic seal package failed full verification") from exc
    _require(registration.get("seal_package_sha256") == seal_sha,
             "verified seal registration digest mismatch")
    seal_doc = _strict_json_object_bytes(seal_bytes, "seal manifest")
    seal_files = seal_doc.get("files")
    _require(isinstance(seal_files, dict),
             "seal manifest files must be an object")
    _require(seal_doc.get("protocol_version") == PROTOCOL_VERSION,
             "seal protocol_version must be 2")
    _require(seal_doc.get("max_judge_attempts") == 3,
             "seal max_judge_attempts must be 3")
    _require(seal_doc.get("judge_retry_policy") == JUDGE_RETRY_POLICY,
             "sealed judge retry policy is not the registered v2 policy")
    _require(seal_doc.get("judge_output_policy") == JUDGE_OUTPUT_POLICY,
             "sealed judge output policy is not the registered v2 policy")
    actual_final_contracts = {
        role: judge_contract.final_response_contract_sha256(role)
        for role in ("scorer", "verifier")
    }
    _require(actual_final_contracts == FINAL_RESPONSE_CONTRACT_SHA256,
             "public final-response contract differs from independent pins")
    _require(JUDGE_OUTPUT_POLICY.get("final_response_contract_sha256")
             == FINAL_RESPONSE_CONTRACT_SHA256,
             "judge output policy does not bind final-response contracts")
    _require(seal_doc.get("aggregation_policy") == AGGREGATION_POLICY,
             "sealed aggregation policy is not the registered v2 policy")
    associations = seal_doc.get("judge_response_schemas")
    _require(isinstance(associations, dict),
             "seal must associate each judge role with a response schema")
    _require(set(associations) == {"scorer", "verifier"},
             "seal judge schema roles must be exactly scorer and verifier")

    schema_digests = {}
    package_root = Path(seal_manifest_path).resolve().parent
    for role in ("scorer", "verifier"):
        relative = associations[role]
        schema_path = _inside(package_root, relative, f"{role} schema")
        schema_bytes = _file_bytes(schema_path, f"sealed {role} schema")
        expected_digest = seal_files.get(relative)
        _require(isinstance(expected_digest, str),
                 f"sealed files map omits the {role} response schema")
        actual_digest = _sha256(schema_bytes)
        _require(actual_digest == expected_digest,
                 f"sealed {role} response schema digest mismatch")
        schema_doc = _strict_json_object_bytes(
            schema_bytes, f"sealed {role} response schema")
        _require(schema_doc == judge_contract.contract_schema(role),
                 f"sealed {role} response schema differs from pilot-v2")
        schema_digests[role] = actual_digest
    return seal_doc, seal_files, seal_sha, schema_digests, registration


def _load_and_verify_schedule(config, manifest, manifest_path):
    _require(manifest.get("complete") is True,
             "schedule manifest is incomplete")
    _require(manifest.get("protocol_version") == PROTOCOL_VERSION,
             "schedule manifest protocol_version must be 2")
    _require(manifest.get("environment_policy_id")
             == runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
             "schedule manifest environment policy mismatch")
    _require(manifest.get("runtime_pins")
             == runner.protocol_v2_runtime_pins(config),
             "schedule manifest operator runtime pins mismatch")
    _require(manifest.get("config_digest") == runner.config_digest(config),
             "schedule manifest config digest mismatch")
    schedule_path = _resolve_reference(
        manifest.get("schedule"), Path(manifest_path).resolve().parent,
        "schedule",
    )
    schedule = _strict_json_path(schedule_path, "schedule")
    _require(schedule.get("protocol_version") == PROTOCOL_VERSION,
             "schedule protocol_version must be 2")
    _require(schedule.get("environment_policy_id")
             == runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
             "schedule environment policy mismatch")
    _require(schedule.get("runtime_pins")
             == runner.protocol_v2_runtime_pins(config),
             "schedule operator runtime pins mismatch")
    _require(schedule.get("config_digest") == runner.config_digest(config),
             "schedule config digest mismatch")
    _require(manifest.get("schedule_digest") == runner.schedule_digest(schedule),
             "schedule manifest digest mismatch")
    _require(schedule.get("replicates") == REPLICATES,
             "pilot-v2 schedule requires three replicates")
    _require(manifest.get("replicates") == REPLICATES,
             "schedule manifest requires three replicates")
    _require(schedule.get("nonstandard") is False
             and manifest.get("nonstandard") is False,
             "pilot-v2 aggregation refuses a nonstandard schedule")
    tasks = schedule.get("tasks")
    _require(isinstance(tasks, list) and len(tasks) == 6,
             "pilot-v2 schedule must contain six tasks")
    _require(all(isinstance(task, str) and task for task in tasks),
             "schedule tasks must be nonempty strings")
    _require(len(set(tasks)) == len(tasks), "schedule contains duplicate tasks")
    basenames = [Path(task).name for task in tasks]
    _require(len(set(basenames)) == len(basenames),
             "schedule task basenames must be unique")
    _require(basenames == list(seal_package.HOLDOUT_TASKS),
             "pilot-v2 schedule tasks are not in the canonical registered "
             "holdout order")

    rebuilt = runner.make_schedule(
        config, tasks, schedule.get("replicates"), schedule.get("seed"),
        allow_nonstandard=False,
    )
    _require(rebuilt == schedule,
             "schedule is not the registered reconstruction from config/tasks")
    return schedule, schedule_path, dict(zip(tasks, basenames))


def _ritual_stops(record):
    return runner.validate_intervention_log(record)


def _accounting_metrics(accounting):
    metrics = {}
    for bucket in ACCOUNTING_BUCKETS:
        values = accounting.get(bucket)
        _require(isinstance(values, dict),
                 f"accounting {bucket} bucket must be an object")
        parsed = {
            field: Fraction(_nonnegative_int(
                values.get(field), f"accounting {bucket} {field}"), 1)
            for field in ACCOUNTING_FIELDS
        }
        parsed["total_tokens"] = (
            parsed["input_tokens"] + parsed["output_tokens"])
        if "total_tokens" in values:
            recorded_total = _nonnegative_int(
                values["total_tokens"],
                f"accounting {bucket} total_tokens")
            _require(Fraction(recorded_total, 1)
                     == parsed["total_tokens"],
                     f"accounting {bucket} total_tokens mismatch")
        metrics[bucket] = parsed
    for field in ACCOUNTING_FIELDS:
        _require(
            metrics["tree"][field]
            == (metrics["main"][field] + metrics["subagents"][field]
                + metrics["auxiliary"][field]),
            f"accounting tree {field} does not include every bucket")
    return metrics


def _audit_run_material(config, manifest_path, schedule, results, entries):
    """Bind every run record in the output directory to one exact slot.

    The complete schedule manifest is only a convenience view.  Aggregation
    also audits the superseded infrastructure attempts and refuses any stale,
    foreign, ambiguous, claimed, or terminal-invalid material in the run
    directory.  A final attempt N therefore has exactly one record for every
    attempt 1..N, with attempts before N classified only as infrastructure.
    """
    return runner.audit_completed_v2_run_material(
        config, manifest_path, schedule, results, entries)

    # Kept below temporarily as a line-for-line reference for the stricter
    # metric-level validation in `_verify_runs`; the authoritative namespace
    # reconciliation above is shared with the pre-judge handoff.
    root = Path(manifest_path).resolve().parent
    claims = sorted(item.name for item in root.glob("schedule-entry-*.claim"))
    terminal_markers = sorted(
        item.name
        for item in root.glob("schedule-entry-*-terminal-invalid.json")
    )
    _require(not claims,
             "run directory retains an exclusive schedule-entry claim")
    _require(not terminal_markers,
             "run directory is terminally invalid and cannot be aggregated")

    expected_schedule_digest = runner.schedule_digest(schedule)
    expected_config_digest = runner.config_digest(config)
    task_digests = schedule.get("task_digests")
    _require(isinstance(task_digests, dict),
             "schedule task digests must be an object")
    max_retries = config.get("max_infra_retries", 2)
    _require(isinstance(max_retries, int)
             and not isinstance(max_retries, bool) and max_retries == 2,
             "runtime infrastructure retry bound must be the registered two")
    max_attempt = max_retries + 1

    entries_by_index = {}
    for entry in entries:
        _require(isinstance(entry, dict),
                 "schedule entries must contain objects")
        index = entry.get("index")
        _require(isinstance(index, int) and not isinstance(index, bool)
                 and index >= 0 and index not in entries_by_index,
                 "schedule entries have invalid or duplicate indices")
        entries_by_index[index] = entry

    material_by_run = {}
    grouped = {index: [] for index in entries_by_index}
    for record_path in sorted(root.glob("run-*.json"), key=lambda item: item.name):
        match = re.fullmatch(r"run-([0-9a-f]{12})\.json", record_path.name)
        _require(match is not None,
                 "run directory contains a malformed or foreign run record")
        record_bytes = _file_bytes(record_path, "run material record")
        record = _strict_json_object_bytes(
            record_bytes, "run material record")
        run_id = record.get("run_id")
        _require(run_id == match.group(1) and run_id not in material_by_run,
                 "run material record identity differs from its filename")
        _require(record.get("protocol_version") == PROTOCOL_VERSION,
                 "run directory contains a foreign protocol record")
        _require(record.get("environment_policy_id")
                 == runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
                 "run directory contains a foreign environment record")
        _require(record.get("runtime_pins")
                 == runner.protocol_v2_runtime_pins(config),
                 "run directory contains foreign operator runtime pins")
        _require(record.get("schedule_digest") == expected_schedule_digest,
                 "run directory contains a record from another schedule")
        _require(record.get("config_digest") == expected_config_digest,
                 "run directory contains a record from another config")
        index = record.get("schedule_index")
        _require(isinstance(index, int) and not isinstance(index, bool)
                 and index in entries_by_index,
                 "run record refers to an unknown schedule slot")
        entry = entries_by_index[index]
        _require(record.get("arm") == entry.get("arm")
                 and record.get("task") == entry.get("task")
                 and record.get("task_sha256")
                 == task_digests.get(entry.get("task")),
                 "run record immutable slot binding mismatch")
        attempt = record.get("attempt")
        _require(isinstance(attempt, int) and not isinstance(attempt, bool)
                 and 1 <= attempt <= max_attempt,
                 "run material has an invalid attempt number")
        status = record.get("status")
        _require(status in FINAL_STATUSES | {"infra_failure"},
                 "run directory contains ambiguous or nonterminal material")
        if status == "infra_failure":
            _require(record.get("blocking") is not True,
                     "blocking infrastructure material invalidates the round")
        material_by_run[run_id] = (record_bytes, record)
        grouped[index].append((attempt, run_id, record_bytes, record))

    _require(len(results) == len(entries),
             "schedule manifest is not a complete final population")
    record_hashes = []
    for summary, entry in zip(results, entries):
        _require(isinstance(summary, dict),
                 "schedule manifest results must contain objects")
        index = entry["index"]
        _require(summary.get("index") == index,
                 "schedule result index differs from its slot")
        final_run_id = summary.get("run_id")
        _require(isinstance(final_run_id, str)
                 and re.fullmatch(r"[0-9a-f]{12}", final_run_id),
                 "schedule result has an invalid final run id")
        final_attempt = summary.get("attempts")
        _require(isinstance(final_attempt, int)
                 and not isinstance(final_attempt, bool)
                 and 1 <= final_attempt <= max_attempt,
                 "schedule result has an invalid final attempt number")
        attempts = {}
        for attempt, run_id, record_bytes, record in grouped[index]:
            _require(attempt not in attempts,
                     "run slot contains duplicate attempt records")
            attempts[attempt] = run_id
            if attempt < final_attempt:
                _require(record.get("status") == "infra_failure",
                         "run slot contains an extra terminal observation")
            elif attempt == final_attempt:
                _require(run_id == final_run_id
                         and record.get("status") in FINAL_STATUSES,
                         "run slot final material differs from its manifest")
            else:
                raise runner.InfraFailure(
                    "run slot contains material after its final attempt")
            record_hashes.append({
                "schedule_index": index,
                "attempt": attempt,
                "kind": "record",
                "file": f"run-{run_id}.json",
                "sha256": _sha256(record_bytes),
            })
        _require(set(attempts) == set(range(1, final_attempt + 1)),
                 "run slot infrastructure attempt history is not contiguous")
        _require(final_run_id in material_by_run,
                 "schedule result has no canonical final run record")

    allowed_artifacts = {}
    for run_id, (_record_bytes, record) in material_by_run.items():
        status = record.get("status")
        gate = record.get("artifact_gate")
        raw_path = root / f"run-{run_id}-raw.md"
        anon_path = root / f"run-{run_id}-anon.md"
        diag_path = root / f"run-{run_id}-diag.md"
        if gate in {"passed", "failed"}:
            _require(raw_path.is_file() and not raw_path.is_symlink(),
                     "document-producing run has no byte-exact raw artifact")
            allowed_artifacts[raw_path.name] = raw_path
        elif raw_path.exists():
            _require(status == "infra_failure"
                     and raw_path.is_file() and not raw_path.is_symlink(),
                     "no-document run carries unexpected raw artifact")
            # A validator crash can supersede a run only after the raw bytes
            # were copied; preserve and hash that invalid attempt evidence.
            allowed_artifacts[raw_path.name] = raw_path
        if gate == "passed":
            _require(anon_path.is_file() and not anon_path.is_symlink(),
                     "gate-passed run has no anonymized artifact")
            anon_bytes = _file_bytes(anon_path, "anonymized run artifact")
            _require(_sha256(anon_bytes) == record.get("artifact_sha256"),
                     "anonymized run artifact digest mismatch")
            allowed_artifacts[anon_path.name] = anon_path
        if gate == "failed":
            _require(diag_path.is_file() and not diag_path.is_symlink(),
                     "gate-failed run has no diagnostic artifact")
            diag_bytes = _file_bytes(diag_path, "diagnostic run artifact")
            _require(_sha256(diag_bytes) == record.get("diagnostic_sha256"),
                     "diagnostic run artifact digest mismatch")
            allowed_artifacts[diag_path.name] = diag_path

    discovered_artifacts = {
        path.name: path
        for path in root.glob("run-*")
        if path.suffix != ".json"
    }
    _require(set(discovered_artifacts) == set(allowed_artifacts),
             "run directory contains missing, foreign, or orphan artifact "
             "material")
    for name, path in sorted(allowed_artifacts.items()):
        _require(path.is_file() and not path.is_symlink(),
                 "run artifact material must be a regular file")
        record_hashes.append({
            "kind": "artifact",
            "file": name,
            "sha256": _sha256(_file_bytes(path, "run artifact material")),
        })
    record_hashes.sort(key=lambda item: (
        item.get("schedule_index", -1), item.get("attempt", -1),
        item["kind"], item["file"]))
    return material_by_run, record_hashes


def _verify_runs(config, manifest, manifest_path, schedule, task_names):
    results = manifest.get("results")
    entries = schedule.get("entries")
    _require(isinstance(results, list),
             "schedule manifest results must be an array")
    _require(isinstance(entries, list), "schedule entries must be an array")
    runner.verify_results_against_records(
        results, entries, Path(manifest_path).resolve().parent,
        require_all=True,
    )
    _require(len(results) == len(entries),
             "schedule manifest is not a complete final population")
    record_material, record_hashes = _audit_run_material(
        config, manifest_path, schedule, results, entries)

    run_rows = []
    docs = {}
    seen_run_ids = set()
    manifest_root = Path(manifest_path).resolve().parent
    expected_config_digest = runner.config_digest(config)
    for position, (summary, entry) in enumerate(zip(results, entries)):
        run_id = summary.get("run_id")
        _require(isinstance(run_id, str)
                 and re.fullmatch(r"[0-9a-f]{12}", run_id),
                 f"schedule result {position} has no run_id")
        _require(run_id not in seen_run_ids,
                 "schedule manifest reuses a final run id")
        seen_run_ids.add(run_id)
        record_bytes, record = record_material[run_id]
        _require(record.get("run_id") == run_id,
                 "canonical run record id mismatch")
        _require(record.get("protocol_version") == PROTOCOL_VERSION
                 and summary.get("protocol_version") == PROTOCOL_VERSION,
                 "run record and manifest result must bind protocol_version=2")
        _require(record.get("environment_policy_id")
                 == runner.PILOT_V2_ENVIRONMENT_POLICY_ID
                 and summary.get("environment_policy_id")
                 == runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
                 "run record and manifest result have the wrong "
                 "environment policy")
        _require(record.get("runtime_pins")
                 == runner.protocol_v2_runtime_pins(config)
                 and summary.get("runtime_pins")
                 == runner.protocol_v2_runtime_pins(config),
                 "run record and manifest result have the wrong operator "
                 "runtime pins")
        _require(record.get("config_digest") == expected_config_digest,
                 "run record config digest mismatch")
        _require(record.get("schedule_digest")
                 == runner.schedule_digest(schedule)
                 and summary.get("schedule_digest")
                 == runner.schedule_digest(schedule)
                 and record.get("schedule_index") == entry.get("index"),
                 "run record has the wrong immutable schedule binding")
        _require(record.get("task_sha256")
                 == schedule.get("task_digests", {}).get(entry.get("task")),
                 "run record task digest mismatch")
        task = entry.get("task")
        arm_name = entry.get("arm")
        _require(task in task_names, "run refers to a task outside the schedule")
        _require(arm_name in config["arms"],
                 "run refers to an arm outside the config")
        arm_config = config["arms"][arm_name]
        _require(record.get("task") == task and summary.get("task") == task,
                 "run task binding mismatch")
        _require(record.get("arm") == arm_name
                 and summary.get("arm") == arm_name,
                 "run arm binding mismatch")
        _require(record.get("registered_model") == arm_config["model"],
                 "run registered model differs from its arm")
        _require(record.get("effort") == arm_config["effort"],
                 "run effort differs from its arm")
        _require(record.get("installation_sha256") == arm_config["sha256"],
                 "run installation digest differs from its arm")
        _require(record.get("backend_version") == config.get("backend_version"),
                 "run backend version differs from config")
        _require(record.get("entrypoint") == arm_config.get("entrypoint"),
                 "run entrypoint differs from its arm")
        _require(record.get("standard_topology") is True,
                 "run was not executed under the standard topology")
        task_text = runner.read_task_text(task)
        _require(record.get("target_sha")
                 == runner.task_target_sha(task_text, task),
                 "run target SHA differs from its task")
        attempt = record.get("attempt")
        _require(isinstance(attempt, int) and not isinstance(attempt, bool)
                 and 1 <= attempt <= config.get("max_infra_retries", 2) + 1,
                 "final run has an invalid infrastructure attempt number")
        _require(summary.get("attempts") == attempt,
                 "manifest attempts differ from the final run record")
        status = record.get("status")
        _require(status in FINAL_STATUSES,
                 "final run population contains a nonterminal outcome")
        failure_kind = record.get("failure_kind")
        artifact_gate = record.get("artifact_gate")
        if status == "completed":
            _require(failure_kind is None,
                     "completed run must not have a failure_kind")
            _require(artifact_gate == "passed",
                     "completed run must have a passed artifact gate")
        else:
            _require(failure_kind in FAILURE_KINDS,
                     "workflow failure has an unregistered failure_kind")
            _require(artifact_gate in {
                "passed", "failed", "not_evaluated",
            }, "workflow failure artifact gate is invalid")
            if failure_kind == "artifact_contract":
                _require(artifact_gate == "failed",
                         "artifact-contract failure must have a failed gate")

        _require(record.get("telemetry_policy_id") == TELEMETRY_POLICY_ID,
                 "final run has the wrong telemetry policy")
        _require(record.get("telemetry_eligible") is True,
                 "every final workflow outcome must be telemetry eligible")
        _require(record.get("telemetry_exclusion_reason") is None,
                 "eligible final run must not carry a telemetry exclusion")
        wall = _number(record.get("wall_seconds"), "run wall_seconds",
                       nonnegative=True)
        accounting = record.get("accounting")
        _require(isinstance(accounting, dict),
                 "final run must contain tree-wide accounting")
        nodes = record.get("nodes")
        _require(isinstance(nodes, list) and nodes,
                 "final run must retain nonempty accounting nodes")
        try:
            recomputed_accounting = runner.account(nodes)
            runner.validate_models(nodes, arm_config["model"])
            effort_capture = runner.validate_efforts(
                nodes, arm_config["effort"])
        except (runner.InfraFailure, KeyError, TypeError, ValueError) as exc:
            raise runner.InfraFailure(
                "final run nodes cannot be strictly recomputed") from exc
        _require(recomputed_accounting == accounting,
                 "run accounting differs from recomputation over nodes")
        _require(record.get("effort_capture") == effort_capture,
                 "run effort capture differs from node validation")
        accounting_metrics = _accounting_metrics(accounting)
        total_tokens = accounting_metrics["tree"]["total_tokens"]
        subagents_spawned = _nonnegative_int(
            accounting.get("subagents_spawned"), "subagents_spawned")
        subagent_launches = _nonnegative_int(
            accounting.get("subagent_launches"), "subagent_launches")
        subagent_children = _nonnegative_int(
            accounting.get("subagent_children"), "subagent_children")
        _require(subagent_launches <= subagent_children,
                 "final run has a subagent launch without model-bearing "
                 "child accounting")
        if failure_kind == "subagent_policy":
            _require(arm_config.get("forbid_subagents") is True
                     and subagents_spawned > 0,
                     "subagent-policy failure lacks a forbidden spawn")
        if arm_config.get("forbid_subagents") is True and subagents_spawned:
            _require(status == "workflow_failure"
                     and failure_kind == "subagent_policy",
                     "forbidden subagent spawn was not a policy failure")

        doc_name = None
        doc_digest = None
        if artifact_gate == "passed":
            doc_name = f"run-{run_id}-anon.md"
            doc_digest = record.get("artifact_sha256")
            _require(record.get("diagnostic_sha256") is None,
                     "passed artifact gate carries a diagnostic digest")
            _require(record.get("artifact_defects") in (None, []),
                     "passed artifact gate carries contract defects")
        elif artifact_gate == "failed":
            doc_name = f"run-{run_id}-diag.md"
            doc_digest = record.get("diagnostic_sha256")
            _require(record.get("artifact_sha256") is None,
                     "failed artifact gate carries a passing digest")
            defects = record.get("artifact_defects")
            _require(isinstance(defects, list) and defects
                     and all(isinstance(item, str) and item
                             for item in defects),
                     "failed artifact gate has no contract defects")
        else:
            _require(record.get("artifact_sha256") is None
                     and record.get("diagnostic_sha256") is None,
                     "no-document outcome carries a document digest")
        if doc_name is not None:
            _require(isinstance(doc_digest, str) and len(doc_digest) == 64,
                     "scoreable document has no registered SHA-256")
            doc_path = manifest_root / doc_name
            _require(_sha256(_file_bytes(doc_path, "scoreable document"))
                     == doc_digest,
                     "scoreable document digest differs from its run record")
            _require(doc_name not in docs, "duplicate scoreable document name")

        row = {
            "index": entry.get("index"),
            "run_id": run_id,
            "task": task,
            "task_name": task_names[task],
            "arm": arm_name,
            "status": status,
            "failure_kind": failure_kind,
            "artifact_gate": artifact_gate,
            "doc": doc_name,
            "tokens": total_tokens,
            "accounting": accounting_metrics,
            "wall": wall,
            "ritual_stops": _ritual_stops(record),
            "subagents_spawned": subagents_spawned,
        }
        run_rows.append(row)
        if doc_name is not None:
            docs[doc_name] = row
    _require(len(run_rows) == 42,
             "pilot-v2 standard schedule must contain exactly 42 final runs")
    arm_counts = {
        arm: sum(row["arm"] == arm for row in run_rows)
        for arm in config["arms"]
    }
    ablation_arms = [
        arm for arm, arm_config in config["arms"].items()
        if arm_config.get("forbid_subagents")
    ]
    _require(arm_counts.get("baseline") == 18
             and arm_counts.get("candidate") == 18
             and len(ablation_arms) == 1
             and arm_counts.get(ablation_arms[0]) == 6,
             "pilot-v2 final run population has the wrong arm shape")
    return run_rows, docs, record_hashes


def _validate_source_drift_decision(
        drift, task, seal_doc, seal_files, expected_material):
    """Recompute the semantic shape shared by both role manifests.

    A copied materiality verdict is meaningful only for one sealed external
    task and one exact re-fetched digest.  The aggregate cannot fetch history
    retroactively, but it can prove that both batches preserved the same
    sealed-key/digest/adjudication tuple and that changed bytes differ from
    the sealed snapshot.
    """
    _require(isinstance(drift, dict)
             and drift.get("material") is expected_material,
             "judge result has an invalid source-drift materiality verdict")
    task_text = runner.read_task_text(task)
    task_frontmatter = re.match(
        r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)",
        task_text, re.DOTALL)
    _require(Path(task).name == seal_package.HOLDOUT_TASKS[4]
             and task_frontmatter is not None
             and bool(re.search(
                 r"^external-snapshots:\s*true\s*$",
                 task_frontmatter.group(1), re.MULTILINE)),
             "only a sealed external-context task may carry source drift")
    _require(set(drift) == {"changed", "material", "adjudications"},
             "source-drift decision has an invalid shape")
    changed = drift.get("changed")
    adjudications = drift.get("adjudications")
    _require(isinstance(changed, list)
             and all(isinstance(key, str) and key for key in changed)
             and len(set(changed)) == len(changed),
             "source drift must name changed sealed sources")
    _require(isinstance(adjudications, dict)
             and set(adjudications) == set(changed),
             "source-drift adjudications must cover exactly the changed "
             "sealed sources")
    snapshot_sources = seal_doc.get("snapshot_sources")
    _require(isinstance(snapshot_sources, dict),
             "sealed snapshot provenance is unavailable")
    material_flags = []
    for key in changed:
        _require(key in seal_files and key in snapshot_sources,
                 "source-drift decision names an unsealed source")
        adjudication = adjudications[key]
        _require(isinstance(adjudication, dict)
                 and set(adjudication) == {
                     "material", "rationale", "observed_sha256"}
                 and isinstance(adjudication.get("material"), bool)
                 and isinstance(adjudication.get("rationale"), str)
                 and adjudication["rationale"].strip()
                 and isinstance(
                     adjudication.get("observed_sha256"), str)
                 and re.fullmatch(
                     r"[0-9a-f]{64}", adjudication["observed_sha256"])
                 and adjudication["observed_sha256"] != seal_files[key],
                 "source-drift adjudication has an invalid verdict or "
                 "live-byte binding")
        material_flags.append(adjudication["material"])
    _require(any(material_flags) is expected_material,
             "source-drift decision does not reconcile its adjudications")


def _validate_task_drift_decisions(decisions, schedule_tasks,
                                   seal_doc, seal_files):
    """Validate role-level live-source receipts even for zero-doc tasks."""
    external_tasks = {
        Path(task).name: task for task in schedule_tasks
        if re.search(r"^external-snapshots:\s*true\s*$",
                     runner.read_task_text(task), re.MULTILINE)
    }
    _require(isinstance(decisions, dict)
             and set(decisions) == set(external_tasks),
             "role manifest task-level drift receipts do not cover exactly "
             "the registered external-context tasks")
    snapshot_sources = seal_doc.get("snapshot_sources")
    _require(isinstance(snapshot_sources, dict) and snapshot_sources,
             "sealed snapshot provenance is unavailable")
    source_keys = set(snapshot_sources)
    material_tasks = set()
    for task_name, note in decisions.items():
        _require(isinstance(note, dict) and set(note) == {
            "observed_sha256", "changed", "material", "adjudications",
        }, "task-level source-drift receipt has an invalid shape")
        observed = note["observed_sha256"]
        changed = note["changed"]
        adjudications = note["adjudications"]
        _require(isinstance(observed, dict) and set(observed) == source_keys
                 and all(isinstance(value, str)
                         and re.fullmatch(r"[0-9a-f]{64}", value)
                         for value in observed.values()),
                 "task-level drift receipt has invalid observed digests")
        expected_changed = {
            key for key, digest in observed.items()
            if digest != seal_files.get(key)
        }
        _require(isinstance(changed, list)
                 and len(changed) == len(set(changed))
                 and set(changed) == expected_changed,
                 "task-level changed sources do not match observed bytes")
        _require(isinstance(adjudications, dict)
                 and set(adjudications) == expected_changed,
                 "task-level adjudications do not cover changed sources")
        flags = []
        for key in changed:
            adjudication = adjudications[key]
            _require(isinstance(adjudication, dict)
                     and set(adjudication) == {
                         "material", "rationale", "observed_sha256"}
                     and isinstance(adjudication.get("material"), bool)
                     and isinstance(adjudication.get("rationale"), str)
                     and adjudication["rationale"].strip()
                     and adjudication.get("observed_sha256") == observed[key],
                     "task-level drift adjudication is not digest-bound")
            flags.append(adjudication["material"])
        _require(note.get("material") is any(flags),
                 "task-level materiality does not reconcile adjudications")
        if note["material"]:
            material_tasks.add(external_tasks[task_name])
    return material_tasks


def _verify_judge_manifest(path, role, config, schedule_manifest_path,
                           expected_docs, schema_sha, seal_doc, seal_files,
                           seal_manifest_path, schedule_tasks):
    manifest = _strict_json_path(path, f"{role} scoring manifest")
    _require(manifest.get("complete") is True,
             f"{role} scoring manifest is incomplete")
    scoring_id = manifest.get("scoring_id")
    _require(isinstance(scoring_id, str)
             and re.fullmatch(r"[0-9a-f]{8}", scoring_id) is not None,
             f"{role} scoring manifest has an invalid scoring_id")
    identity = manifest.get("identity")
    _require(isinstance(identity, dict),
             f"{role} scoring manifest has no batch identity")
    _require(identity.get("role") == role and identity.get("axis") == AXIS,
             f"{role} batch role/axis identity mismatch")
    _require(identity.get("protocol_version") == PROTOCOL_VERSION,
             f"{role} batch does not bind protocol_version=2")
    _require(identity.get("environment_policy_id")
             == runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
             f"{role} batch environment policy mismatch")
    _require(identity.get("response_schema_version") == SCHEMA_VERSION,
             f"{role} batch response schema version mismatch")
    _require(identity.get("schema_sha256") == schema_sha,
             f"{role} batch response schema digest mismatch")
    expected_structured_sha = (
        judge_contract.structured_output_schema_sha256(role))
    expected_final_contract_sha = (
        judge_contract.final_response_contract_sha256(role))
    _require(identity.get("judge_output_policy") == JUDGE_OUTPUT_POLICY,
             f"{role} batch judge output policy mismatch")
    _require(identity.get("structured_output_schema_sha256")
             == expected_structured_sha,
             f"{role} batch structured-output schema digest mismatch")
    _require(identity.get("final_response_contract_sha256")
             == expected_final_contract_sha,
             f"{role} batch final-response contract digest mismatch")
    prompt_ref = seal_doc.get("judge_prompts", {}).get(role)
    rubric_ref = seal_doc.get("quality_rubric")
    expected_prompt_sha = seal_files.get(prompt_ref)
    expected_rubric_sha = seal_files.get(rubric_ref)
    _require(isinstance(expected_prompt_sha, str)
             and identity.get("judge_prompt_sha256")
             == expected_prompt_sha,
             f"{role} batch judge prompt digest mismatch")
    _require(isinstance(expected_rubric_sha, str)
             and identity.get("quality_rubric_sha256")
             == expected_rubric_sha,
             f"{role} batch quality rubric digest mismatch")
    config_digest = runner.config_digest(config)
    _require(identity.get("config_digest") == config_digest,
             f"{role} batch config digest mismatch")
    scoring_seed = identity.get("scoring_seed")
    _require(isinstance(scoring_seed, int)
             and not isinstance(scoring_seed, bool),
             f"{role} batch scoring seed must be an integer")
    expected_seed = (runner.PILOT_V2_SCORER_SEED
                     if role == "scorer"
                     else runner.PILOT_V2_VERIFIER_SEED)
    _require(scoring_seed == expected_seed,
             f"{role} batch scoring seed differs from the registered seed")
    identity_docs = identity.get("docs")
    _require(isinstance(identity_docs, list)
             and all(isinstance(item, str) and item for item in identity_docs),
             f"{role} batch docs must be an array of names")
    identity_names = [Path(item).name for item in identity_docs]
    _require(identity_docs == identity_names,
             f"{role} batch docs must use canonical document names")
    _require(len(identity_names) == len(set(identity_names)),
             f"{role} batch contains duplicate documents")
    _require(identity_names == list(expected_docs),
             f"{role} batch documents are not the canonical ordered "
             "all-docs population")
    drift_identity = identity.get("drift_decisions")
    _require(isinstance(drift_identity, dict)
             and set(drift_identity) == {
                 "inconclusive", "notes_digest", "tasks"},
             f"{role} batch drift identity has an invalid shape")
    _validate_task_drift_decisions(
        drift_identity["tasks"], schedule_tasks, seal_doc, seal_files)
    presentation_order = list(range(len(identity_names)))
    random.Random(scoring_seed).shuffle(presentation_order)
    expected_doc_by_slot = {
        slot: identity_names[doc_index]
        for slot, doc_index in enumerate(presentation_order)
    }

    manifest_ref = identity.get("manifest")
    _require(isinstance(manifest_ref, str) and manifest_ref,
             f"{role} batch does not bind the schedule manifest")
    try:
        same_manifest = Path(manifest_ref).resolve() == Path(
            schedule_manifest_path).resolve()
    except OSError as exc:
        raise runner.InfraFailure(
            f"cannot resolve {role} batch manifest binding: {exc}") from exc
    _require(same_manifest, f"{role} batch is bound to another run manifest")

    results = manifest.get("results")
    _require(isinstance(results, list),
             f"{role} scoring results must be an array")
    _require(len(results) == len(expected_docs),
             f"{role} scoring results do not cover every scoreable document")
    by_doc = {}
    record_hashes = []
    attempt_hashes = []
    root = Path(path).resolve().parent
    seen_slots = set()
    seen_attempt_profiles = set()
    seen_attempt_cwds = set()
    seen_attempt_sessions = set()
    allowed_judge_material = set()
    for result in results:
        _require(isinstance(result, dict),
                 f"{role} scoring result must be an object")
        slot = result.get("presentation_index")
        _require(isinstance(slot, int) and not isinstance(slot, bool)
                 and 0 <= slot < len(results),
                 f"{role} result has an invalid presentation index")
        _require(slot not in seen_slots,
                 f"{role} results duplicate a presentation index")
        seen_slots.add(slot)
        record_path = root / f"judge-{scoring_id}-{slot}.json"
        allowed_judge_material.add(record_path.name)
        record_bytes = _file_bytes(record_path, "canonical judge record")
        canonical = _strict_json_object_bytes(
            record_bytes, f"canonical {role} judge record")
        _require(canonical == result,
                 f"{role} scoring result differs from its canonical record")
        doc_value = result.get("doc")
        _require(isinstance(doc_value, str) and doc_value,
                 f"{role} result has no document identity")
        doc_name = Path(doc_value).name
        _require(doc_name in expected_docs,
                 f"{role} result refers to an unexpected document")
        _require(doc_name == expected_doc_by_slot[slot],
                 f"{role} result violates the seeded presentation order")
        expected_doc_path = (
            Path(schedule_manifest_path).resolve().parent / doc_name
        ).resolve()
        try:
            actual_doc_path = Path(doc_value).resolve()
        except OSError as exc:
            raise runner.InfraFailure(
                f"cannot resolve {role} scored document binding") from exc
        _require(actual_doc_path == expected_doc_path,
                 f"{role} result binds a foreign document path")
        _require(doc_name not in by_doc,
                 f"{role} results duplicate a document")
        _require(result.get("task") == expected_docs[doc_name]["task"],
                 f"{role} result task does not match its immutable run")
        _require(result.get("role") == role and result.get("axis") == AXIS,
                 f"{role} result role/axis mismatch")
        _require(result.get("protocol_version") == PROTOCOL_VERSION,
                 f"{role} result protocol version mismatch")
        _require(result.get("environment_policy_id")
                 == runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
                 f"{role} result environment policy mismatch")
        _require(result.get("response_schema_version") == SCHEMA_VERSION,
                 f"{role} result response schema version mismatch")
        _require(result.get("schema_sha256") == schema_sha,
                 f"{role} result response schema digest mismatch")
        _require(result.get("judge_output_policy") == JUDGE_OUTPUT_POLICY,
                 f"{role} result judge output policy mismatch")
        _require(result.get("structured_output_schema_sha256")
                 == expected_structured_sha,
                 f"{role} result structured-output schema digest mismatch")
        _require(result.get("final_response_contract_sha256")
                 == expected_final_contract_sha,
                 f"{role} result final-response contract digest mismatch")
        _require(result.get("judge_prompt_sha256") == expected_prompt_sha,
                 f"{role} result judge prompt digest mismatch")
        _require(result.get("quality_rubric_sha256") == expected_rubric_sha,
                 f"{role} result quality rubric digest mismatch")
        _require(result.get("scheduled") is True,
                 f"{role} all-docs result must be schedule-bound")

        task = expected_docs[doc_name]["task"]
        task_receipt = drift_identity["tasks"].get(Path(task).name)
        expected_doc_drift = (None if task_receipt is None else {
            "changed": task_receipt["changed"],
            "material": task_receipt["material"],
            "adjudications": task_receipt["adjudications"],
        })
        _require(result.get("source_drift") == expected_doc_drift,
                 f"{role} document drift decision differs from its "
                 "task-level live-byte receipt")

        if result.get("inconclusive") is True:
            _require(result.get("schema_valid") in (None, False),
                     "source-drift placeholder must not claim a valid schema")
            _require(result.get("parsed_response") in (None, {}),
                     "source-drift placeholder must not contain a score")
            drift = result.get("source_drift")
            _validate_source_drift_decision(
                drift, task, seal_doc, seal_files, True)
            _require(result.get("scoring_seed") == scoring_seed,
                     "source-drift placeholder scoring seed mismatch")
            _require(not list(root.glob(
                f"judge-{scoring_id}-{slot}-attempt-*")),
                "source-drift placeholder unexpectedly has judge attempts")
            _require(not (root / (
                f"judge-{scoring_id}-{slot}-exhausted.json")).exists(),
                "source-drift placeholder unexpectedly has exhaustion state")
        else:
            _require(result.get("scoring_id") == scoring_id,
                     f"{role} accepted result scoring_id mismatch")
            attempt = result.get("attempt")
            _require(isinstance(attempt, int) and not isinstance(attempt, bool)
                     and 1 <= attempt <= JUDGE_RETRY_POLICY["max_attempts"],
                     f"{role} accepted result has an invalid attempt number")
            if result.get("source_drift") is not None:
                _validate_source_drift_decision(
                    result["source_drift"], task, seal_doc, seal_files,
                    False)
            task_name = Path(task).name
            context_assoc = seal_doc.get("task_contexts", {}).get(task_name)
            context_value = result.get("task_context")
            _require(isinstance(context_assoc, str)
                     and isinstance(context_value, str),
                     f"{role} accepted result context is not seal-associated")
            context_path = _inside(
                Path(seal_manifest_path).resolve().parent,
                context_assoc, f"{role} task context")
            try:
                same_context = Path(context_value).resolve() == context_path
            except OSError as exc:
                raise runner.InfraFailure(
                    f"cannot resolve {role} task context binding") from exc
            _require(same_context,
                     f"{role} accepted result binds a foreign task context")
            _require(_sha256(_file_bytes(
                context_path, f"{role} sealed task context"))
                == seal_files.get(context_assoc),
                f"{role} accepted result context digest mismatch")
            seal_value = result.get("seal_manifest")
            _require(isinstance(seal_value, str) and seal_value,
                     f"{role} accepted result has no seal binding")
            try:
                same_seal = (Path(seal_value).resolve()
                             == Path(seal_manifest_path).resolve())
            except OSError as exc:
                raise runner.InfraFailure(
                    f"cannot resolve {role} accepted seal binding") from exc
            _require(same_seal,
                     f"{role} accepted result binds another seal")

            expected_attempt = {
                "doc": doc_value,
                "presentation_index": slot,
                "scoring_id": scoring_id,
                "role": role,
                "axis": AXIS,
                "protocol_version": PROTOCOL_VERSION,
                "environment_policy_id": (
                    runner.PILOT_V2_ENVIRONMENT_POLICY_ID),
                "response_schema_version": SCHEMA_VERSION,
                "schema_sha256": schema_sha,
                "judge_output_policy": JUDGE_OUTPUT_POLICY,
                "structured_output_schema_sha256": expected_structured_sha,
                "final_response_contract_sha256": (
                    expected_final_contract_sha),
                "judge_prompt_sha256": expected_prompt_sha,
                "quality_rubric_sha256": expected_rubric_sha,
                "config_digest": config_digest,
                "backend_version": config.get("backend_version"),
                "scoring_seed": scoring_seed,
                "scheduled": True,
                "judge_model": config.get("judge_model"),
                "judge_effort": config.get("judge_effort"),
                "profile_settings": (
                    runner.VERIFIER_SETTINGS
                    if role == "verifier" else runner.JUDGE_SETTINGS
                ),
                "task": task,
                "task_context": context_value,
                "seal_manifest": seal_value,
                "snapshots": result.get("snapshots"),
                "source_drift": result.get("source_drift"),
                "raw_stream_limit_bytes": (
                    runner.PILOT_V2_MAX_RAW_STREAM_BYTES),
            }
            task_text = runner.read_task_text(task)
            requires_snapshots = bool(re.search(
                r"^external-snapshots:\s*true\s*$",
                task_text, re.MULTILINE))
            snapshot_value = result.get("snapshots")
            if requires_snapshots:
                _require(isinstance(snapshot_value, str) and snapshot_value,
                         f"{role} external-context result has no snapshots")
                try:
                    snapshot_path = Path(snapshot_value).resolve(strict=True)
                    snapshot_path.relative_to(
                        Path(seal_manifest_path).resolve().parent)
                    snapshot_items = runner._sealed_snapshot_items(
                        snapshot_path, seal_files)
                except (OSError, ValueError, runner.InfraFailure) as exc:
                    raise runner.InfraFailure(
                        f"{role} snapshot binding is outside the seal") from exc
                snapshot_sources = seal_doc.get("snapshot_sources", {})
                for snapshot, _relative, seal_key in snapshot_items:
                    _require(_sha256(_file_bytes(
                        snapshot, f"{role} sealed snapshot"))
                        == seal_files.get(seal_key),
                        f"{role} sealed snapshot digest mismatch")
                    _require(seal_key in snapshot_sources,
                             f"{role} snapshot has no sealed source")
            else:
                _require(snapshot_value is None,
                         f"{role} result has unexpected task snapshots")
            if role == "verifier":
                expected_attempt["evidence_sha"] = runner.task_target_sha(
                    task_text, task)
            else:
                _require("evidence_sha" not in result,
                         "scorer accepted result carries verifier evidence")

            accepted_record = None
            allowed_attempt_files = set()
            for attempt_number in range(1, attempt + 1):
                attempt_path = root / (
                    f"judge-{scoring_id}-{slot}-attempt-"
                    f"{attempt_number}.json")
                allowed_attempt_files.add(attempt_path.name)
                allowed_judge_material.add(attempt_path.name)
                _require(attempt_path.exists(),
                         f"{role} accepted attempt chain is not contiguous")
                attempt_bytes = _file_bytes(
                    attempt_path, f"{role} judge attempt record")
                attempt_record = _strict_json_object_bytes(
                    attempt_bytes, f"{role} judge attempt record")
                _require(attempt_record.get("doc") == doc_value,
                         f"{role} judge attempt document binding changed")
                expected_for_number = dict(expected_attempt)
                expected_for_number["attempt"] = attempt_number
                sidecar_name = (
                    f"judge-{scoring_id}-{slot}-attempt-"
                    f"{attempt_number}-raw-stream.txt"
                )
                sidecar_value = attempt_record.get("raw_stream_sidecar")
                _require(isinstance(sidecar_value, str) and sidecar_value,
                         f"{role} judge attempt has no sidecar binding")
                try:
                    same_sidecar = (Path(sidecar_value).resolve()
                                    == (root / sidecar_name).resolve())
                except OSError as exc:
                    raise runner.InfraFailure(
                        f"cannot resolve {role} judge sidecar binding") from exc
                _require(same_sidecar,
                         f"{role} judge attempt binds a foreign sidecar")
                expected_for_number["raw_stream_sidecar"] = sidecar_value
                try:
                    valid = runner._validate_v2_attempt_record(
                        attempt_record, expected_for_number)
                except (runner.InfraFailure, KeyError, TypeError,
                        ValueError) as exc:
                    raise runner.InfraFailure(
                        f"{role} judge attempt failed strict recomputation"
                    ) from exc
                profile = attempt_record["profile"]
                cwd = attempt_record["cwd"]
                session_id = attempt_record.get("session_id")
                try:
                    profile_identity = str(Path(profile).resolve())
                    cwd_identity = str(Path(cwd).resolve())
                except OSError as exc:
                    raise runner.InfraFailure(
                        f"cannot normalize {role} judge isolation") from exc
                _require(profile_identity not in seen_attempt_profiles
                         and cwd_identity not in seen_attempt_cwds,
                         f"{role} judge attempts did not use fresh isolation")
                seen_attempt_profiles.add(profile_identity)
                seen_attempt_cwds.add(cwd_identity)
                if session_id is not None:
                    _require(session_id not in seen_attempt_sessions,
                             f"{role} judge attempt reused a session")
                    seen_attempt_sessions.add(session_id)
                if attempt_number < attempt:
                    _require(valid is False,
                             f"{role} has attempts after its first valid one")
                else:
                    _require(valid is True,
                             f"{role} canonical attempt is not valid")
                    accepted_record = attempt_record
                attempt_hashes.append({
                    "role": role,
                    "presentation_index": slot,
                    "attempt": attempt_number,
                    "sha256": _sha256(attempt_bytes),
                })
                if attempt_record.get("raw_stream_external") is True:
                    allowed_attempt_files.add(sidecar_name)
                    allowed_judge_material.add(sidecar_name)
                _require(not (root / (
                    f"judge-{scoring_id}-{slot}-attempt-"
                    f"{attempt_number}.pending")).exists(),
                    f"{role} accepted chain retains a pending journal")
            _require(accepted_record == canonical,
                     f"{role} canonical record is not the accepted attempt")
            for later in range(
                    attempt + 1, JUDGE_RETRY_POLICY["max_attempts"] + 1):
                _require(not (root / (
                    f"judge-{scoring_id}-{slot}-attempt-{later}.json"
                )).exists() and not (root / (
                    f"judge-{scoring_id}-{slot}-attempt-{later}.pending"
                )).exists(),
                f"{role} has material after its accepted attempt")
            unexpected_attempts = {
                item.name for item in root.glob(
                    f"judge-{scoring_id}-{slot}-attempt-*")
                if item.name not in allowed_attempt_files
            }
            _require(not unexpected_attempts,
                     f"{role} accepted chain has unexpected attempt material")
            _require(not (root / (
                f"judge-{scoring_id}-{slot}-exhausted.json")).exists(),
                f"{role} accepted result also has exhaustion state")
        by_doc[doc_name] = result
        record_hashes.append({
            "role": role,
            "presentation_index": slot,
            "sha256": _sha256(record_bytes),
        })
    _require(seen_slots == set(range(len(results))),
             f"{role} results do not fill every presentation slot")
    drift_notes = {
        Path(result["doc"]).name: result["source_drift"]
        for result in results if result.get("source_drift") is not None
    }
    expected_drift_decisions = {
        "inconclusive": sorted(
            Path(result["doc"]).name for result in results
            if result.get("inconclusive") is True
        ),
        "notes_digest": _sha256(json.dumps(
            drift_notes, sort_keys=True).encode("utf-8")),
        "tasks": drift_identity["tasks"],
    }
    _require(identity.get("drift_decisions") == expected_drift_decisions,
             f"{role} drift decisions differ from judge records")
    unexpected_material = {
        item.name for item in root.glob(f"judge-{scoring_id}-*")
        if item.name not in allowed_judge_material
    }
    _require(not unexpected_material,
             f"{role} batch contains unregistered judge material")
    return (
        by_doc,
        sorted(record_hashes,
               key=lambda item: item["presentation_index"]),
        sorted(attempt_hashes,
               key=lambda item: (item["presentation_index"], item["attempt"])),
    )


def _task_arm_rows(rows, task, arm):
    return [row for row in rows if row["task"] == task and row["arm"] == arm]


def _arm_failures(rows, arm, included_tasks, verifier):
    selected = [row for row in rows
                if row["arm"] == arm and row["task"] in included_tasks]
    artifact = sum(row["artifact_gate"] == "failed" for row in selected)
    workflow = sum(
        row["status"] == "workflow_failure"
        and row["failure_kind"] != "artifact_contract"
        for row in selected
    )
    policy = sum(
        row["failure_kind"] == "subagent_policy"
        or row["subagents_spawned"] > 0
        for row in selected
    )
    ritual = sum(row["ritual_stops"] for row in selected)
    critical = 0
    for row in selected:
        if row["doc"] is None:
            continue
        result = verifier[row["doc"]]
        if not result.get("inconclusive"):
            critical += result["parsed_response"]["critical_error_count"]
    return {
        "artifact_failures": artifact,
        "workflow_failures": workflow,
        "policy_failures": policy,
        "ritual_stops": ritual,
        "critical_errors": critical,
    }


def _artifact_counts(rows, arms, included_tasks):
    output = {}
    for arm in arms:
        selected = [row for row in rows
                    if row["arm"] == arm and row["task"] in included_tasks]
        passed = sum(row["artifact_gate"] == "passed" for row in selected)
        failed = sum(row["artifact_gate"] == "failed" for row in selected)
        output[arm] = {
            "passed": passed,
            "failed": failed,
            "not_evaluated": len(selected) - passed - failed,
            "final_runs": len(selected),
            "pass_rate": _rational(
                Fraction(passed, len(selected)) if selected else Fraction(0, 1)
            ),
        }
    return output


def _accounting_medians(rows):
    output = {}
    for bucket in ACCOUNTING_BUCKETS:
        output[bucket] = {
            field: _median(
                [row["accounting"][bucket][field] for row in rows],
                f"{bucket} {field} accounting cell",
            )
            for field in (*ACCOUNTING_FIELDS, "total_tokens")
        }
    return output


def _rational_accounting(metrics):
    return {
        bucket: {
            field: _rational(value)
            for field, value in values.items()
        }
        for bucket, values in metrics.items()
    }


def aggregate(config_path, manifest_path, scorer_manifest_path,
              verifier_manifest_path, seal_manifest_path):
    """Validate all pilot-v2 inputs and return one sanitized result object."""
    config = runner.load_config(config_path)
    _require(_strict_json_path(config_path, "runtime config") == config,
             "runtime config strict parse differs from runner parse")
    _require(config.get("protocol_version") == PROTOCOL_VERSION,
             "runtime config protocol_version must be 2")
    _require(config.get("max_judge_attempts") == 3,
             "runtime config max_judge_attempts must be 3")
    runner.validate_arm_topology(config)
    (seal_doc, seal_files, seal_sha, schema_digests,
     seal_registration) = _verify_seal(
        config, seal_manifest_path
    )
    # Reuse the runner's config↔seal judge-pin verification in addition to
    # the v2 policy/schema checks above.
    runner.validate_sealed_judge_config(
        config, seal_doc, seal_manifest_path, seal_files
    )

    manifest = _strict_json_path(manifest_path, "schedule manifest")
    schedule, schedule_path, task_names = _load_and_verify_schedule(
        config, manifest, manifest_path
    )
    sealed_tasks = seal_registration.get("holdout_tasks")
    schedule_task_names = [Path(task).name for task in schedule["tasks"]]
    _require(len(schedule_task_names) == len(sealed_tasks)
             and set(schedule_task_names) == set(sealed_tasks),
             "verified seal tasks differ from the registered schedule")
    rows, expected_docs, run_record_hashes = _verify_runs(
        config, manifest, manifest_path, schedule, task_names
    )
    scorer, scorer_hashes, scorer_attempt_hashes = _verify_judge_manifest(
        scorer_manifest_path, "scorer", config,
        manifest_path, expected_docs, schema_digests["scorer"],
        seal_doc, seal_files, seal_manifest_path, schedule["tasks"],
    )
    verifier, verifier_hashes, verifier_attempt_hashes = _verify_judge_manifest(
        verifier_manifest_path, "verifier", config,
        manifest_path, expected_docs, schema_digests["verifier"],
        seal_doc, seal_files, seal_manifest_path, schedule["tasks"],
    )
    scorer_state = _strict_json_path(
        scorer_manifest_path, "scorer scoring manifest")
    verifier_state = _strict_json_path(
        verifier_manifest_path, "verifier scoring manifest")
    scorer_root = Path(scorer_manifest_path).resolve().parent
    verifier_root = Path(verifier_manifest_path).resolve().parent
    _require(scorer_root == verifier_root,
             "scorer and verifier manifests must share one judging directory")
    supplied_batch_manifests = {
        Path(scorer_manifest_path).resolve(),
        Path(verifier_manifest_path).resolve(),
    }
    allowed_scoring_names = {
        path.name for path in supplied_batch_manifests
    } | {
        ".scoring-scorer-all-docs.lock",
        ".scoring-verifier-all-docs.lock",
    }
    discovered_scoring_material = {
        path for pattern in ("scoring-*", ".scoring-*")
        for path in scorer_root.glob(pattern)
    }
    _require(
        {path.name for path in discovered_scoring_material}
        == allowed_scoring_names
        and {path.resolve() for path in discovered_scoring_material
             if path.name.endswith("-manifest.json")}
        == supplied_batch_manifests
        and all(runner._safe_single_link_regular_file(path)
                for path in discovered_scoring_material),
        "judging directory must contain exactly the supplied v2 scorer/"
        "verifier manifests and their expected role locks",
    )
    registered_judge_ids = {
        scorer_state.get("scoring_id"), verifier_state.get("scoring_id")}
    _require(len(registered_judge_ids) == 2
             and all(isinstance(item, str) and item
                     for item in registered_judge_ids),
             "scorer and verifier must have two distinct registered batch ids")
    foreign_judge_material = set()
    for item in scorer_root.glob("judge-*"):
        match = re.match(r"^judge-([0-9a-f]{8})-", item.name)
        if (not item.is_file() or item.is_symlink() or match is None
                or match.group(1) not in registered_judge_ids):
            foreign_judge_material.add(item.name)
    _require(not foreign_judge_material,
             "judging directory contains material from an unregistered "
             "scoring batch")
    for doc_name in expected_docs:
        _require(
            all(scorer[doc_name].get(field)
                == verifier[doc_name].get(field)
                for field in ("task", "task_context", "seal_manifest",
                              "snapshots", "source_drift", "inconclusive")),
            "scorer and verifier immutable document bindings differ",
        )
    scorer_task_drift = scorer_state["identity"]["drift_decisions"]["tasks"]
    verifier_task_drift = verifier_state["identity"]["drift_decisions"]["tasks"]
    _require(scorer_task_drift == verifier_task_drift,
             "scorer and verifier task-level live-source receipts differ")
    scheduled_by_basename = {
        Path(task).name: task for task in schedule["tasks"]
    }
    drift_tasks = {
        scheduled_by_basename[name]
        for name, note in scorer_task_drift.items()
        if note.get("material") is True
    }
    for task in schedule["tasks"]:
        task_docs = [
            name for name, row in expected_docs.items()
            if row["task"] == task
        ]
        task_bindings = {
            json.dumps({
                "snapshots": scorer[name].get("snapshots"),
                "source_drift": scorer[name].get("source_drift"),
                "inconclusive": scorer[name].get("inconclusive", False),
            }, sort_keys=True, allow_nan=False)
            for name in task_docs
        }
        _require(not task_docs or len(task_bindings) == 1,
                 "judge source bindings differ within one task")

    scorer_inconclusive = {
        doc for doc, result in scorer.items() if result.get("inconclusive")
    }
    verifier_inconclusive = {
        doc for doc, result in verifier.items() if result.get("inconclusive")
    }
    _require(scorer_inconclusive == verifier_inconclusive,
             "scorer and verifier disagree on source-drift exclusions")
    for doc in scorer_inconclusive:
        drift_tasks.add(expected_docs[doc]["task"])
    for task in drift_tasks:
        task_docs = {name for name, row in expected_docs.items()
                     if row["task"] == task}
        _require(task_docs <= scorer_inconclusive,
                 "source drift was not applied uniformly to the whole task")

    tasks = schedule["tasks"]
    arms = schedule.get("arms")
    _require(isinstance(arms, list) and set(arms) == set(config["arms"]),
             "schedule arm set differs from runtime config")
    _require("baseline" in arms and "candidate" in arms,
             "pilot-v2 requires baseline and candidate arms")
    ablations = [name for name, arm in config["arms"].items()
                 if arm.get("forbid_subagents")]
    _require(len(ablations) == 1,
             "pilot-v2 requires exactly one no-subagent ablation arm")
    ablation = ablations[0]
    tasks_by_basename = {}
    for task in tasks:
        basename = Path(task).name
        _require(basename not in tasks_by_basename,
                 "schedule task basenames must be unique")
        tasks_by_basename[basename] = task
    configured_ablation_tasks = config["arms"][ablation].get(
        "schedule_tasks")
    _require(isinstance(configured_ablation_tasks, list)
             and len(configured_ablation_tasks) == 2
             and len({Path(task).name
                      for task in configured_ablation_tasks}) == 2,
             "ablation must configure exactly two distinct tasks")
    configured_ablation_basenames = [
        Path(task).name for task in configured_ablation_tasks
    ]
    _require(all(name in tasks_by_basename
                 for name in configured_ablation_basenames),
             "configured ablation tasks are outside the schedule")
    resolved_ablation_tasks = [
        tasks_by_basename[name] for name in configured_ablation_basenames
    ]
    resolved_ablation_task_set = set(resolved_ablation_tasks)

    excluded = {}
    for task in tasks:
        if task in drift_tasks:
            excluded[task] = "source_drift"
            continue
        baseline_rows = _task_arm_rows(rows, task, "baseline")
        if any(row["failure_kind"] in {
                "timeout", "abort", "missing_document",
        } for row in baseline_rows):
            excluded[task] = "baseline_no_document"
    included_tasks = [task for task in tasks if task not in excluded]

    task_output = {}
    quality_deltas = []
    evidence_deltas = []
    token_savings = []
    wall_savings = []
    internal_metrics = {}
    for task in tasks:
        task_name = task_names[task]
        task_doc = {
            "included": task in included_tasks,
            "exclusion_reason": excluded.get(task),
            "arms": {},
            "candidate_minus_baseline": None,
        }
        internal_metrics[task] = {}
        for arm in arms:
            cell = _task_arm_rows(rows, task, arm)
            expected_count = (REPLICATES if arm != ablation
                              or task in resolved_ablation_task_set
                              else 0)
            _require(len(cell) == expected_count,
                     "schedule does not contain exactly three final runs per cell")
            if not cell:
                continue
            quality_values = []
            evidence_values = []
            critical = 0
            for row in cell:
                if row["doc"] is None:
                    continue
                s_result = scorer[row["doc"]]
                v_result = verifier[row["doc"]]
                if s_result.get("inconclusive"):
                    continue
                quality_values.append(_number(
                    s_result["parsed_response"]["total"],
                    "scorer total", nonnegative=True,
                ))
                parsed_v = v_result["parsed_response"]
                denominator = parsed_v["verifiable_claims"]
                evidence_values.append(
                    Fraction(parsed_v["supported_claims"], denominator)
                    if denominator else Fraction(0, 1)
                )
                critical += parsed_v["critical_error_count"]
            workflow_failures = [
                row for row in cell
                if row["status"] == "workflow_failure"
                and row["failure_kind"] != "artifact_contract"
            ]
            no_document_failures = [
                row for row in cell if row["doc"] is None
            ]
            if task in included_tasks and not no_document_failures:
                _require(len(quality_values) == REPLICATES
                         and len(evidence_values) == REPLICATES,
                         "conclusive document-producing cell lacks three judge values")
            quality_median = (_median(quality_values, "quality cell")
                              if len(quality_values) == REPLICATES else None)
            evidence_median = (_median(evidence_values, "evidence cell")
                               if len(evidence_values) == REPLICATES else None)
            token_median = _median([row["tokens"] for row in cell],
                                   "token cell")
            wall_median = _median([row["wall"] for row in cell], "wall cell")
            accounting_medians = _accounting_medians(cell)
            _require(token_median
                     == accounting_medians["tree"]["total_tokens"],
                     "token median differs from tree accounting median")
            internal_metrics[task][arm] = {
                "quality": quality_median,
                "evidence": evidence_median,
                "tokens": token_median,
                "wall": wall_median,
                "critical": critical,
                "accounting": accounting_medians,
            }
            task_doc["arms"][arm] = {
                "final_runs": len(cell),
                "judged_documents": len(quality_values),
                "quality_median": _rational(quality_median),
                "evidence_accuracy_median": _rational(evidence_median),
                "token_median": _rational(token_median),
                "wall_seconds_median": _rational(wall_median),
                "accounting_medians": _rational_accounting(
                    accounting_medians),
                "critical_errors": critical,
                "artifact_passed": sum(
                    row["artifact_gate"] == "passed" for row in cell),
                "workflow_failures": len(workflow_failures),
            }

        if task in included_tasks:
            b = internal_metrics[task]["baseline"]
            c = internal_metrics[task]["candidate"]
            quality_delta = (c["quality"] - b["quality"]
                             if c["quality"] is not None
                             and b["quality"] is not None else None)
            evidence_delta = (c["evidence"] - b["evidence"]
                              if c["evidence"] is not None
                              and b["evidence"] is not None else None)
            _require(b["tokens"] > 0,
                     "baseline token median must be positive for savings")
            _require(b["wall"] > 0,
                     "baseline wall median must be positive for savings")
            token_save = Fraction(1, 1) - c["tokens"] / b["tokens"]
            wall_save = Fraction(1, 1) - c["wall"] / b["wall"]
            task_doc["candidate_minus_baseline"] = {
                "quality": _rational(quality_delta),
                "evidence_accuracy": _rational(evidence_delta),
                "token_savings": _rational(token_save),
                "wall_time_savings": _rational(wall_save),
            }
            if quality_delta is not None:
                quality_deltas.append(quality_delta)
            if evidence_delta is not None:
                evidence_deltas.append(evidence_delta)
            token_savings.append(token_save)
            wall_savings.append(wall_save)
        task_output[task_name] = task_doc

    conclusive_count = len(included_tasks)
    quality_delta = (_mean(quality_deltas, "quality deltas")
                     if len(quality_deltas) == conclusive_count
                     and conclusive_count else None)
    evidence_delta = (_mean(evidence_deltas, "evidence deltas")
                      if len(evidence_deltas) == conclusive_count
                      and conclusive_count else None)
    token_saving = (_mean(token_savings, "token savings")
                    if len(token_savings) == conclusive_count
                    and conclusive_count else None)
    wall_saving = (_mean(wall_savings, "wall savings")
                   if len(wall_savings) == conclusive_count
                   and conclusive_count else None)

    telemetry_arm_means = {}
    for arm in arms:
        arm_task_metrics = [
            internal_metrics[task][arm]["accounting"]
            for task in included_tasks
            if arm in internal_metrics[task]
        ]
        if not arm_task_metrics:
            continue
        means = {
            bucket: {
                field: _mean(
                    [metrics[bucket][field]
                     for metrics in arm_task_metrics],
                    f"{arm} {bucket} {field} descriptive telemetry",
                )
                for field in (*ACCOUNTING_FIELDS, "total_tokens")
            }
            for bucket in ACCOUNTING_BUCKETS
        }
        telemetry_arm_means[arm] = {
            "task_count": len(arm_task_metrics),
            "mean_of_task_medians": _rational_accounting(means),
        }

    # The operational candidate gates are absolute over all six scheduled
    # tasks. A baseline no-document exclusion removes a paired metric cell,
    # never a candidate artifact/workflow/ritual failure. Material source
    # drift has no verifier score, so only its critical-error observation is
    # naturally absent; the round is independently indeterminate below.
    failures = _arm_failures(rows, "candidate", set(tasks), verifier)
    quality_gate = (quality_delta >= Fraction(-1, 4)
                    if quality_delta is not None else None)
    evidence_gate = (evidence_delta >= Fraction(-1, 50)
                     if evidence_delta is not None else None)
    token_gate = (token_saving >= Fraction(1, 5)
                  if token_saving is not None else None)
    wall_gate = (wall_saving >= Fraction(3, 20)
                 if wall_saving is not None else None)
    efficiency_gate = ((token_gate or wall_gate)
                       if token_gate is not None and wall_gate is not None
                       else None)
    gates = {
        "quality_noninferiority": {
            "passed": quality_gate,
            "value": _rational(quality_delta),
            "threshold": _rational(Fraction(-1, 4)),
        },
        "evidence_noninferiority": {
            "passed": evidence_gate,
            "value": _rational(evidence_delta),
            "threshold": _rational(Fraction(-1, 50)),
        },
        "critical_errors": {
            "passed": failures["critical_errors"] == 0,
            "count": failures["critical_errors"],
            "threshold": 0,
        },
        "artifact_contract": {
            "passed": failures["artifact_failures"] == 0,
            "count": failures["artifact_failures"],
            "threshold": 0,
        },
        "workflow_failures": {
            "passed": failures["workflow_failures"] == 0,
            "count": failures["workflow_failures"],
            "threshold": 0,
        },
        "ritual_stops": {
            "passed": failures["ritual_stops"] == 0,
            "count": failures["ritual_stops"],
            "threshold": 0,
        },
        "efficiency": {
            "passed": efficiency_gate,
            "token_savings": _rational(token_saving),
            "token_threshold": _rational(Fraction(1, 5)),
            "wall_time_savings": _rational(wall_saving),
            "wall_threshold": _rational(Fraction(3, 20)),
            "rule": "token_or_wall",
        },
    }
    gate_values = [gate["passed"] for gate in gates.values()]
    if drift_tasks:
        verdict = "indeterminate"
    elif conclusive_count < 3:
        verdict = "indeterminate"
    elif any(value is False for value in gate_values):
        verdict = "fail"
    elif all(value is True for value in gate_values):
        verdict = "pass"
    else:
        verdict = "indeterminate"

    _require(seal_doc.get("ablation_tasks")
             == configured_ablation_basenames,
             "sealed ablation tasks differ from runtime config")
    ablation_failures = _arm_failures(
        rows, ablation, resolved_ablation_task_set, verifier
    )
    ablation_task_output = {}
    ablation_task_passes = []
    for task in resolved_ablation_tasks:
        passed = False
        metrics_doc = None
        if task not in excluded:
            a = internal_metrics[task].get(ablation)
            c = internal_metrics[task].get("candidate")
            if (a and c and a["quality"] is not None and c["quality"] is not None
                    and a["evidence"] is not None and c["evidence"] is not None):
                _require(c["tokens"] > 0 and c["wall"] > 0,
                         "candidate medians must be positive for ablation savings")
                q_delta = a["quality"] - c["quality"]
                e_delta = a["evidence"] - c["evidence"]
                t_save = Fraction(1, 1) - a["tokens"] / c["tokens"]
                w_save = Fraction(1, 1) - a["wall"] / c["wall"]
                passed = (
                    q_delta >= Fraction(-1, 2)
                    and e_delta >= Fraction(-1, 50)
                    and (t_save >= Fraction(3, 10)
                         or w_save >= Fraction(1, 5))
                )
                metrics_doc = {
                    "quality_delta": _rational(q_delta),
                    "evidence_accuracy_delta": _rational(e_delta),
                    "token_savings": _rational(t_save),
                    "wall_time_savings": _rational(w_save),
                }
        ablation_task_passes.append(passed)
        ablation_task_output[task_names[task]] = {
            "included": task not in excluded,
            "metrics": metrics_doc,
            "thresholds_passed": passed,
        }
    ablation_clean = all(
        ablation_failures[key] == 0 for key in (
            "artifact_failures", "workflow_failures", "policy_failures",
            "critical_errors",
        )
    )
    redundancy = all(ablation_task_passes) and ablation_clean

    judge_hashes = scorer_hashes + verifier_hashes
    judge_hashes.sort(key=lambda item: (
        0 if item["role"] == "scorer" else 1,
        item["presentation_index"],
    ))
    judge_attempt_hashes = scorer_attempt_hashes + verifier_attempt_hashes
    judge_attempt_hashes.sort(key=lambda item: (
        0 if item["role"] == "scorer" else 1,
        item["presentation_index"], item["attempt"],
    ))
    input_hashes = {
        "config": _sha256(_file_bytes(config_path, "config")),
        "schedule": _sha256(_file_bytes(schedule_path, "schedule")),
        "schedule_manifest": _sha256(
            _file_bytes(manifest_path, "schedule manifest")),
        "scorer_manifest": _sha256(
            _file_bytes(scorer_manifest_path, "scorer manifest")),
        "verifier_manifest": _sha256(
            _file_bytes(verifier_manifest_path, "verifier manifest")),
        "seal_manifest": seal_sha,
        "run_record_set": _json_sha(run_record_hashes),
        "judge_record_set": _json_sha(judge_hashes),
        "judge_records": judge_hashes,
        "judge_attempt_record_set": _json_sha(judge_attempt_hashes),
        "judge_attempt_records": judge_attempt_hashes,
        "structured_output_schemas": {
            role: judge_contract.structured_output_schema_sha256(role)
            for role in ("scorer", "verifier")
        },
        "final_response_contracts": {
            role: judge_contract.final_response_contract_sha256(role)
            for role in ("scorer", "verifier")
        },
    }
    return {
        "protocol_version": PROTOCOL_VERSION,
        "policy_ids": {
            "aggregation": AGGREGATION_POLICY["id"],
            "telemetry": TELEMETRY_POLICY_ID,
            "environment": runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
            "agent_stream_accounting":
                runner.PILOT_V2_AGENT_STREAM_ACCOUNTING_POLICY["id"],
            "critical_error": AGGREGATION_POLICY["critical"],
            "judge_response_schema": SCHEMA_VERSION,
            "judge_output": JUDGE_OUTPUT_POLICY["id"],
        },
        "input_sha256": input_hashes,
        "population": {
            "scheduled_final_runs": len(rows),
            "scoreable_documents": len(expected_docs),
            "conclusive_tasks": conclusive_count,
            "fresh_seal_required": bool(drift_tasks)
            or conclusive_count < 3,
            "holdout_tasks": sealed_tasks,
            "excluded_tasks": {
                task_names[task]: reason for task, reason in sorted(
                    excluded.items(), key=lambda item: task_names[item[0]])
            },
        },
        "tasks": dict(sorted(task_output.items())),
        "holdout": {
            "quality_delta": _rational(quality_delta),
            "evidence_accuracy_delta": _rational(evidence_delta),
            "token_savings": _rational(token_saving),
            "wall_time_savings": _rational(wall_saving),
            "telemetry_arm_means": telemetry_arm_means,
        },
        "artifact_pass_counts": _artifact_counts(rows, arms, set(tasks)),
        "candidate_failures": failures,
        "gates": gates,
        "ablation": {
            "arm": ablation,
            "tasks": dict(sorted(ablation_task_output.items())),
            "failures": ablation_failures,
            "redundancy_established": redundancy,
            "status": ("established" if redundancy else "not_established"),
        },
        "verdict": verdict,
    }


def _paths_collide(left, right):
    if left == right:
        return True
    try:
        return left.exists() and right.exists() and left.samefile(right)
    except OSError as exc:
        raise runner.InfraFailure(
            "cannot compare aggregate output with protected material"
        ) from exc


def _validate_output_target(output_path, config_path, manifest_path,
                            scorer_manifest_path, verifier_manifest_path,
                            seal_manifest_path):
    """Refuse outputs that could overwrite any aggregation evidence."""
    try:
        output = Path(output_path).resolve()
        supplied = {
            Path(path).resolve() for path in (
                config_path, manifest_path, scorer_manifest_path,
                verifier_manifest_path, seal_manifest_path,
            )
        }
    except OSError as exc:
        raise runner.InfraFailure(
            "cannot resolve aggregate output protection paths") from exc

    manifest = _strict_json_path(manifest_path, "schedule manifest")
    schedule_path = _resolve_reference(
        manifest.get("schedule"), Path(manifest_path).resolve().parent,
        "schedule",
    )
    protected = set(supplied)
    protected.add(schedule_path)

    seal_root = Path(seal_manifest_path).resolve().parent
    _require(output != seal_root and seal_root not in output.parents,
             "aggregate output must be outside the atomic seal package")
    seal_doc = _strict_json_path(seal_manifest_path, "seal manifest")
    seal_files = seal_doc.get("files")
    _require(isinstance(seal_files, dict),
             "seal manifest files must be an object")
    for relative in seal_files:
        protected.add(_inside(seal_root, relative, "sealed material"))

    run_root = Path(manifest_path).resolve().parent
    judge_roots = {
        Path(scorer_manifest_path).resolve().parent,
        Path(verifier_manifest_path).resolve().parent,
    }
    for pattern in ("run-*", "schedule-entry-*"):
        protected.update(item.resolve() for item in run_root.glob(pattern))
    protected.add((run_root / ".run-schedule.lock").resolve())
    for root in judge_roots:
        for pattern in ("judge-*", "scoring-*", ".scoring-*"):
            protected.update(item.resolve() for item in root.glob(pattern))

    _require(not (
        output.parent == run_root
        and (output.name.startswith("run-")
             or output.name.startswith("schedule-entry-"))
    ), "aggregate output collides with the canonical run namespace")
    _require(not any(
        output.parent == root
        and (output.name.startswith("judge-")
             or output.name.startswith("scoring-")
             or output.name.startswith(".scoring-"))
        for root in judge_roots
    ), "aggregate output collides with the canonical judge namespace")
    _require(not any(_paths_collide(output, item) for item in protected),
             "aggregate output collides with protected input material")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", required=True,
                        help="complete schedule-manifest.json")
    parser.add_argument("--scorer-manifest", required=True)
    parser.add_argument("--verifier-manifest", required=True)
    parser.add_argument("--seal-manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        _validate_output_target(
            args.output, args.config, args.manifest, args.scorer_manifest,
            args.verifier_manifest, args.seal_manifest,
        )
        result = aggregate(
            args.config, args.manifest, args.scorer_manifest,
            args.verifier_manifest, args.seal_manifest,
        )
        try:
            runner.atomic_write_text(
                args.output,
                json.dumps(result, ensure_ascii=True, indent=2,
                           sort_keys=True, allow_nan=False) + "\n",
            )
        except OSError as exc:
            raise runner.InfraFailure(
                f"cannot write aggregate output: {exc}") from exc
        print(json.dumps({"status": "complete", "verdict": result["verdict"]},
                         sort_keys=True))
        return 0
    except runner.InfraFailure:
        # Private paths, config values, judge prose, and validation details
        # stay inside the operator session. The CLI boundary is deliberately
        # generic; library callers still receive the classified exception.
        print(json.dumps({
            "status": "infra_failure",
            "error": "aggregate_input_invalid",
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
