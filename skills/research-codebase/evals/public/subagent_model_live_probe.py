#!/usr/bin/env python3
"""One-shot public live probe for the pinned subagent model override.

Run this before authoring the round-10 holdout.  It launches exactly one
Claude session using only a tiny public plugin fixture, requires that session
to invoke the fixture's custom subagent exactly once, and accepts the result
only when both the parent and child stream nodes report ``claude-opus-5``
while ``CLAUDE_CODE_SUBAGENT_MODEL`` is set to that same registered value.

The prompt travels on stdin.  The raw stream and receipt live in the sole
namespace derived from the prospective seal path; creating that namespace is
an irreversible launch claim.  An existing namespace is only revalidated and
is never repaired or relaunched.
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pilot_registration  # noqa: E402
import runner  # noqa: E402
import step5_operator as operator_contract  # noqa: E402


ROUND_NAMESPACE = "holdout-v2-round10"
PACKAGE_NAMESPACE = "package"
OUTPUT_NAMESPACE = "subagent-model-live-probe"
RECEIPT_NAME = "subagent-model-live-probe-receipt.json"
RAW_NAME = "subagent-model-live-probe.jsonl"

PROBE_VERSION = "public-subagent-model-precedence-v1"
VALIDATION_POLICY = "exact-custom-task-lineage-and-model-v1"
EXPECTED_MODEL = "claude-opus-5"
EXPECTED_EFFORT = "high"
SUBAGENT_MODEL_ENV = "CLAUDE_CODE_SUBAGENT_MODEL"
FIXTURE_DECLARED_MODEL = "sonnet"
FIXTURE_ROOT = HERE / "subagent-model-live-probe-plugin"
FIXTURE_FILES = frozenset({
    ".claude-plugin/plugin.json",
    "agents/model-probe-child.md",
})
FIXTURE_SHA256 = (
    "635ad14033244b176dc794b8140dfcc3c6b603201c5f7054b36f7a139de60786"
)
EXPECTED_SUBAGENT_TYPE = "rpa-subagent-model-probe:model-probe-child"

CHILD_MARKER = "PUBLIC-SUBAGENT-MODEL-PROBE-CHILD-OK"
PARENT_MARKER = "PUBLIC-SUBAGENT-MODEL-PROBE-PARENT-OK"
CHILD_TASK_PROMPT = (
    "Follow your public fixture instructions and return exactly "
    f"{CHILD_MARKER} with no other text."
)
PUBLIC_PROMPT = (
    "This is a public synthetic runtime probe, not an evaluation. No holdout "
    "material exists in this session. Use the Task tool exactly once with "
    f"subagent_type `{EXPECTED_SUBAGENT_TYPE}` and prompt exactly: "
    f"{CHILD_TASK_PROMPT}\n"
    f"After that child returns, respond exactly {PARENT_MARKER} and nothing "
    "else. Do not invoke any other tool."
)

# The parent needs Task and nothing else.  The raw-stream validator separately
# rejects every tool_use other than the one exact custom-agent launch, so this
# remains fail-closed if a CLI adds a tool not covered by this public deny list.
PROBE_SETTINGS = {
    "permissions": {
        "deny": [
            "Read", "Glob", "Grep", "Bash", "Write", "Edit",
            "NotebookEdit", "WebFetch", "WebSearch",
        ]
    }
}

# These values are necessarily pending when both public pre-seal probes run.
# Omitting them from the execution identity avoids a circular digest and lets
# the resulting receipt revalidate after all proof digests are registered.
PROSPECTIVE_CONFIG_FIELDS = (
    "seal_package_sha256",
    "judge_live_probe_receipt_sha256",
    "judge_live_probe_execution_sha256",
    "subagent_model_live_probe_receipt_sha256",
    "subagent_model_live_probe_execution_sha256",
)


class ProbeError(RuntimeError):
    """The public subagent-model probe or its receipt is invalid."""


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path):
    try:
        data = runner.read_input_bytes(path, "subagent probe identity file")
    except runner.InfraFailure as exc:
        raise ProbeError("subagent probe identity file is unsafe") from exc
    return _sha256_bytes(data)


def _ordinary_file(path, *, mode=None):
    try:
        info = Path(path).lstat()
    except OSError:
        return False
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_nlink != 1):
        return False
    return mode is None or stat.S_IMODE(info.st_mode) == mode


def _ordinary_directory(path, *, mode=None):
    try:
        info = Path(path).lstat()
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return False
    return mode is None or stat.S_IMODE(info.st_mode) == mode


def canonical_output_dir(config):
    """Derive the sole probe namespace from the round-10 seal path."""
    raw = config.get("seal_manifest")
    if not isinstance(raw, str) or not raw.strip():
        raise ProbeError("subagent-model probe requires seal_manifest")
    supplied_manifest = Path(raw).absolute()
    supplied_package = supplied_manifest.parent
    supplied_round = supplied_package.parent
    if (supplied_manifest.name != "seal-manifest.json"
            or supplied_package.name != PACKAGE_NAMESPACE
            or supplied_round.name != ROUND_NAMESPACE):
        raise ProbeError(
            "seal_manifest is outside the canonical round-10 namespace")
    if (not _ordinary_directory(supplied_round)
            or not _ordinary_directory(supplied_package)):
        raise ProbeError(
            "canonical round-10 package directories are missing or unsafe")
    manifest = supplied_manifest.resolve()
    package = manifest.parent
    round_root = package.parent
    if (package.name != PACKAGE_NAMESPACE
            or round_root.name != ROUND_NAMESPACE
            or package != supplied_package.resolve()
            or round_root != supplied_round.resolve()):
        raise ProbeError("seal_manifest canonical namespace resolves elsewhere")
    return round_root / OUTPUT_NAMESPACE


def _fixture_sha256():
    if not _ordinary_directory(FIXTURE_ROOT):
        raise ProbeError("public subagent probe fixture is missing or unsafe")
    entries = list(FIXTURE_ROOT.rglob("*"))
    files = {
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in entries if path.is_file() and not path.is_symlink()
    }
    directories = {
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in entries if path.is_dir() and not path.is_symlink()
    }
    if (files != set(FIXTURE_FILES)
            or directories != {".claude-plugin", "agents"}
            or any(path.is_symlink() for path in entries)
            or any(not (_ordinary_file(path) or _ordinary_directory(path))
                   for path in entries)):
        raise ProbeError("public subagent probe fixture topology drifted")
    try:
        manifest = runner._json_without_duplicate_keys(
            runner.read_input_bytes(
                FIXTURE_ROOT / ".claude-plugin" / "plugin.json",
                "subagent probe plugin manifest"),
            "subagent probe plugin manifest")
        agent_text = runner.read_input_bytes(
            FIXTURE_ROOT / "agents" / "model-probe-child.md",
            "subagent probe child fixture").decode("utf-8")
    except (UnicodeDecodeError, runner.InfraFailure) as exc:
        raise ProbeError("public subagent probe fixture is invalid") from exc
    if manifest != {
            "name": "rpa-subagent-model-probe",
            "version": "1.0.0",
            "description": "Public synthetic subagent model override probe",
    }:
        raise ProbeError("public subagent probe plugin manifest drifted")
    if ("name: model-probe-child" not in agent_text
            or f"model: {FIXTURE_DECLARED_MODEL}" not in agent_text
            or CHILD_MARKER not in agent_text):
        raise ProbeError("public subagent probe child fixture drifted")
    digest = runner.hash_tree(FIXTURE_ROOT)
    if digest != FIXTURE_SHA256:
        raise ProbeError("public subagent probe fixture bytes or modes drifted")
    return digest


def _execution_identity(config):
    pin_problems = operator_contract.live_probe_config_problems(config)
    if pin_problems:
        raise ProbeError("subagent-model probe config differs from registered pins")
    canonical_output_dir(config)
    if config.get("protocol_version") != runner.PILOT_V2_PROTOCOL_VERSION:
        raise ProbeError("subagent-model probe requires protocol_version 2")
    if (pilot_registration.MODEL != EXPECTED_MODEL
            or pilot_registration.EFFORT != EXPECTED_EFFORT
            or pilot_registration.SUBAGENT_MODEL_ENV != SUBAGENT_MODEL_ENV
            or pilot_registration.SUBAGENT_MODEL_LIVE_PROBE_VERSION
            != PROBE_VERSION):
        raise ProbeError("public model/effort registration differs from probe")
    backend_cmd = config.get("backend_cmd")
    if not isinstance(backend_cmd, list) or not backend_cmd:
        raise ProbeError("subagent-model probe requires backend_cmd")
    if not any("{installation}" in part for part in backend_cmd):
        raise ProbeError("subagent-model probe requires a public plugin mount")
    try:
        runner.require_effort_pin(backend_cmd, "backend_cmd")
        runner.refuse_v2_structured_output_override(backend_cmd)
        runner.validate_timeout(config)
    except runner.InfraFailure as exc:
        raise ProbeError("subagent-model probe command is invalid") from exc
    if not config.get("sandbox_cmd"):
        raise ProbeError("subagent-model probe requires sandbox_cmd")
    sandbox_issue = operator_contract.sandbox_problem(config["sandbox_cmd"])
    if sandbox_issue:
        raise ProbeError("subagent-model probe sandbox differs from registration")
    wrapper = Path(config["sandbox_cmd"][1])
    probe_path = Path(__file__).resolve()
    if not _ordinary_file(wrapper) or not _ordinary_file(probe_path):
        raise ProbeError("subagent-model probe code or sandbox is unsafe")
    fixture_sha256 = _fixture_sha256()

    identity_config = json.loads(json.dumps(config))
    for field in PROSPECTIVE_CONFIG_FIELDS:
        identity_config.pop(field, None)
    material = {
        "probe_version": PROBE_VERSION,
        "validation_policy": VALIDATION_POLICY,
        "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
        "environment_policy_id": runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
        "runtime_pins": runner.protocol_v2_runtime_pins(config),
        "backend_cmd": backend_cmd,
        "backend_version": config.get("backend_version"),
        "backend_version_cmd": config.get("backend_version_cmd"),
        "expected_model": EXPECTED_MODEL,
        "expected_effort": EXPECTED_EFFORT,
        "subagent_model_environment": {
            "name": SUBAGENT_MODEL_ENV,
            "value": EXPECTED_MODEL,
        },
        "subagent_model_policy": dict(
            pilot_registration.SUBAGENT_MODEL_POLICY),
        "expected_subagent_type": EXPECTED_SUBAGENT_TYPE,
        "fixture_declared_model": FIXTURE_DECLARED_MODEL,
        "fixture_sha256": fixture_sha256,
        "prompt_sha256": _sha256_bytes(PUBLIC_PROMPT.encode("utf-8")),
        "child_task_prompt_sha256": _sha256_bytes(
            CHILD_TASK_PROMPT.encode("utf-8")),
        "child_marker_sha256": _sha256_bytes(CHILD_MARKER.encode("utf-8")),
        "parent_marker_sha256": _sha256_bytes(PARENT_MARKER.encode("utf-8")),
        "profile_settings": PROBE_SETTINGS,
        "timeout_seconds": config.get("timeout_seconds"),
        "sandbox_cmd": config["sandbox_cmd"],
        "sandbox_wrapper_sha256": _file_sha256(wrapper),
        "probe_sha256": _file_sha256(probe_path),
        "runner_sha256": _file_sha256(HERE / "runner.py"),
        "operator_contract_sha256": _file_sha256(HERE / "step5_operator.py"),
        "registered_config": identity_config,
    }
    execution_sha256 = _sha256_bytes(json.dumps(
        material, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    return {
        **material,
        "execution_sha256": execution_sha256,
    }


def _strict_events(raw_text):
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ProbeError("subagent-model probe emitted no stream")
    events = []
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        try:
            event = runner._json_without_duplicate_keys(
                line.encode("utf-8"), "subagent probe stream event")
        except (json.JSONDecodeError, runner.InfraFailure) as exc:
            raise ProbeError("subagent-model probe stream is not strict JSONL") \
                from exc
        if not isinstance(event, dict):
            raise ProbeError("subagent-model probe stream event is not an object")
        events.append(event)
    if not events:
        raise ProbeError("subagent-model probe emitted no stream events")
    return events


def _validated_observation(raw_text, config):
    events = _strict_events(raw_text)
    session_id = None
    init_models = []
    nodes = []
    task_launches = []
    child_ids = set()
    child_texts = []
    parent_texts = []
    result_events = []
    unexpected_tools = []

    for event in events:
        if "session_id" in event:
            candidate = event["session_id"]
            if not isinstance(candidate, str) or not candidate.strip():
                raise ProbeError("subagent-model probe has invalid session identity")
            if session_id is None:
                session_id = candidate
            elif candidate != session_id:
                raise ProbeError("subagent-model probe mixes session identities")

        if event.get("type") == "system" and event.get("subtype") == "init":
            model = event.get("model")
            if not isinstance(model, str) or not model:
                raise ProbeError("subagent-model probe init lacks a model")
            init_models.append(model)
        if event.get("type") == "result":
            result_events.append(event)
        if event.get("type") != "assistant":
            continue

        message = event.get("message")
        if not isinstance(message, dict):
            raise ProbeError("subagent-model probe assistant message is invalid")
        content = message.get("content")
        if (not isinstance(content, list)
                or any(not isinstance(block, dict) for block in content)):
            raise ProbeError("subagent-model probe assistant content is invalid")
        parent_id = event.get("parent_tool_use_id")
        if parent_id is not None and (
                not isinstance(parent_id, str) or not parent_id):
            raise ProbeError("subagent-model probe child identity is invalid")

        # Client-generated synthetic notices are not model evidence, but a
        # synthetic notice must not be allowed to smuggle launch evidence.
        synthetic = message.get("model") == "<synthetic>"
        for block in content:
            if block.get("type") == "tool_use":
                if (not synthetic and parent_id is None
                        and block.get("name") == "Task"):
                    task_launches.append(block)
                else:
                    unexpected_tools.append(block.get("name"))
            elif not synthetic and block.get("type") == "text":
                text = block.get("text")
                if not isinstance(text, str):
                    raise ProbeError("subagent-model probe text is invalid")
                if text:
                    if parent_id is None:
                        parent_texts.append(text)
                    else:
                        child_texts.append(text)
        if synthetic:
            continue
        try:
            node = runner._node_from_event(event)
        except runner.InfraFailure as exc:
            raise ProbeError("subagent-model probe accounting event is invalid") \
                from exc
        if node is None:
            raise ProbeError("subagent-model probe lost a model-bearing node")
        nodes.append(node)
        if parent_id is not None:
            child_ids.add(parent_id)

    if session_id is None:
        raise ProbeError("subagent-model probe stream has no session identity")
    if init_models != [EXPECTED_MODEL]:
        raise ProbeError("subagent-model probe init model differs from registration")
    if len(result_events) != 1:
        raise ProbeError("subagent-model probe requires one terminal result")
    terminal = result_events[0]
    if (terminal.get("subtype") != "success"
            or ("is_error" in terminal
                and terminal.get("is_error") is not False)):
        raise ProbeError(
            "subagent-model probe requires a successful terminal result")
    result = terminal.get("result")
    if result != PARENT_MARKER or parent_texts != [PARENT_MARKER]:
        raise ProbeError("subagent-model probe parent marker is invalid")
    if unexpected_tools:
        raise ProbeError("subagent-model probe used an unregistered tool")
    if len(task_launches) != 1:
        raise ProbeError("subagent-model probe requires exactly one Task launch")

    task_launch = task_launches[0]
    task_id = task_launch.get("id")
    task_input = task_launch.get("input")
    if (not isinstance(task_id, str) or not task_id
            or not isinstance(task_input, dict)
            or task_input.get("subagent_type") != EXPECTED_SUBAGENT_TYPE):
        raise ProbeError("subagent-model probe launched the wrong custom agent")
    child_prompt = task_input.get("prompt")
    if child_prompt != CHILD_TASK_PROMPT:
        raise ProbeError("subagent-model probe Task prompt is invalid")
    if child_ids != {task_id}:
        raise ProbeError("subagent-model probe parent/child lineage is invalid")
    if child_texts != [CHILD_MARKER]:
        raise ProbeError("subagent-model probe child marker is invalid")

    main_nodes = [node for node in nodes if not node["subagent"]]
    child_nodes = [node for node in nodes if node["subagent"]]
    if not main_nodes or not child_nodes:
        raise ProbeError("subagent-model probe lacks parent or child evidence")
    try:
        runner.validate_models(nodes, EXPECTED_MODEL)
        effort_capture = runner.validate_efforts(nodes, EXPECTED_EFFORT)
        accounting = runner.account(nodes)
    except (TypeError, runner.InfraFailure) as exc:
        raise ProbeError("subagent-model probe runtime parity is invalid") from exc
    if (accounting.get("subagent_launches") != 1
            or accounting.get("subagent_children") != 1
            or accounting.get("subagents_spawned") != 1):
        raise ProbeError("subagent-model probe delegation accounting is invalid")
    for bucket in ("main", "subagents"):
        usage = accounting.get(bucket, {})
        if (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                <= 0):
            raise ProbeError("subagent-model probe lacks positive model usage")

    return {
        "session_id": session_id,
        "backend_version_observed": config.get("backend_version"),
        "validation_policy": VALIDATION_POLICY,
        "expected_subagent_type": EXPECTED_SUBAGENT_TYPE,
        "fixture_declared_model": FIXTURE_DECLARED_MODEL,
        "environment_override": {
            "name": SUBAGENT_MODEL_ENV,
            "value": EXPECTED_MODEL,
        },
        "reported_models": {
            "parent": sorted({node["model"] for node in main_nodes}),
            "child": sorted({node["model"] for node in child_nodes}),
        },
        "node_counts": {
            "parent": len(main_nodes),
            "child": len(child_nodes),
        },
        "lineage": {
            "task_launches": accounting["subagent_launches"],
            "child_identities": accounting["subagent_children"],
            "task_tool_use_id_sha256": _sha256_bytes(task_id.encode("utf-8")),
        },
        "effort_capture": effort_capture,
        "accounting": accounting,
        "prompt_sha256": _sha256_bytes(PUBLIC_PROMPT.encode("utf-8")),
        "task_prompt_sha256": _sha256_bytes(child_prompt.encode("utf-8")),
        "child_response_sha256": _sha256_bytes(CHILD_MARKER.encode("utf-8")),
        "parent_response_sha256": _sha256_bytes(PARENT_MARKER.encode("utf-8")),
    }


def _load_receipt(path):
    try:
        data = runner.read_input_bytes(path, "subagent-model probe receipt")
        receipt = runner._json_without_duplicate_keys(
            data, "subagent-model probe receipt")
    except (json.JSONDecodeError, runner.InfraFailure) as exc:
        raise ProbeError("subagent-model probe receipt is invalid") from exc
    if not isinstance(receipt, dict):
        raise ProbeError("subagent-model probe receipt is not an object")
    return receipt


def _freeze_namespace(output, expected_names=None):
    """Make successful or partial one-shot evidence read-only and durable."""
    output = Path(output)
    try:
        names = {path.name for path in output.iterdir()}
        if expected_names is not None and names != set(expected_names):
            raise ProbeError("subagent-model probe output set is not canonical")
        for path in output.iterdir():
            if not _ordinary_file(path):
                raise ProbeError("subagent-model probe evidence is unsafe")
            path.chmod(0o400)
            if not _ordinary_file(path, mode=0o400):
                raise ProbeError("subagent-model probe evidence is not read-only")
            descriptor = os.open(
                path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        output.chmod(0o500)
        descriptor = os.open(
            output,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ProbeError("cannot freeze subagent-model probe evidence") from exc


def verify_receipt(config, probe_backend=True):
    output = canonical_output_dir(config)
    if not _ordinary_directory(output, mode=0o500):
        raise ProbeError("subagent-model probe namespace is missing or mutable")
    allowed_names = {RECEIPT_NAME, RAW_NAME}
    try:
        paths = list(output.iterdir())
    except OSError as exc:
        raise ProbeError("subagent-model probe namespace is unreadable") from exc
    if ({path.name for path in paths} != allowed_names
            or any(not _ordinary_file(path, mode=0o400) for path in paths)):
        raise ProbeError("subagent-model probe namespace is not canonical")

    receipt_path = output / RECEIPT_NAME
    raw_path = output / RAW_NAME
    receipt = _load_receipt(receipt_path)
    if set(receipt) != {"identity", "observation", "recorded_at"}:
        raise ProbeError("subagent-model probe receipt has an invalid shape")
    if receipt.get("identity") != _execution_identity(config):
        raise ProbeError("subagent-model probe receipt identity drifted")
    if probe_backend:
        try:
            runner.verify_backend_version(config)
        except runner.InfraFailure as exc:
            raise ProbeError("subagent-model probe backend version drifted") from exc

    try:
        raw_bytes = runner.read_input_bytes(
            raw_path, "subagent-model probe raw stream")
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProbeError("subagent-model probe raw stream is not UTF-8") from exc
    except runner.InfraFailure as exc:
        raise ProbeError("subagent-model probe raw stream is unsafe") from exc
    observation = _validated_observation(raw_text, config)
    observation.update({
        "raw_stream": RAW_NAME,
        "raw_stream_bytes": len(raw_bytes),
        "raw_stream_sha256": _sha256_bytes(raw_bytes),
    })
    if receipt.get("observation") != observation:
        raise ProbeError("subagent-model probe receipt does not match raw stream")
    return receipt


def run_probe(config):
    output = canonical_output_dir(config)
    identity = _execution_identity(config)
    try:
        os.mkdir(output, 0o700)
    except FileExistsError:
        return verify_receipt(config)
    except OSError as exc:
        raise ProbeError("cannot create subagent-model probe namespace") from exc

    workspace = None
    try:
        try:
            backend_version = runner.verify_backend_version(config)
        except runner.InfraFailure as exc:
            raise ProbeError("subagent-model probe backend version is invalid") \
                from exc
        if backend_version != identity["backend_version"]:
            raise ProbeError("subagent-model probe backend version drifted")

        workspace = Path(tempfile.mkdtemp(prefix="rpa-subagent-model-probe-"))
        profile, mount = runner.make_profile(
            workspace, "subagent-model-probe",
            installation_dir=FIXTURE_ROOT, settings=PROBE_SETTINGS)
        if runner.hash_tree(mount) != identity["fixture_sha256"]:
            raise ProbeError("mounted public subagent probe fixture drifted")
        workdir = workspace / "workdir"
        workdir.mkdir()
        expanded = runner.expand_backend_cmd(
            config["backend_cmd"], mount, EXPECTED_EFFORT)
        expanded = runner.with_stream_json_transport(expanded)
        command = runner.apply_sandbox(
            config, expanded, workdir, profile)
        if any(PUBLIC_PROMPT in part for part in command):
            raise ProbeError("subagent-model probe prompt entered argv")
        # The shared environment constructor sets, rather than inherits, the
        # registered pin. The fixture deliberately declares `model: sonnet`,
        # so a child reporting Opus causally exercises precedence rather than
        # merely inheriting the parent's model.
        env = runner.backend_env(
            profile, runner.PILOT_V2_PROTOCOL_VERSION,
            subagent_model=EXPECTED_MODEL)

        temporary_sidecar = output / f".{RAW_NAME}.capture"
        (raw_text, raw_bytes, raw_digest, launch_defects,
         external) = runner.spawn_judge_session_capped(
             command, PUBLIC_PROMPT, workdir, env,
             config["timeout_seconds"], temporary_sidecar,
             runner.PILOT_V2_MAX_RAW_STREAM_BYTES)
        # The capped helper keeps oversized/non-UTF-8 bytes in its sidecar.
        # Persist bounded UTF-8 bytes here even when the backend later proves
        # unsuccessful, so every started call leaves immutable raw evidence.
        if raw_text is not None:
            raw_data = raw_text.encode("utf-8")
            if (len(raw_data) != raw_bytes
                    or _sha256_bytes(raw_data) != raw_digest):
                raise ProbeError("subagent-model probe stream digest mismatch")
            runner.atomic_write_text(output / RAW_NAME, raw_text)
        if launch_defects or external or raw_text is None:
            raise ProbeError("subagent-model probe transport failed")

        observation = _validated_observation(raw_text, config)
        observation.update({
            "raw_stream": RAW_NAME,
            "raw_stream_bytes": raw_bytes,
            "raw_stream_sha256": raw_digest,
        })
        receipt = {
            "identity": identity,
            "observation": observation,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        runner.atomic_write_text(
            output / RECEIPT_NAME,
            json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        _freeze_namespace(output, {RAW_NAME, RECEIPT_NAME})
        return verify_receipt(config)
    except BaseException:
        # Preserve every bounded raw/partial capture that exists.  The missing
        # valid receipt keeps this namespace permanently non-rerunnable.
        try:
            if _ordinary_directory(output):
                _freeze_namespace(output)
        except (OSError, ProbeError):
            pass
        raise
    finally:
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)


def receipt_sha256(config):
    return _file_sha256(canonical_output_dir(config) / RECEIPT_NAME)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", required=True,
        help="filled runner config for holdout-v2-round10")
    parser.add_argument(
        "--verify", action="store_true",
        help="only revalidate the immutable existing receipt")
    args = parser.parse_args()
    try:
        config = runner.load_config(args.config)
        receipt = (verify_receipt(config) if args.verify
                   else run_probe(config))
    except (OSError, ProbeError, runner.InfraFailure):
        print("subagent-model-live-probe: STOP", file=sys.stderr)
        return 1
    print(
        "subagent-model-live-probe: OK — "
        f"receipt_sha256={receipt_sha256(config)} "
        f"execution_sha256={receipt['identity']['execution_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
