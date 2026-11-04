import json
from pathlib import Path


_LOCATION_FILE = Path(__file__).parent / 'data' / 'nigeria_state_lgas.json'
_LOCATION_DATA = json.loads(_LOCATION_FILE.read_text(encoding='utf-8'))
STATE_LGA_MAP = _LOCATION_DATA['states']
STATE_CHOICES = tuple((state, state) for state in STATE_LGA_MAP)


def lga_choices_for_state(state):
    return (('', 'Select an LGA'),) + tuple(
        (lga, lga) for lga in STATE_LGA_MAP.get(state, ())
    )
