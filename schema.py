from typing import Literal
from pydantic import BaseModel, Field

Layout = Literal["bullets", "two_column", "section"]


class Outline(BaseModel):
    title: str
    slide_titles: list[str] = Field(description="One title per content slide, in order")


class Slide(BaseModel):
    title: str
    layout: Layout = "bullets"
    bullets: list[str] = Field(description="3-5 short bullets, max ~12 words each")
    right_bullets: list[str] = Field(
        default_factory=list, description="Only used for the two_column layout"
    )
    notes: str = Field(default="", description="Speaker notes, 2-4 sentences")


class Deck(BaseModel):
    title: str
    subtitle: str = ""
    slides: list[Slide]
