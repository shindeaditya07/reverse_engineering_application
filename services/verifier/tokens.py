"""Token and symbol overlap for V-10, a heuristic (VER-1.7).

It asks one question: do the content words of the explanation appear in the cited code? It
cannot tell a true explanation from a false one that reuses the code's words, and it
penalises a correct explanation written in different words. That is why it may only demote.
"""

import re

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[A-Za-z0-9]+")
_STOP = frozenset(
    """a about after all also an and any are as at be because been before but by can could do does
    each for from has have how if in into is it its may more must no not of on only or other our
    over per same should so such than that the their then there these they this those to under up
    use used uses using was we were what when where which while who will with would you your
    returns return value values""".split()
)


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def content_tokens(text: str) -> frozenset[str]:
    tokens = (_stem(w.lower()) for w in _WORD.findall(_CAMEL.sub(" ", text)))
    return frozenset(t for t in tokens if t not in _STOP and (len(t) > 2 or t.isdigit()))


def overlap(explanation: str, evidence_text: str) -> float:
    """Share of the explanation's content tokens that occur in the evidence. 1.0 if it has none."""
    wanted = content_tokens(explanation)
    if not wanted:
        return 1.0
    return len(wanted & content_tokens(evidence_text)) / len(wanted)
