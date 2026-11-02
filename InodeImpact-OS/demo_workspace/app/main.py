"""Local sample service (demonstration only)."""
from app.core.report import build_report
from app.core.metrics import calculate_score
from pathlib import Path
import json

SETTINGS = Path('config/settings.json')

if __name__ == '__main__':
    print(build_report())
    print('score:', calculate_score([4, 7, 10]))
    print(json.loads(SETTINGS.read_text())['name'])
