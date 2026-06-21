def leverage_for_score(score: int, maximum: int = 5) -> int:
    target = 5 if score >= 85 else 3 if score >= 75 else 2 if score >= 65 else 0
    return min(target, max(1, maximum)) if target else 0
