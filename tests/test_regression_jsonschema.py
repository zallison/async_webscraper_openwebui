import importlib
import typing
import pytest
from pydantic import TypeAdapter


def test_register_handler_func_annotation_json_schema_safe():
    """
    Regression test: ensure Tools.register_handler 'func' annotation does not
    use typing.Callable (which breaks Pydantic JSON schema generation).

    This will fail if the annotation regresses to Callable, since
    TypeAdapter(Callable).json_schema() raises in Pydantic v2.
    """
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    hints = typing.get_type_hints(main_mod.Tools.register_handler)
    func_ann = hints.get("func", None)

    # If annotation is missing, treat as Any for schema generation
    ann = func_ann if func_ann is not None else typing.Any

    # Should not raise
    TypeAdapter(ann).json_schema()
