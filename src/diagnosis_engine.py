"""NetSage AI - AI Diagnosis Engine.

Phase 5 implementation.

This module connects a troubleshooting case to the AI diagnosis prompt
(from prompts/diagnose_prompt.md) and produces a STRUCTURED diagnosis.

It supports two modes:

  DEMO MODE (default when no API key is available)
      - Works with no dependencies and no network.
      - Produces a clearly-labeled simulated diagnosis.
      - The output is never presented as genuine AI evidence.

  LIVE MODE (when OPENAI_API_KEY is set)
      - Calls the configured OpenAI-compatible model.
      - Uses a low temperature for deterministic output.
      - Parses and validates the model's JSON against the 9-field schema.

Security:
    - The API key is read from the environment variable OPENAI_API_KEY.
    - A .env file may be loaded (via python-dotenv if present, otherwise a
      minimal built-in parser). The key is NEVER hard-coded in source.

Explicitly separate concepts:
    - AI diagnosis (this module)
    - Rule checker findings      (separate module)
    - Expected answer            (data/cases.csv, ground truth)
    - Human-approved final result (separate, human review)
"""

import csv
import json
import os
import re

# The exact schema every produced diagnosis must conform to.
# Internal metadata (like "source") is stored SEPARATELY, never in this object.
DIAGNOSIS_KEYS = [
    "case_id",
    "likely_fault",
    "osi_layer",
    "confidence",
    "evidence_used",
    "recommended_next_command",
    "suggested_fix",
    "reasoning_summary",
    "uncertainty_or_limitations",
]

VALID_CONFIDENCE = ("high", "medium", "low")

DEFAULT_MODEL = "gpt-4o-mini"


class DiagnosisValidationError(Exception):
    """Raised when an AI diagnosis fails validation."""


def _load_env_file(path=".env"):
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Used only as a fallback when python-dotenv is not installed.
    Values are not quoted-parsed beyond stripping basic quotes.
    Existing environment variables are NOT overwritten.
    """
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        # Reading the env file is best-effort; never crash on it.
        pass


def load_env():
    """Load .env (if present) preferring python-dotenv, else built-in parser."""
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:
        _load_env_file(".env")


def get_api_key():
    """Return the API key, loading .env first if needed."""
    if "OPENAI_API_KEY" not in os.environ:
        load_env()
    return os.environ.get("OPENAI_API_KEY", "").strip()


def get_model():
    """Return the configured model name, or the default."""
    return os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def validate_diagnosis(obj):
    """Validate a parsed JSON object against the 9-field schema.

    Returns a normalized diagnosis dict or raises DiagnosisValidationError.
    Does NOT add any extra/modified fields.
    """
    if not isinstance(obj, dict):
        raise DiagnosisValidationError("Response is not a JSON object.")

    missing = [k for k in DIAGNOSIS_KEYS if k not in obj]
    if missing:
        raise DiagnosisValidationError(
            "Response missing required field(s): %s" % ", ".join(missing))

    extra = [k for k in obj if k not in DIAGNOSIS_KEYS]
    if extra:
        raise DiagnosisValidationError(
            "Response contains unexpected field(s): %s" % ", ".join(extra))

    conf = obj.get("confidence")
    if conf not in VALID_CONFIDENCE:
        raise DiagnosisValidationError(
            "confidence must be one of %s, got %r" % (list(VALID_CONFIDENCE), conf))

    return {k: obj[k] for k in DIAGNOSIS_KEYS}


def _strip_code_fence(text):
    """Remove a surrounding ```json ... ``` fence if present."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return m.group(1) if m else text


def parse_raw_response(raw):
    """Parse a raw model response string into a validated diagnosis.

    Raises DiagnosisValidationError on unparseable/invalid JSON.
    Does not repair or fabricate output.
    """
    cleaned = _strip_code_fence(str(raw)).strip()
    # Extract the first balanced JSON object so trailing prose is ignored.
    start = cleaned.find("{")
    if start == -1:
        raise DiagnosisValidationError("No JSON object found in response.")
    depth = 0
    in_str = False
    escape = False
    end = None
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        raise DiagnosisValidationError("Unbalanced JSON object in response.")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise DiagnosisValidationError("Invalid JSON: %s" % exc)
    return validate_diagnosis(parsed)


