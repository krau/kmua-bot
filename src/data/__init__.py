import json
import pathlib

weni_data: dict = json.load(
    open(
        pathlib.Path(__file__).parent.parent.parent / "resource" / "weni.json",
        "r",
        encoding="utf-8",
    )
)
