#!/usr/bin/env python3
"""One-shot public live probe for protocol-v2 structured judge output.

Run this before authoring a replacement holdout seal.  It launches exactly
one scorer and one verifier session using only synthetic public material,
persists their raw streams, and writes a receipt only after both CLI output
views independently pass the full role validator and compare equal.
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

import judge_contract  # noqa: E402
import runner  # noqa: E402
import step5_operator as operator_contract  # noqa: E402


ROLES = ("scorer", "verifier")
ROUND_NAMESPACE = "holdout-v2-round6"
PACKAGE_NAMESPACE = "package"
OUTPUT_NAMESPACE = "judge-live-probe"
RECEIPT_NAME = "judge-structured-output-live-probe.json"
RAW_NAMES = {
    role: f"judge-structured-output-{role}.jsonl" for role in ROLES
}

PUBLIC_RESPONSES = {
    "scorer": {
        "coverage": {
            "score": 3.5,
            "rationale": "The mock document covers the registered areas.",
        },
        "relevance": {
            "score": 2.5,
            "rationale": "The mock findings stay focused on the task.",
        },
        "synthesis": {
            "score": 2,
            "rationale": "The mock document connects its findings.",
        },
        "total": 8,
        "summary": "Deterministic valid scorer response.",
    },
    "verifier": {
        "verifiable_claims": 2,
        "supported_claims": 1,
        "unsupported_claims": 1,
        "unverifiable_claims": 0,
        "claim_ledger": [
            {
                "claim": "The mock file contains the cited definition.",
                "candidate_citations": ["mock/file.py:1"],
                "status": "supported",
                "evidence": ["mock/file.py:1"],
                "rationale": "The cited line supports the claim.",
            },
            {
                "claim": "The mock file contains an additional setting.",
                "candidate_citations": ["mock/file.py:2"],
                "status": "unsupported",
                "evidence": [],
                "rationale": (
                    "The cited setting is absent from frozen evidence."),
            },
        ],
        "critical_errors": [],
        "critical_error_count": 0,
        "summary": "Deterministic valid verifier response.",
    },
}


class ProbeError(RuntimeError):
    """The public live probe or its receipt is invalid."""


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path):
    try:
        data = runner.read_input_bytes(path, "live probe identity file")
    except runner.InfraFailure as exc:
        raise ProbeError(str(exc)) from exc
    return _sha256_bytes(data)


def _ordinary_file(path):
    try:
        info = Path(path).lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_nlink == 1)


def _ordinary_directory(path):
    try:
        info = Path(path).lstat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def canonical_output_dir(config):
    """Derive the sole probe namespace from the registered round seal path."""
    raw = config.get("seal_manifest")
    if not isinstance(raw, str) or not raw.strip():
        raise ProbeError("live judge probe requires seal_manifest")
    supplied_manifest = Path(raw).absolute()
    supplied_package = supplied_manifest.parent
    supplied_round = supplied_package.parent
    if (supplied_manifest.name != "seal-manifest.json"
            or supplied_package.name != PACKAGE_NAMESPACE
            or supplied_round.name != ROUND_NAMESPACE):
        raise ProbeError(
            "seal_manifest must be exactly "
            f"<private-root>/{ROUND_NAMESPACE}/{PACKAGE_NAMESPACE}/"
            "seal-manifest.json")
    if (not _ordinary_directory(supplied_round)
            or not _ordinary_directory(supplied_package)):
        raise ProbeError(
            f"the canonical {ROUND_NAMESPACE}/package directories must "
            "already exist and contain no symlink")
    manifest = supplied_manifest.resolve()
    package = manifest.parent
    round_root = package.parent
    if (package.name != PACKAGE_NAMESPACE
            or round_root.name != ROUND_NAMESPACE
            or package != supplied_package.resolve()
            or round_root != supplied_round.resolve()):
        raise ProbeError("seal_manifest canonical namespace resolves elsewhere")
    return round_root / OUTPUT_NAMESPACE


def _execution_identity(config):
    pin_problems = operator_contract.live_probe_config_problems(config)
    if pin_problems:
        raise ProbeError(
            "live judge probe config differs from registered pins: "
            + "; ".join(pin_problems))
    canonical_output_dir(config)
    if config.get("protocol_version") != runner.PILOT_V2_PROTOCOL_VERSION:
        raise ProbeError("live judge probe requires protocol_version 2")
    judge_cmd = config.get("judge_backend_cmd")
    if not isinstance(judge_cmd, list) or not judge_cmd:
        raise ProbeError("live judge probe requires judge_backend_cmd")
    if any("{installation}" in part for part in judge_cmd):
        raise ProbeError("live judge probe command must be installation-free")
    try:
        runner.require_effort_pin(judge_cmd, "judge_backend_cmd")
        runner.refuse_v2_structured_output_override(judge_cmd)
        runner.validate_timeout(config)
    except runner.InfraFailure as exc:
        raise ProbeError(str(exc)) from exc
    for key in ("judge_model", "judge_effort", "backend_version"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ProbeError(f"live judge probe requires nonempty `{key}`")
    if not config.get("sandbox_cmd"):
        raise ProbeError("live judge probe requires sandbox_cmd")
    sandbox_cmd = config["sandbox_cmd"]
    sandbox_issue = operator_contract.sandbox_problem(sandbox_cmd)
    if sandbox_issue:
        raise ProbeError(sandbox_issue)
    wrapper = Path(sandbox_cmd[1])
    if not _ordinary_file(wrapper):
        raise ProbeError(
            "live judge probe sandbox wrapper must be a single-link "
            "ordinary file")
    probe_path = Path(__file__).resolve()
    if not _ordinary_file(probe_path):
        raise ProbeError(
            "live judge probe code must be a single-link ordinary file")
    probe_sha256 = _file_sha256(probe_path)
    sandbox_wrapper_sha256 = _file_sha256(wrapper)

    # Bind the entire filled config, including arm topology/install hashes and
    # private runtime paths.  The three values that are necessarily pending
    # before this proof/seal exists are deliberately omitted to avoid a
    # circular digest; every other key (including notes) remains bound.
    identity_config = json.loads(json.dumps(config))
    for field in (
            "seal_package_sha256",
            "judge_live_probe_receipt_sha256",
            "judge_live_probe_execution_sha256"):
        identity_config.pop(field, None)
    material = {
        "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
        "environment_policy_id": runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
        "runtime_pins": runner.protocol_v2_runtime_pins(config),
        "judge_output_policy": runner.PILOT_V2_JUDGE_OUTPUT_POLICY,
        "structured_output_schema_sha256": {
            role: judge_contract.structured_output_schema_sha256(role)
            for role in ROLES
        },
        "judge_backend_cmd": judge_cmd,
        "judge_model": config["judge_model"],
        "judge_effort": config["judge_effort"],
        "backend_version": config["backend_version"],
        "backend_version_cmd": config.get("backend_version_cmd"),
        "timeout_seconds": config["timeout_seconds"],
        "sandbox_cmd": sandbox_cmd,
        "sandbox_wrapper_sha256": sandbox_wrapper_sha256,
        "probe_sha256": probe_sha256,
        "runner_sha256": _file_sha256(HERE / "runner.py"),
        "judge_contract_sha256": _file_sha256(HERE / "judge_contract.py"),
        "registered_config": identity_config,
    }
    return {
        "probe_version": runner.PILOT_V2_LIVE_PROBE_VERSION,
        "execution_sha256": _sha256_bytes(json.dumps(
            material, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")),
        "judge_output_policy": runner.PILOT_V2_JUDGE_OUTPUT_POLICY,
        "runtime_pins": runner.protocol_v2_runtime_pins(config),
        "probe_sha256": probe_sha256,
        "sandbox_wrapper_sha256": sandbox_wrapper_sha256,
        "structured_output_schema_sha256": material[
            "structured_output_schema_sha256"],
        "judge_model": config["judge_model"],
        "judge_effort": config["judge_effort"],
        "backend_version": config["backend_version"],
    }


def _public_prompt(role):
    expected = json.dumps(
        PUBLIC_RESPONSES[role], ensure_ascii=False, sort_keys=True)
    marker = "VERIFIER-CONTRACT" if role == "verifier" else "SCORER-CONTRACT"
    return runner.compose_v2_judge_prompt(
        (
            f"{marker}\nThis is a public transport probe, not an evaluation. "
            "Return the exact synthetic object supplied below."
        ),
        "Public probe rubric: exact reproduction is the only criterion.",
        json.dumps(judge_contract.contract_schema(role), sort_keys=True),
        "Expected public synthetic object:\n" + expected,
        "# Public probe document\n\nPROBE-STRUCTURED-OUTPUT\n",
    )


def _validated_observation(role, raw_text, config):
    (session_id, nodes, response, structured_output,
     defects) = runner._parse_judge_stream_tolerant(
         raw_text, require_structured_output=True)
    if not defects:
        try:
            runner.validate_models(nodes, config["judge_model"])
            effort_capture = runner.validate_efforts(
                nodes, config["judge_effort"])
        except runner.InfraFailure as exc:
            defects.append(f"runtime parity: {exc}")
            effort_capture = None
    else:
        effort_capture = None
    parsed = None
    if not defects:
        parsed, pair_defects = runner._validate_v2_judge_response_pair(
            response, structured_output, role)
        defects.extend(pair_defects)
    expected = judge_contract.validate_response(
        json.dumps(PUBLIC_RESPONSES[role]), role)
    if parsed is not None and parsed != expected:
        defects.append(
            "validated response differs from the exact public probe object")
    if defects:
        raise ProbeError(f"{role} live probe invalid: {'; '.join(defects)}")
    accounting = runner.account(nodes)
    if (accounting["tree"]["input_tokens"]
            + accounting["tree"]["output_tokens"] <= 0):
        raise ProbeError(f"{role} live probe has no positive token usage")
    return {
        "role": role,
        "session_id": session_id,
        "backend_version_observed": config["backend_version"],
        "structured_output_schema_sha256": (
            judge_contract.structured_output_schema_sha256(role)),
        "prompt_sha256": _sha256_bytes(
            _public_prompt(role).encode("utf-8")),
        "response_sha256": _sha256_bytes(response.encode("utf-8")),
        "parsed_response_sha256": _sha256_bytes(json.dumps(
            parsed, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")
        ).encode("utf-8")),
        "effort_capture": effort_capture,
        "accounting": accounting,
    }


def verify_receipt(config, probe_backend=True):
    output = canonical_output_dir(config)
    if not _ordinary_directory(output):
        raise ProbeError("live judge probe output namespace is missing or unsafe")
    receipt_path = output / RECEIPT_NAME
    if not _ordinary_file(receipt_path):
        raise ProbeError("live judge probe receipt is missing or unsafe")
    try:
        receipt = runner.load_json_object(receipt_path, "live judge probe receipt")
    except runner.InfraFailure as exc:
        raise ProbeError(str(exc)) from exc
    if set(receipt) != {"identity", "observations", "recorded_at"}:
        raise ProbeError("live judge probe receipt has an invalid shape")
    if receipt.get("identity") != _execution_identity(config):
        raise ProbeError("live judge probe receipt identity drifted")
    if probe_backend:
        try:
            runner.verify_backend_version(config)
        except runner.InfraFailure as exc:
            raise ProbeError(str(exc)) from exc
    observations = receipt.get("observations")
    if not isinstance(observations, dict) or set(observations) != set(ROLES):
        raise ProbeError("live judge probe receipt has incomplete roles")
    allowed_names = {RECEIPT_NAME, *RAW_NAMES.values()}
    if ({path.name for path in output.iterdir()} != allowed_names
            or any(not _ordinary_file(path) for path in output.iterdir())):
        raise ProbeError("live judge probe output namespace is not canonical")
    for role in ROLES:
        raw_path = output / RAW_NAMES[role]
        try:
            raw_bytes = runner.read_input_bytes(
                raw_path, f"{role} live probe raw stream")
        except runner.InfraFailure as exc:
            raise ProbeError(str(exc)) from exc
        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProbeError(f"{role} raw stream is not UTF-8") from exc
        observed = _validated_observation(role, raw_text, config)
        observed.update({
            "raw_stream": RAW_NAMES[role],
            "raw_stream_bytes": len(raw_bytes),
            "raw_stream_sha256": _sha256_bytes(raw_bytes),
        })
        if observations.get(role) != observed:
            raise ProbeError(f"{role} live probe receipt does not match raw stream")
    return receipt


def run_probe(config):
    output = canonical_output_dir(config)
    receipt_path = output / RECEIPT_NAME
    identity = _execution_identity(config)
    try:
        os.mkdir(output, 0o700)
    except FileExistsError:
        # Existence is an irreversible launch claim.  A complete valid
        # receipt may be revalidated, but no missing/tampered/partial state
        # ever authorizes another nondeterministic backend observation.
        return verify_receipt(config)
    except OSError as exc:
        raise ProbeError("cannot create canonical live probe namespace") from exc
    observations = {}
    expanded = runner.expand_backend_cmd(
        config["judge_backend_cmd"], None, config["judge_effort"])
    expanded = runner.with_stream_json_transport(expanded)
    for role in ROLES:
        try:
            backend_version = runner.verify_backend_version(config)
        except runner.InfraFailure as exc:
            raise ProbeError(str(exc)) from exc
        if backend_version != identity["backend_version"]:
            raise ProbeError(
                f"{role} live judge probe backend version drifted")
        workspace = Path(tempfile.mkdtemp(prefix=f"rpa-{role}-probe-"))
        try:
            settings = (runner.VERIFIER_SETTINGS
                        if role == "verifier" else runner.JUDGE_SETTINGS)
            profile, _mount = runner.make_profile(
                workspace, "judge-probe", settings=settings)
            workdir = workspace / "workdir"
            workdir.mkdir()
            command = runner.apply_sandbox(
                config, expanded, workdir, profile)
            env = runner.backend_env(
                profile, runner.PILOT_V2_PROTOCOL_VERSION)
            temporary_sidecar = output / f".{RAW_NAMES[role]}.capture"
            (raw_text, raw_bytes, raw_digest, launch_defects,
             external) = runner.spawn_judge_session_capped(
                 command, _public_prompt(role), workdir, env,
                 config["timeout_seconds"], temporary_sidecar,
                 runner.PILOT_V2_MAX_RAW_STREAM_BYTES,
                 structured_output_schema=(
                     judge_contract.structured_output_schema_text(role)))
            if launch_defects or external or raw_text is None:
                detail = "; ".join(launch_defects) or "external raw stream"
                raise ProbeError(f"{role} live probe transport invalid: {detail}")
            raw_data = raw_text.encode("utf-8")
            if len(raw_data) != raw_bytes or _sha256_bytes(raw_data) != raw_digest:
                raise ProbeError(f"{role} live probe stream digest mismatch")
            raw_path = output / RAW_NAMES[role]
            runner.atomic_write_text(raw_path, raw_text)
            observation = _validated_observation(role, raw_text, config)
            observation.update({
                "raw_stream": RAW_NAMES[role],
                "raw_stream_bytes": raw_bytes,
                "raw_stream_sha256": raw_digest,
            })
            observations[role] = observation
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    receipt = {
        "identity": identity,
        "observations": observations,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    runner.atomic_write_text(
        receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return verify_receipt(config)


def receipt_sha256(config):
    receipt_path = canonical_output_dir(config) / RECEIPT_NAME
    return _file_sha256(receipt_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True,
                        help="filled runner config for holdout-v2-round6")
    parser.add_argument("--verify", action="store_true",
                        help="only revalidate an existing receipt")
    args = parser.parse_args()
    try:
        config = runner.load_config(args.config)
        if args.verify:
            receipt = verify_receipt(config)
        else:
            receipt = run_probe(config)
    except (OSError, ProbeError, runner.InfraFailure) as exc:
        print(f"judge-live-probe: STOP — {exc}", file=sys.stderr)
        return 1
    print("judge-live-probe: OK — "
          f"receipt_sha256={receipt_sha256(config)} "
          f"execution_sha256={receipt['identity']['execution_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
