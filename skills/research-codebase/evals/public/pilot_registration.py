#!/usr/bin/env python3
"""Single public authority for the standard protocol-v2 pilot runtime.

Private paths are deliberately absent.  The live-probe and package digests
are prospective registrations: only the public probe may run while those
sentinels are pending; every schedule/run/score entry point fails closed.
"""

import hashlib
import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


FROZEN_CANDIDATE_SHA = "b731f06cdff5f38c0fa4c5aa64f93277d69e741d"
PROTOCOL_VERSION = 2
NONSTANDARD_CONFIG = False
MAX_INFRA_RETRIES = 2
MAX_JUDGE_ATTEMPTS = 3
TIMEOUT_SECONDS = 3600
SCHEDULE_SEED = 20260801
SCORER_SEED = 20260802
VERIFIER_SEED = 20260803

HOLDOUT_TASKS = tuple(f"holdout-v2-{number}.md" for number in range(1, 7))
ABLATION_TASKS = (HOLDOUT_TASKS[0], HOLDOUT_TASKS[2])
ARM_NAMES = ("baseline", "candidate", "ablation")
INSTALL_SHA256 = {
    "baseline":
        "2762bf04e9ea82fec520906a0db0382eadff5c99cada5b44ba2f1c49a3e7b28c",
    "candidate":
        "5638b81633610a68192cc5d03dba4d1022175aa1980b27a209b3114d4c4d126c",
    "ablation":
        "a1d44b131ebd5d858756280454b9f7f33cb79a4f13d034b2004d5993b21e9b57",
}
MODEL = "claude-opus-5"
EFFORT = "high"
ENTRYPOINT = "/rpa:research_codebase"

BACKEND_CMD = (
    "claude", "--model", MODEL, "--effort", "{effort}",
    "--plugin-dir", "{installation}", "--permission-mode",
    "acceptEdits", "--verbose",
)
BACKEND_VERSION = "2.1.220 (Claude Code)"
BACKEND_VERSION_CMD = ("claude", "--version")
JUDGE_BACKEND_CMD = (
    "claude", "--model", MODEL, "--effort", "{effort}",
)
JUDGE_MODEL = MODEL
JUDGE_EFFORT = EFFORT
WORKFLOW_ABORT_EXIT_CODES = ()
DRIFT_FETCH_CMD = (
    "curl", "-q", "-fsSL", "--config", "-", "-o", "{dest}",
)

OPERATOR_IMAGE_SHA256 = (
    "sha256:bbe9dbf152c933f4c3a69eae0809983cf698253a7a067fd6b73180ecc85c4975"
)
ARTIFACT_PARSER = "pyyaml"
ARTIFACT_PARSER_VERSION = "6.0.2"
ENVIRONMENT_POLICY_ID = (
    "claude-cli-minimal-env-v4-sync-agents-pyyaml-6.0.2"
)
SUBAGENT_MODEL_ENV = "CLAUDE_CODE_SUBAGENT_MODEL"
SUBAGENT_MODEL_POLICY_ID = "registered-session-model-v1"
SUBAGENT_MODEL_POLICY = {
    "id": SUBAGENT_MODEL_POLICY_ID,
    "environment_variable": SUBAGENT_MODEL_ENV,
    "source": "registered-session-model",
}
BACKGROUND_TASKS_ENV = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"
BACKGROUND_TASKS_VALUE = "1"
BACKGROUND_TASKS_POLICY = {
    "id": "registered-synchronous-agent-lifecycle-v1",
    "environment_variable": BACKGROUND_TASKS_ENV,
    "value": BACKGROUND_TASKS_VALUE,
    "source": "harness-injected",
}
SUBAGENT_MODEL_LIVE_PROBE_VERSION = "public-subagent-model-precedence-v4"
PENDING_SUBAGENT_MODEL_LIVE_PROBE_RECEIPT_SHA256 = "0" * 64
PENDING_SUBAGENT_MODEL_LIVE_PROBE_EXECUTION_SHA256 = "0" * 64
REGISTERED_SUBAGENT_MODEL_LIVE_PROBE_RECEIPT_SHA256 = (
    "d066949bf0e2adaecc1b9e737515c835f3ca7eba3b4285e1772ded6496e08d65")
