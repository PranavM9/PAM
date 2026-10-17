# Commenting guideline

Follow the same commenting style used in `normalizer.py`: concise, structured docstrings with a short summary and a predictable set of sections. Keep comments factual, sparse, and useful. Do not add decorative prose or repeated explanations.

## Core rules

- Prefer docstrings over inline comments for public functions, classes, and modules.
- Start every docstring with a single-sentence summary that states the purpose clearly.
- Use a blank line after the summary before the detailed sections.
- Keep the summary in plain, direct language. Avoid buzzwords and vague wording.
- Use the same section order everywhere: `Behavior:`, `Exceptions:`, `Returns:`, then `Parameters:`.
- Write each section as a short, factual description. Do not over-explain the obvious.
- Use backticks for types, literals, and file names when they are part of the API contract.
- Use imperative or neutral phrasing such as "Parse a Claude export into normalized conversations." or "Normalize an export using the parser registered for its platform."
- Only add inline comments when they explain a non-obvious operation or a subtle edge case.
- Avoid comments that restate the code. If the code is obvious, leave it alone.

## Required structure

Use this pattern for functions and classes:

```python
"""Brief summary of what the function or class does.

Behavior:
    Explain the main processing behavior in a compact, precise way.
Exceptions:
    List the exception types and the situations that trigger them.
Returns:
    Describe the value returned by the function.
Parameters:
    name: Description of each parameter.
"""
```

The exact shape should stay consistent across files:

1. Summary sentence.
2. Blank line.
3. `Behavior:` section.
4. `Exceptions:` section when relevant.
5. `Returns:` section when relevant.
6. `Parameters:` section when function inputs exist.

## Style expectations

- Keep the first line short, usually one sentence.
- Use sentence case and periods at the end of sentences.
- Maintain a calm, technical tone.
- Prefer concrete wording over abstract wording.
- Use `"""` docstrings for modules, classes, and public functions.
- Keep comments aligned with the code's real behavior, not a hypothetical design.
- When a function handles multiple cases, document the key branch behavior in `Behavior:` rather than narrating every line of code.

## Example of the approved style

```python
"""Parse a Claude export into normalized conversations.

Behavior:
    Converts conversation metadata and user or assistant messages to the
    shared schema. Messages from other sender types are omitted.
Exceptions:
    OSError: The export cannot be opened or read.
    json.JSONDecodeError: The file does not contain valid JSON.
Returns:
    The conversations found in the export.
Parameters:
    path: Path to Claude's ``conversations.json`` export.
"""
```

This is the standard to match exactly: one summary sentence, brief sections, tight wording, and no filler.

## What to avoid

- Long narrative comments that explain what is obvious from the code.
- Mixed section names or inconsistent ordering.
- Fluffy wording like "This function is used to" without stating the actual behavior.
- Repeating the parameter names in paragraphs instead of the structured `Parameters:` block.
- Inline comments every few lines when a docstring would be clearer.
- Comments that describe intent instead of behavior.

The goal is simple: document the contract and the behavior without adding noise. The file should read like a precise technical reference, not a story.
