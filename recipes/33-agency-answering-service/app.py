"""Agency answering service: one deployment, many tenants.

Governance point: per-request configuration instead of one deployment per customer.
The dynamic config callback resolves the tenant on the server (called number first,
then ?tenant=, else a message-only default), loads tenants/<id>.yaml and registers
only that tenant's tools on a per-request copy of the agent. A tool enabled for one
tenant does not exist for another, and handlers read the tenant, its hours and its
transfer numbers from the YAML, never from the model.
"""
import json
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from signalwire import AgentBase, FunctionResult

import config

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def digits(value) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def expand_numbers(cfg: dict) -> dict:
    """${VAR} expands only in numbers and transfer_targets. Expanding the whole file would let a
    tenant YAML pull any env var (an API token, say) into its prompt."""
    cfg["numbers"] = [os.path.expandvars(str(n)) for n in cfg.get("numbers") or []]
    cfg["transfer_targets"] = {k: os.path.expandvars(str(v or ""))
                               for k, v in (cfg.get("transfer_targets") or {}).items()}
    return cfg


def load_tenants() -> dict:
    """Read every tenants/*.yaml now, so a new file takes effect on the next call."""
    tenants = {}
    for path in sorted(config.TENANTS_DIR.glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text())
        if isinstance(cfg, dict) and cfg.get("id") == path.stem:
            cfg = expand_numbers(cfg)
            tenants[cfg["id"]] = cfg
    return tenants


def resolve_tenant(query_params: dict, body: dict) -> dict:
    tenants = load_tenants()
    called = digits((body or {}).get("call", {}).get("to"))
    for cfg in tenants.values():
        if called and called in {digits(n) for n in cfg.get("numbers", []) if digits(n)}:
            return cfg
    wanted = str((query_params or {}).get("tenant", ""))
    if config.ALLOW_TENANT_QUERY and TENANT_ID.match(wanted) and wanted in tenants:
        return tenants[wanted]
    return config.DEFAULT_TENANT


def now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def hours_on(cfg: dict, day: str) -> tuple[str, str] | None:
    span = cfg.get("hours", {}).get(day)
    return tuple(span.split("-")) if span else None


def is_open(cfg: dict) -> bool:
    t = now(cfg["timezone"])
    span = hours_on(cfg, DAYS[t.weekday()])
    return bool(span) and span[0] <= t.strftime("%H:%M") < span[1]


def record(cfg: dict, kind: str, fields: dict) -> str:
    ref = f"{cfg['id'][:3].upper()}-{int(time.time() * 1000) % 100000:05d}"
    config.MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with config.MESSAGES_FILE.open("a") as fh:  # tenant comes from config, never from args
        fh.write(json.dumps({"tenant": cfg["id"], "kind": kind, "ref": ref, **fields}) + "\n")
    return ref


# --- tool registry: name -> (description, properties(cfg), required, handler(cfg, args)) ---

def check_hours(cfg, args):
    day = str(args.get("day", "")).strip().lower()
    if day not in DAYS:
        return FunctionResult("That isn't a day of the week. Ask which day they mean.")
    span = hours_on(cfg, day)
    return FunctionResult(f"On {day} {cfg['name']} is " + (f"open {span[0]} to {span[1]}." if span else "closed."))


def ask_for(args, *keys):
    """`required` is enforced here, not trusted: the first blank field becomes a question for the model."""
    for k in keys:
        if not str(args.get(k) or "").strip():
            return FunctionResult(f"Ask the caller for their {k.replace('_', ' ')} before saving.")
    return None


def take_message(cfg, args):
    if problem := ask_for(args, "caller_name", "callback_number", "message"):
        return problem
    ref = record(cfg, "message", {k: args.get(k, "") for k in ("caller_name", "callback_number", "message")})
    return FunctionResult(f"Message saved for {cfg['name']}, reference {ref}. Tell the caller someone will call back.")


def book_appointment(cfg, args):
    if problem := ask_for(args, "patient_name", "reason"):
        return problem
    ref = record(cfg, "appointment_request", {k: args.get(k, "") for k in ("patient_name", "reason", "preferred_day")})
    return FunctionResult(f"Appointment request {ref} saved. The office will call to confirm a time.")


def request_consultation(cfg, args):
    if problem := ask_for(args, "name"):
        return problem
    area = args.get("practice_area")
    if area not in cfg.get("practice_areas", []):
        return FunctionResult(f"The firm handles: {', '.join(cfg.get('practice_areas', []))}. Offer to take a message.")
    ref = record(cfg, "consultation_request", {"name": args.get("name", ""), "practice_area": area})
    return FunctionResult(f"Consultation request {ref} saved. Intake will call back within one business day.")


def transfer_to(cfg, target, reason):
    number = cfg.get("transfer_targets", {}).get(target, "")
    if not digits(number):
        return FunctionResult("That line isn't available. Offer to take a message instead.")
    return FunctionResult(f"Connecting you now ({reason}).").connect(number, final=True)


