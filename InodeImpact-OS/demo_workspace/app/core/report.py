from app.core.metrics import calculate_score
from app.core.formatter import format_score

def build_report():
    return format_score(calculate_score([10, 20, 30]))
