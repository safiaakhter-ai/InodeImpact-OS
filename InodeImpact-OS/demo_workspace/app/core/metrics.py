def calculate_score(values):
    return round(sum(values) / len(values), 2) if values else 0
