import math


def calculate_affection_update(
    current, change, rank, passivation=0.05, limit=2000, p=2, q=2, min_damping=0.2
) -> int:
    if change == 0:
        return current
    return round(
        max(
            -limit,
            min(
                limit,
                (
                    current
                    + (
                        change
                        * (math.tanh(passivation * change) / (passivation * change))
                        * max(
                            (1.0 / (1.0 + passivation * abs(2 * rank - 1) ** q))
                            * (max(0.0, 1.0 - (abs(current) / limit) ** p)),
                            min_damping,
                        )
                    )
                ),
            ),
        )
    )