REGISTERED_SUBAGENT_MODEL_LIVE_PROBE_EXECUTION_SHA256 = (
    "1fefea2f5883831a481ec30a0619003a6a36a3dd4769b6b984279854c1d0dda0")

AGENT_STREAM_ACCOUNTING_POLICY = {
    "id": "claude-cli-agent-stream-accounting-v4",
    "assistant_identity": [
        "session_id", "parent_tool_use_id", "message.id", "request_id"],
    "delegation_tools": ["Task", "Agent"],
    "root_usage_source": "terminal-result-usage-authoritative",
    "assistant_usage_role": "partial-stream-fallback-only",
    "agent_completion_usage_role": "last-child-turn-evidence-only",
    "complete_agent_usage_source": (
        "terminal-registered-model-minus-root-residual"),
    "tool_using_agent_without_terminal": "fail-closed",
    "agent_tool_stats": "typed-recursive-sidechain-exact-cli-2.1.220",
    "agent_continuation": (
        "same-agent-sendmessage-sync-branch-tools-v4"),
    "continuation_model_evidence": (
        "persisted-agent-model-plus-registered-terminal-ledger"),
    "non_agent_task_lifecycle": "correlated-observed-tool-v1",
    "registered_model_reconciliation": "exact-terminal-model-usage",
    "auxiliary_models": ["claude-haiku-4-5-20251001"],
    "canonical_models": {
        "claude-opus-5": "claude-opus-5",
        "claude-haiku-4-5-20251001": "claude-haiku-4-5",
    },
    "tree_includes_auxiliary": True,
}

SANDBOX_TAIL = (
    "--confine-to", "{workdir}", "--profile", "{profile}", "--",
)
PLATFORM_WRAPPER = {"darwin": "macos_sandbox.py"}
DEFAULT_WRAPPER = "ns_sandbox.py"
SANDBOX_WRAPPER_SHA256 = {
    "ns_sandbox.py":
        "38d4e3241810d4eb652bdede4e4ea414ab2f217b2f31b04b8e5cd11e95652ee9",
    "macos_sandbox.py":
        "7a20a2728aa5790c0878b72bb1684d2049b94adb3419ce1979eb45ad9073ef2e",
}

JUDGE_RETRY_POLICY = {
    "max_attempts": MAX_JUDGE_ATTEMPTS,
    "fresh_session_each_attempt": True,
    "repair": "none",
}
STRUCTURED_OUTPUT_SCHEMA_SHA256 = {
    "scorer":
        "ec21f5722725501edf6d29741a85e93f0ed4611d443540452a3b907e382adcc7",
    "verifier":
        "feba3d9047ff1aa9b2da959e8431e177bdf9e6117ed2ffed972772e2ebddebe0",
}
# Exact UTF-8 bytes of the deterministic, role-specific prompt tail.  These
# values are intentionally literal public registration data: step-5 checks
# the implementation-derived digests before any private task read or model
# launch, while the runtime-registration digest binds them into every seal.
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
AGGREGATION_POLICY = {
    "id": "pilot-v2-all-docs-v1",
    "telemetry": "all-final-scheduled-workflow-outcomes-v1",
    "critical": "candidate-absolute-zero-v1",
}

LIVE_PROBE_VERSION = "public-live-dual-output-v3"
PENDING_LIVE_PROBE_RECEIPT_SHA256 = "0" * 64
PENDING_LIVE_PROBE_EXECUTION_SHA256 = "0" * 64
REGISTERED_LIVE_PROBE_RECEIPT_SHA256 = (
    "93f50b576ad0287d0d808fead53b29609539342d2b6d5e28de43df92fd7a5612")
REGISTERED_LIVE_PROBE_EXECUTION_SHA256 = (
    "d12675be2a4093194667ab27a4a4b30595e6d6dd3591b0b5e709df9bd0a23de1")

PENDING_SEAL_PACKAGE_SHA256 = "0" * 64
REGISTERED_SEAL_PACKAGE_SHA256 = PENDING_SEAL_PACKAGE_SHA256


def live_probe_binding():
    return {
        "probe_version": LIVE_PROBE_VERSION,
        "receipt_sha256": REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
        "execution_sha256": REGISTERED_LIVE_PROBE_EXECUTION_SHA256,
    }


