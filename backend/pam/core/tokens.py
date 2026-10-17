"""Token counting with tiktoken `cl100k_base`, the tokenizer named in `ContextBundle.tokenizer`."""

from functools import lru_cache

import tiktoken

TOKENIZER = "cl100k_base"


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    # First use downloads the BPE file unless TIKTOKEN_CACHE_DIR already holds it.
    return tiktoken.get_encoding(TOKENIZER)


def count(text: str) -> int:
    """Count the tokens in a text.

    Behavior:
        Special-token strings such as `<|endoftext|>` are counted as plain text, not rejected.
    Returns:
        The number of `cl100k_base` tokens.
    Parameters:
        text: Text to count.
    """
    return len(_encoding().encode(text, disallowed_special=()))
