from .models import Character, Statement


def get_statement(statement: str) -> Statement:
    """Convert a string statement type to a Statement enum

    Args:
        statement (str): The string representation of the statement type

    Returns:
        Statement: The corresponding Statement enum
    """
    mapping = {
        "赞同": Statement.AGREEMENT,
        "疑问": Statement.DOUBT,
        "伪证": Statement.PURJURY,
        "反驳": Statement.REFUTATION,
    }
    return mapping[statement]


def get_character(character: str) -> Character:
    """Convert a string character name to a Character enum

    Args:
        character (str): The string representation of the character name

    Returns:
        Character: The corresponding Character enum
    """
    mapping = {
        "艾玛": Character.EMA,
        "希罗": Character.HIRO,
    }
    return mapping[character]
