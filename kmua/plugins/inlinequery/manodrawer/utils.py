from .models import Character, Option, Statement


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


def to_display_statement(statement: Statement) -> str:
    """Convert a Statement enum to its display string

    Args:
        statement (Statement): The Statement enum

    Returns:
        str: The display string of the statement
    """
    mapping = {
        Statement.AGREEMENT: "赞同",
        Statement.DOUBT: "疑问",
        Statement.PURJURY: "伪证",
        Statement.REFUTATION: "反驳",
    }
    return mapping[statement]


def get_character(character: str) -> Character:
    """Convert a string character name to a Character enum

    Args:
        character (str): The string representation of the character name

    Returns:
        Character: The corresponding Character enum, defaults to EMA if not found.
    """
    mapping = {
        "艾玛": Character.EMA,
        "希罗": Character.HIRO,
    }
    return mapping.get(character, Character.EMA)
