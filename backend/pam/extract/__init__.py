"""M3 rule extractor and persona deriver (SPEC §8 M3).

Behavior:
    `patterns` declares the fact patterns, `facts` extracts and merges them, `rules` finds repeated
    instructions, `style` measures how the user writes, `persona` renders the Derived persona
    sections from `templates/`, `text` holds shared text helpers, and `derive` runs the pipeline
    behind `pam derive`.
"""
