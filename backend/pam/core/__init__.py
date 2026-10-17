"""M0 core plumbing shared by every module (SPEC §8 M0).

Behavior:
    `config` loads `pam.toml`, `vault` resolves paths and creates vaults, `mdio` reads and writes
    frontmatter Markdown, `tokens` counts `cl100k_base` tokens, `lock` serializes vault writers,
    and `time`, `ids`, `errors` hold shared helpers.
"""
