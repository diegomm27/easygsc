"""Interactive prompts shared by the wizards: EOF, Ctrl+D, q and quit cancel any of them."""

from __future__ import annotations


class Cancelled(Exception):
    """The user cancelled with EOF, Ctrl+D or q/quit."""


def ask(prompt: str) -> str:
    try:
        answer = input(prompt)
    except EOFError:
        raise Cancelled("no input") from None
    if answer.strip().lower() in ("q", "quit"):
        raise Cancelled("quit")
    return answer


def confirm(prompt: str, default: bool = False) -> bool:
    answer = ask(prompt).strip().lower()
    return default if not answer else answer in ("y", "yes")
