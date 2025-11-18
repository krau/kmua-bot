from enum import StrEnum


class Character(StrEnum):
    """Characters available for trail drawing"""

    EMA = "Ema"
    HIRO = "Hiro"


class Statement(StrEnum):
    """Types of statements for the trail drawing"""

    AGREEMENT = "Agreement"
    DOUBT = "Doubt"
    PURJURY = "Perjury"
    REFUTATION = "Refutation"


class Option:
    """A trial option for a character to say"""

    def __init__(self, statement: Statement, text: str) -> None:
        """Initialize a trail option

        Args:
            statement (Statement): The type of statement this option represents
            text (str): The text content of the option
        """
        self.statement = statement
        self.text = text