def live_probe_registration_pending():
    binding = live_probe_binding()
    return (
        binding["receipt_sha256"] == PENDING_LIVE_PROBE_RECEIPT_SHA256
        or binding["execution_sha256"]
        == PENDING_LIVE_PROBE_EXECUTION_SHA256
    )


def subagent_model_live_probe_binding():
    return {
        "probe_version": SUBAGENT_MODEL_LIVE_PROBE_VERSION,
        "receipt_sha256":
            REGISTERED_SUBAGENT_MODEL_LIVE_PROBE_RECEIPT_SHA256,
        "execution_sha256":
            REGISTERED_SUBAGENT_MODEL_LIVE_PROBE_EXECUTION_SHA256,
    }


def subagent_model_live_probe_registration_pending():
    binding = subagent_model_live_probe_binding()
    return (
        binding["receipt_sha256"]
        == PENDING_SUBAGENT_MODEL_LIVE_PROBE_RECEIPT_SHA256
        or binding["execution_sha256"]
        == PENDING_SUBAGENT_MODEL_LIVE_PROBE_EXECUTION_SHA256
    )


def seal_registration_pending():
    return REGISTERED_SEAL_PACKAGE_SHA256 == PENDING_SEAL_PACKAGE_SHA256


def standard_v2_runtime_binding():
    """Return the canonical path-free registration embedded in every seal."""
    return {
        "registration_version": "standard-v2-runtime-v4",
        "frozen_candidate_sha": FROZEN_CANDIDATE_SHA,
        "protocol_version": PROTOCOL_VERSION,
        "nonstandard_config": NONSTANDARD_CONFIG,
        "arms": {
            arm: {
                "sha256": INSTALL_SHA256[arm],
                "model": MODEL,
                "effort": EFFORT,
                "entrypoint": ENTRYPOINT,
                **({
                    "forbid_subagents": True,
                    "schedule_tasks": list(ABLATION_TASKS),
                } if arm == "ablation" else {}),
            }
            for arm in ARM_NAMES
        },
        "backend_cmd": list(BACKEND_CMD),
        "backend_version": BACKEND_VERSION,
        "backend_version_cmd": list(BACKEND_VERSION_CMD),
        "judge_backend_cmd": list(JUDGE_BACKEND_CMD),
        "judge_model": JUDGE_MODEL,
        "judge_effort": JUDGE_EFFORT,
        "workflow_abort_exit_codes": list(WORKFLOW_ABORT_EXIT_CODES),
        "timeout_seconds": TIMEOUT_SECONDS,
        "max_infra_retries": MAX_INFRA_RETRIES,
        "max_judge_attempts": MAX_JUDGE_ATTEMPTS,
        "operator_image_sha256": OPERATOR_IMAGE_SHA256,
        "artifact_parser": ARTIFACT_PARSER,
        "artifact_parser_version": ARTIFACT_PARSER_VERSION,
        "environment_policy_id": ENVIRONMENT_POLICY_ID,
        "subagent_model_policy": dict(SUBAGENT_MODEL_POLICY),
        "background_tasks_policy": dict(BACKGROUND_TASKS_POLICY),
        "agent_stream_accounting_policy": dict(
            AGENT_STREAM_ACCOUNTING_POLICY),
        "subagent_model_live_probe": subagent_model_live_probe_binding(),
        "drift_fetch_cmd": list(DRIFT_FETCH_CMD),
        "sandbox": {
            "python_basename": "python3[.N]",
            "tail": list(SANDBOX_TAIL),
            "platform_wrapper": dict(PLATFORM_WRAPPER),
            "default_wrapper": DEFAULT_WRAPPER,
            "wrapper_sha256": dict(SANDBOX_WRAPPER_SHA256),
        },
        "seeds": {
            "schedule": SCHEDULE_SEED,
            "scorer": SCORER_SEED,
            "verifier": VERIFIER_SEED,
        },
        "judge_retry_policy": dict(JUDGE_RETRY_POLICY),
        "judge_output_policy": dict(JUDGE_OUTPUT_POLICY),
        "structured_output_schema_sha256": dict(
            STRUCTURED_OUTPUT_SCHEMA_SHA256),
        "final_response_contract_sha256": dict(
            FINAL_RESPONSE_CONTRACT_SHA256),
        "aggregation_policy": dict(AGGREGATION_POLICY),
        "judge_live_probe": live_probe_binding(),
    }


