"""`pam schema export`: write one JSON Schema file per public contract model."""

import json
from pathlib import Path

import typer
from pydantic import BaseModel
from rich.console import Console

import pam
from pam.contracts import all_models
from pam.core.mdio import write_text

schema_app = typer.Typer(help="JSON Schemas of the data contracts (SPEC §7).", no_args_is_help=True)

# backend/pam/__init__.py -> repo root; in Docker /app/pam -> /.
DEFAULT_OUT = Path(pam.__file__).resolve().parents[2] / "schemas"


def export_schemas(out_dir: Path) -> list[Path]:
    """Write the JSON Schema of every model from `all_models()`.

    Behavior:
        Writes `<Model>.json` (indent 2, UTF-8, trailing newline) and sets `title` when the schema
        has none, as for the `ChatEvent` union. Output is deterministic. Files for removed models
        are not deleted.
    Exceptions:
        OSError: The folder or a file cannot be written.
    Returns:
        The written file paths.
    Parameters:
        out_dir: Destination folder; created if missing.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in all_models().items():
        is_model = isinstance(model, type) and issubclass(model, BaseModel)
        schema = model.model_json_schema() if is_model else model.json_schema()
        schema.setdefault("title", name)
        path = out_dir / f"{name}.json"
        write_text(path, json.dumps(schema, indent=2, ensure_ascii=False) + "\n")
        written.append(path)
    return written


@schema_app.command("export")
def export(
    out: Path = typer.Option(DEFAULT_OUT, "--out", help="Output folder.", show_default=True),
) -> None:
    """Write the JSON Schema of every contract model (one <Model>.json per model)."""
    written = export_schemas(out)
    Console().print(f"[green]Wrote[/] {len(written)} schemas to {out.resolve()}")


def register(app: typer.Typer) -> None:
    """Register the `schema` group on the root app.

    Parameters:
        app: The root `pam` Typer app.
    """
    app.add_typer(schema_app, name="schema")