class DiagnosisEngine:
    """Runs diagnosis on a single network troubleshooting case.

    load_case_from_csv() loads a case dict from cases.csv.
    diagnose(case) returns a dict:
        {"diagnosis": <9-field diagnosis>, "meta": {source, ...}}
    The 9-field `diagnosis` object NEVER contains extra fields.
    The `meta` block is separate internal metadata only.
    """

    def __init__(self, cases_csv=None):
        self.cases_csv = cases_csv or _default_cases_csv()
        self._prompt = None

    def _prompt_text(self):
        """Cache-load the prompt template from prompts/diagnose_prompt.md."""
        if self._prompt is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base, "prompts", "diagnose_prompt.md")
            if not os.path.isfile(path):
                raise FileNotFoundError("diagnose_prompt.md not found: %s" % path)
            self._prompt = open(path, "r", encoding="utf-8").read()
        return self._prompt

    def build_prompt(self, case):
        """Substitute the {placeholders} in the prompt template with case data."""
        template = self._prompt_text()
        mapping = {
            "case_id": str(case.get("case_id", "")),
            "title": str(case.get("title", "")),
            "concept_tag": str(case.get("concept_tag", "")),
            "symptom": str(case.get("symptom", "")),
            "topology_note": str(case.get("topology_note", "")),
            "show_outputs": str(case.get("show_outputs", "")),
        }
        prompt = template
        for key, value in mapping.items():
            prompt = prompt.replace("{" + key + "}", value)
        return prompt

    def diagnose(self, case, force_demo=False):
        """Produce a diagnosis for a case.

        If an API key is present (and live mode enabled), call the model.
        Otherwise (or force_demo=True) return a simulated diagnosis.
        Returns (diagnosis, meta) where diagnosis is the validated 9-field
        object and meta holds internal source/status info. meta always
        includes needs_human_review=True because every AI diagnosis must go
        through human review before being considered final.
        """
        case_id = str(case.get("case_id", ""))
        if force_demo or not get_api_key():
            return self._demo_diagnosis(case), {
                "source": "demo", "case_id": case_id,
                "needs_human_review": True,
            }
        return self._live_diagnosis(case), {
            "source": "live", "case_id": case_id,
            "needs_human_review": True,
        }

    # ------------------------------------------------------------
    # Demo mode
    # ------------------------------------------------------------
    def _demo_diagnosis(self, case):
        """Produce a deterministic, clearly-labeled simulated diagnosis.

        This is DEMO data only. It is built from the case metadata and is
        NOT genuine AI output. No command outputs are invented. The result
        is generated purely so the pipeline can be tested without an API key.

        IMPORTANT: This object conforms to the 9-field schema and is valid
        so it can exercise JSON validation, but it must never be treated as
        a real AI diagnosis. The returned `meta` marks source="demo".
        """
        case_id = str(case.get("case_id", ""))
        symptom = str(case.get("symptom", "") or "not provided")
        concept = str(case.get("concept_tag", "") or "not provided")
        show = str(case.get("show_outputs", "") or "PENDING_CAPTURE")
        return {
            "case_id": case_id,
            "likely_fault": (
                "DEMO (simulated, not real AI output). "
                "Hypothesis placeholder based on concept_tag=%s." % concept
            ),
            "osi_layer": "Layer 3",
            "confidence": "low",
            "evidence_used": [
                "DEMO MODE: no genuine evidence used; source is simulated.",
                "Symptom used: %s" % symptom,
            ],
            "recommended_next_command": (
                "show running-config   (DEMO placeholder; replace with a real "
                "confirmatory command during live mode)"
            ),
            "suggested_fix": [
                "DEMO MODE: this is a simulated suggestion and not a verified fix.",
                "Run live mode (set OPENAI_API_KEY) to obtain a genuine diagnosis.",
            ],
            "reasoning_summary": (
                "DEMO MODE: deterministic placeholder produced without a model. "
                "Not a real AI reasoning summary."
            ),
            "uncertainty_or_limitations": (
                "DEMO MODE: simulated output. show_outputs present=%r. "
                "This must not be presented as genuine AI evidence." % (show != "PENDING_CAPTURE")
            ),
        }

    # ------------------------------------------------------------
    # Live mode
    # ------------------------------------------------------------
    def _live_diagnosis(self, case):
        """Call the OpenAI-compatible model and validate the diagnosis."""
        key = get_api_key()
        if not key:
            raise DiagnosisValidationError("OPENAI_API_KEY is not set; cannot run live mode.")

        prompt_text = self.build_prompt(case)

        # The openai package can be missing (e.g. not installed under the
        # active interpreter). When it is absent we cannot call the model, so
        # we surface a clear error rather than fabricate a result.
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise DiagnosisValidationError(
                "Live mode requires the 'openai' package, which is not installed: %s" % exc)

        client = OpenAI(api_key=key)
        model = get_model()

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are NetSage AI, a network troubleshooting "
                            "assistant. Output exactly one JSON object matching "
                            "the required schema. Do not add extra fields."
                        ),
                    },
                    {"role": "user", "content": prompt_text},
                ],
                temperature=0.0,
                max_tokens=800,
            )
        except Exception as exc:  # surface API/client errors clearly
            raise DiagnosisValidationError("OpenAI API call failed: %s" % exc)

        content = response.choices[0].message.content
        if not content:
            raise DiagnosisValidationError("OpenAI returned empty content.")
        # parse_raw_response raises DiagnosisValidationError on failure.
        return parse_raw_response(content)

    # ------------------------------------------------------------
    # CSV loading
    # ------------------------------------------------------------
    def load_case(self, case_id):
        """Load a single case dict from cases.csv by case_id."""
        with open(self.cases_csv, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("case_id") == case_id:
                    return row
        raise KeyError("case_id not found in %s: %s" % (self.cases_csv, case_id))

    def load_cases(self, case_ids):
        """Load several cases in order."""
        return [self.load_case(cid) for cid in case_ids]

    def load_all_cases(self):
        """Load every case from cases.csv."""
        with open(self.cases_csv, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))


def _default_cases_csv():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "cases.csv")


# ----------------------------------------------------------------------
# Command-line driver for pilots / manual testing.
# ----------------------------------------------------------------------
def _cli():
    import sys

    if len(sys.argv) < 2:
        print("usage: python diagnosis_engine.py NET-001 [NET-002 ...] [--demo]")
        sys.exit(1)
    case_ids = [a for a in sys.argv[1:] if not a.startswith("--")]
    force_demo = "--demo" in sys.argv[1:]
    engine = DiagnosisEngine()
    for cid in case_ids:
        case = engine.load_case(cid)
        diag, meta = engine.diagnose(case, force_demo=force_demo)
        print(json.dumps({"meta": meta, "diagnosis": diag}, indent=2))


if __name__ == "__main__":
    _cli()