def standard_v2_runtime_registration_sha256():
    material = json.dumps(
        standard_v2_runtime_binding(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def sandbox_registration_problem(cmd, platform=None):
    """Validate the exact wrapper shape, platform selection, and bytes."""
    platform = sys.platform if platform is None else platform
    expected_name = PLATFORM_WRAPPER.get(platform, DEFAULT_WRAPPER)
    if not isinstance(cmd, list) or len(cmd) != 2 + len(SANDBOX_TAIL):
        return "`sandbox_cmd` is not the exact registered wrapper invocation"
    if not re.fullmatch(r"python3(?:\.\d+)?", Path(str(cmd[0])).name):
        return "`sandbox_cmd` does not use the registered python3 interpreter"
    resolved_interpreter = shutil.which(str(cmd[0]))
    try:
        if (resolved_interpreter is None
                or not Path(resolved_interpreter).samefile(sys.executable)):
            return ("`sandbox_cmd` interpreter is not the Python runtime "
                    "executing the registered harness")
    except OSError:
        return "`sandbox_cmd` interpreter identity cannot be verified"
    if [str(part) for part in cmd[2:]] != list(SANDBOX_TAIL):
        return "`sandbox_cmd` arguments differ from the registered wrapper tail"
    wrapper = Path(str(cmd[1]))
    try:
        info = wrapper.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_nlink != 1):
            return "`sandbox_cmd` wrapper is not a single-link ordinary file"
        digest = hashlib.sha256(wrapper.read_bytes()).hexdigest()
    except OSError:
        return "`sandbox_cmd` wrapper is missing or unreadable"
    if wrapper.name != expected_name:
        return (f"`sandbox_cmd` wrapper {wrapper.name!r} is not the registered "
                f"{expected_name!r} for {platform}")
    if digest != SANDBOX_WRAPPER_SHA256[expected_name]:
        return "`sandbox_cmd` wrapper bytes differ from the registration"
    try:
        probe = subprocess.run(
            [resolved_interpreter, str(wrapper), "--help"], capture_output=True,
            text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "`sandbox_cmd` interpreter cannot execute the registered wrapper"
    if probe.returncode != 0 or "--confine-to" not in probe.stdout:
        return "`sandbox_cmd` interpreter does not execute the wrapper interface"
    return None


def _list(value):
    return [str(item) for item in value] if isinstance(value, list) else value


def standard_v2_registration_problems(
        config, *, allow_pending_probe=False, allow_pending_seal=False,
        sandbox_problem=None):
    """Return every drift from the single standard-v2 registration.

    ``nonstandard_config: true`` is the only dev escape and is explicit in
    the resulting artifacts.  It never authorizes a standard schedule.
    """
    if not isinstance(config, dict):
        return ["standard protocol-v2 config must be an object"]
    if config.get("protocol_version") != PROTOCOL_VERSION:
        return [f"protocol_version must be exactly {PROTOCOL_VERSION}"]
    marker = config.get("nonstandard_config")
    if marker is True:
        return []
    if marker is not False:
        return [
            "protocol v2 requires explicit boolean `nonstandard_config`; "
            "generic/dev runs must set it to true"
        ]

    problems = []
    scalar_pins = {
        "backend_version": BACKEND_VERSION,
        "judge_model": JUDGE_MODEL,
        "judge_effort": JUDGE_EFFORT,
        "timeout_seconds": TIMEOUT_SECONDS,
        "max_infra_retries": MAX_INFRA_RETRIES,
        "max_judge_attempts": MAX_JUDGE_ATTEMPTS,
        "operator_image_sha256": OPERATOR_IMAGE_SHA256,
        "artifact_parser": ARTIFACT_PARSER,
        "artifact_parser_version": ARTIFACT_PARSER_VERSION,
    }
    for field, expected in scalar_pins.items():
        if config.get(field) != expected:
            problems.append(f"{field} differs from the standard-v2 registration")
    list_pins = {
        "backend_cmd": BACKEND_CMD,
        "backend_version_cmd": BACKEND_VERSION_CMD,
        "judge_backend_cmd": JUDGE_BACKEND_CMD,
        "workflow_abort_exit_codes": WORKFLOW_ABORT_EXIT_CODES,
        "drift_fetch_cmd": DRIFT_FETCH_CMD,
    }
    for field, expected in list_pins.items():
        if _list(config.get(field)) != list(expected):
            problems.append(f"{field} differs from the standard-v2 registration")

    arms = config.get("arms")
    if not isinstance(arms, dict) or set(arms) != set(ARM_NAMES):
        problems.append("arms differ from the registered baseline/candidate/ablation")
    else:
        for name in ARM_NAMES:
            arm = arms.get(name)
            if not isinstance(arm, dict):
                problems.append(f"arm `{name}` is not an object")
                continue
            expected = {
                "sha256": INSTALL_SHA256[name],
                "model": MODEL,
                "effort": EFFORT,
                "entrypoint": ENTRYPOINT,
            }
            for field, value in expected.items():
                if arm.get(field) != value:
                    problems.append(
                        f"arm `{name}` {field} differs from the registration")
            if name == "ablation":
                if arm.get("forbid_subagents") is not True:
                    problems.append("ablation must forbid subagents")
                if arm.get("schedule_tasks") != list(ABLATION_TASKS):
                    problems.append("ablation task scope differs from registration")
            elif ("forbid_subagents" in arm or "schedule_tasks" in arm):
                problems.append(
                    f"arm `{name}` carries an unregistered ablation policy")

    sandbox_check = sandbox_problem or sandbox_registration_problem
    sandbox_issue = sandbox_check(config.get("sandbox_cmd"))
    if sandbox_issue:
        problems.append(sandbox_issue)

    expected_probe = live_probe_binding()
    observed_probe = {
        "probe_version": LIVE_PROBE_VERSION,
        "receipt_sha256": config.get("judge_live_probe_receipt_sha256"),
        "execution_sha256": config.get("judge_live_probe_execution_sha256"),
    }
    if allow_pending_probe and live_probe_registration_pending():
        pending_probe = {
            "probe_version": LIVE_PROBE_VERSION,
            "receipt_sha256": PENDING_LIVE_PROBE_RECEIPT_SHA256,
            "execution_sha256": PENDING_LIVE_PROBE_EXECUTION_SHA256,
        }
        if observed_probe != pending_probe:
            problems.append("config live-probe sentinels are not exact")
    elif live_probe_registration_pending():
        problems.append("live judge probe registration is pending")
    elif observed_probe != expected_probe:
        problems.append("live judge probe differs from the registration")

    expected_subagent_probe = subagent_model_live_probe_binding()
    observed_subagent_probe = {
        "probe_version": SUBAGENT_MODEL_LIVE_PROBE_VERSION,
        "receipt_sha256": config.get(
            "subagent_model_live_probe_receipt_sha256"),
        "execution_sha256": config.get(
            "subagent_model_live_probe_execution_sha256"),
    }
    if (allow_pending_probe
            and subagent_model_live_probe_registration_pending()):
        pending_subagent_probe = {
            "probe_version": SUBAGENT_MODEL_LIVE_PROBE_VERSION,
            "receipt_sha256":
                PENDING_SUBAGENT_MODEL_LIVE_PROBE_RECEIPT_SHA256,
            "execution_sha256":
                PENDING_SUBAGENT_MODEL_LIVE_PROBE_EXECUTION_SHA256,
        }
        if observed_subagent_probe != pending_subagent_probe:
            problems.append(
                "config subagent-model live-probe sentinels are not exact")
    elif subagent_model_live_probe_registration_pending():
        problems.append("subagent-model live probe registration is pending")
    elif observed_subagent_probe != expected_subagent_probe:
        problems.append(
            "subagent-model live probe differs from the registration")

    observed_seal = config.get("seal_package_sha256")
    if allow_pending_seal and seal_registration_pending():
        if observed_seal != PENDING_SEAL_PACKAGE_SHA256:
            problems.append("config seal sentinel is not exact")
    elif seal_registration_pending():
        problems.append("seal package registration is pending")
    elif observed_seal != REGISTERED_SEAL_PACKAGE_SHA256:
        problems.append("seal_package_sha256 differs from the registration")
    return problems


def standard_v2_registration_problem(config, **kwargs):
    problems = standard_v2_registration_problems(config, **kwargs)
    return "; ".join(problems) if problems else None