def transfer_call(cfg, args):
    if not is_open(cfg):
        return FunctionResult(f"{cfg['name']} is closed right now. Offer to take a message.")
    return transfer_to(cfg, args.get("target"), "office hours")


def dispatch_technician(cfg, args):
    if not isinstance(args.get("emergency"), bool):  # absent or non-boolean must never become a routine ticket
        return FunctionResult("Ask whether this is an emergency: no heat below freezing, a gas smell, "
                              "or water leaking from equipment.")
    if args["emergency"]:  # emergencies bypass hours and go to the on-call line
        return transfer_to(cfg, "on_call_tech", "emergency")
    if problem := ask_for(args, "address", "issue"):
        return problem
    ref = record(cfg, "service_request", {k: args.get(k, "") for k in ("address", "issue")})
    return FunctionResult(f"Service request {ref} saved. Dispatch will call to schedule a visit.")


def s(description, **extra):
    return {"type": "string", "description": description, **extra}


PHONE = s("Phone number to call back, digits only with area code. Ask if not provided and read it back to "
          "confirm; never assume it is the number they are calling from.", pattern="^\\+?[0-9]{10,15}$")
TOOLS = {
    "check_hours": ("Look up office hours for one day of the week.",
                    lambda cfg: {"day": s("Day of the week the caller asked about. Ask which day if they did not "
                                          "say one.", enum=DAYS)},
                    ["day"], check_hours),
    "take_message": ("Take a message for the business.",
                     lambda cfg: {"caller_name": s("Caller's name as they gave it. Ask if not provided."),
                                  "callback_number": PHONE,
                                  "message": s("What the caller wants the business to know, in their words. "
                                               "Ask if not provided.")},
                     ["caller_name", "callback_number", "message"], take_message),
    "book_appointment": ("Submit an appointment request as soon as you have the name and reason. Don't ask "
                         "for an exact date or time: the office calls back to confirm one.",
                         lambda cfg: {"patient_name": s("Patient's full name. Ask if not provided."),
                                      "reason": s("Reason for the visit in the caller's words, e.g. cleaning, "
                                                  "toothache. Ask if not provided."),
                                      "preferred_day": s("Day the caller asked for, as they said it, e.g. Tuesday. "
                                                         "Omit if they did not say one; do not ask.")},
                         ["patient_name", "reason"], book_appointment),
    "request_consultation": ("Submit a consultation request once you have the name and practice area.",
                             lambda cfg: {"name": s("Caller's full name. Ask if not provided."),
                                          "practice_area": s("Kind of legal matter, picked from the list from what "
                                                             "the caller described. Ask if unclear; do not guess.",
                                                             enum=cfg.get("practice_areas", []))},
                             ["name", "practice_area"], request_consultation),
    "dispatch_technician": ("Open an HVAC service request once you have the address and issue. emergency=true "
                            "connects the on-call technician now; address and issue may be omitted for an emergency.",
                            lambda cfg: {"address": s("Service address, street and city. Ask if not provided."),
                                         "issue": s("What is wrong, in the caller's words. Ask if not provided."),
                                         "emergency": {"type": "boolean",
                                                       "description": "true only if the caller confirmed no heat below "
                                                                      "freezing, a gas smell, or water leaking from "
                                                                      "equipment; otherwise false. Ask if unsure."}},
                            ["emergency"], dispatch_technician),
    "transfer_call": ("Transfer the caller to a named line during office hours.",
                      lambda cfg: {"target": s("Which line to connect, e.g. front_desk. Ask the caller first; only "
                                               "connect after they agree to be transferred.",
                                               enum=sorted(cfg.get("transfer_targets", {})))},
                      ["target"], transfer_call),
}


def configure(query_params, body_params, headers, agent):
    """Runs per request (SWML fetch and every SWAIG call) on a copy of the agent."""
    cfg = resolve_tenant(query_params, body_params)
    agent.add_language("English", "en-US", cfg["voice"])
    agent.prompt_add_section("Role", cfg["prompt"])
    agent.prompt_add_section("Rules", bullets=[
        "Be brief and friendly. You only speak for this one business.",
        "Use only the tools you have. If none fits, offer to take a message.",
        "When a tool needs the caller's name, callback number, address or reason, ask for each one and read "
        "numbers back. Never fill in a value the caller did not give.",
    ])
    agent.set_global_data({"tenant": cfg["id"], "business_name": cfg["name"]})
    agent.add_swaig_query_params({"tenant": cfg["id"]})  # SWAIG callbacks resolve the same tenant
    for name in cfg["tools"]:
        description, props, required, handler = TOOLS[name]
        agent.define_tool(name=name, description=description, parameters=props(cfg), required=required,
                          handler=lambda args, raw, h=handler, c=cfg: h(c, args))


class AnsweringServiceAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="answering-service", route=config.ROUTE, port=config.PORT, **kwargs)
        self.set_dynamic_config_callback(configure)  # the master agent itself has no tools


agent = AnsweringServiceAgent()

if __name__ == "__main__":
    agent.run()
