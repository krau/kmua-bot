from enum import StrEnum


class Character(StrEnum):
    """Characters available for trail drawing"""

    EMA = "Ema"
    HIRO = "Hiro"

    @property
    def display(self) -> str:
        """Get the display string for the character"""
        mapping = {
            Character.EMA: "艾玛",
            Character.HIRO: "希罗",
        }
        return mapping[self]


class Statement(StrEnum):
    """Types of statements for the trail drawing"""

    AGREEMENT = "Agreement"
    DOUBT = "Doubt"
    PURJURY = "Perjury"
    REFUTATION = "Refutation"
    MAGIC = "Magic"

    @property
    def display(self) -> str:
        """Get the display string for the statement"""
        mapping = {
            Statement.AGREEMENT: "赞同",
            Statement.DOUBT: "疑问",
            Statement.PURJURY: "伪证",
            Statement.REFUTATION: "反驳",
            Statement.MAGIC: "魔法",
        }
        return mapping[self]


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
