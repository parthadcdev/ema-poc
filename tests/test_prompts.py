from ema_poc.config import Settings
from ema_poc.models import Persona
from ema_poc.prompts import resolve_system_prompt


def test_resolves_persona_specific_prompt():
    s = Settings(system_prompts={"Patient": "patient context", "default": "def"})
    assert resolve_system_prompt(Persona.PATIENT, s) == "patient context"


def test_falls_back_to_default_when_persona_absent():
    s = Settings(system_prompts={"default": "the default"})
    assert resolve_system_prompt(Persona.PROVIDER, s) == "the default"


def test_hardcoded_fallback_when_config_empty():
    s = Settings()  # no system_prompts configured
    out = resolve_system_prompt(Persona.PROSPECT, s)
    assert isinstance(out, str) and out  # non-empty fallback
