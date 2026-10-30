#!/usr/bin/env python3
"""Validate recipes/*/recipe.yaml against recipe.schema.yaml.

Usage:
  python scripts/validate_manifests.py                 # every recipe
  python scripts/validate_manifests.py recipes/08-x    # just these folders

Checks, per recipe:
  1. recipe.yaml exists and passes the JSON Schema.
  2. id equals the folder name (recipes/_template must use id 00-template).
  3. Every *known* primitive is actually used in the recipe's Python code.
Exit code 1 on any error.
"""
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = yaml.safe_load((ROOT / "recipe.schema.yaml").read_text())

# primitive name -> regex that must appear in the recipe's *.py files (tests excluded)
KNOWN_PRIMITIVES = {
    "contexts-steps": r"define_contexts\(",
    "set_functions": r"\.set_functions\(",
    "valid_steps": r"set_valid_steps\(|valid_steps=",
    "valid_contexts": r"set_valid_contexts\(",
    "isolated-contexts": r"set_isolated\(",
    "gather": r"set_gather_info\(|add_gather_question\(",
    "swml_change_step": r"swml_change_step\(",
    "swml_change_context": r"swml_change_context\(",
    "global_data": r"global_data",
    "datamap": r"DataMap\(",
    "dynamic-config": r"set_dynamic_config_callback\(",
    "post_prompt": r"set_post_prompt\(|on_summary\(",
    "add_language": r"add_language\(",
    "native_vector_search": r"native_vector_search",
    "custom-skill": r"SkillBase",
    "prefab": r"from signalwire\.prefabs|signalwire\.prefabs",
    "mcp-client": r"add_mcp_server\(",
    "mcp-server": r"enable_mcp_server\(",
    "pay": r"\.pay\(",
    "record_call": r"record_call\(",
    "rpc_dial": r"rpc_dial\(",
    "rpc_ai_message": r"rpc_ai_message\(",
    "swml_transfer": r"swml_transfer\(",
    "connect": r"\.connect\(",
    "send_sms": r"send_sms\(|messages\.create\(",
    "toggle_functions": r"toggle_functions\(",
    "rest-dial": r"calling\.dial\(",
    "agent-server": r"AgentServer\(",
    "set_prompt_llm_params": r"set_prompt_llm_params\(",
}


def recipe_code(folder: Path) -> str:
    files = [p for p in folder.rglob("*.py") if "tests" not in p.parts and ".venv" not in p.parts]
    return "\n".join(p.read_text(errors="ignore") for p in files)


def validate(folder: Path) -> list[str]:
    errors = []
    manifest = folder / "recipe.yaml"
    if not manifest.is_file():
        return [f"{folder}: missing recipe.yaml"]
    try:
        data = yaml.safe_load(manifest.read_text())
    except yaml.YAMLError as exc:
        return [f"{manifest}: invalid YAML: {exc}"]

    validator = Draft202012Validator(SCHEMA)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "(root)"
        errors.append(f"{manifest}: {loc}: {err.message}")
    if errors:
        return errors

    expected_id = "00-template" if folder.name == "_template" else folder.name
    if data["id"] != expected_id:
        errors.append(f"{manifest}: id '{data['id']}' must equal folder name '{expected_id}'")

    if data["language"] == "python":
        code = recipe_code(folder)
        for prim in data["primitives"]:
            pattern = KNOWN_PRIMITIVES.get(prim)
            if pattern and not re.search(pattern, code):
                errors.append(f"{manifest}: primitive '{prim}' declared but not found in code (/{pattern}/)")
    return errors


def main(argv: list[str]) -> int:
    folders = [Path(a).resolve() for a in argv] or sorted(
        p for p in (ROOT / "recipes").iterdir() if p.is_dir()
    )
    all_errors = []
    for folder in folders:
        errs = validate(folder)
        all_errors += errs
        shown = folder.relative_to(ROOT) if folder.is_relative_to(ROOT) else folder
        print(f"{'FAIL' if errs else 'ok  '} {shown}")
    for e in all_errors:
        print(f"  {e}", file=sys.stderr)
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
