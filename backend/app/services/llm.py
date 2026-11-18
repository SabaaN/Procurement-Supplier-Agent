"""Structured Groq calls that survive a known model quirk.

Groq's models sometimes name their answer "functions.CameraExtraction" instead of
"CameraExtraction" (copying the OpenAI-style prefix). LangChain then rejects a perfectly good
answer with "Unknown tool type: 'functions.CameraExtraction'". At temperature 0 the model makes
the same slip on every retry, so the page was skipped. Here the raw answer is kept, the prefix
stripped, and the arguments validated against the schema as normal.
"""
from pydantic import BaseModel


def structured_invoke(llm, schema: type[BaseModel], messages):
    """llm.with_structured_output(schema).invoke(messages), tolerating a prefixed tool name.

    Raises the original parsing error (or a ValidationError) if the answer really is unusable."""
    out = llm.with_structured_output(schema, include_raw=True).invoke(messages)
    if not isinstance(out, dict):  # a client that ignores include_raw (e.g. a test fake)
        return out
    if out.get("parsed") is not None:
        return out["parsed"]

    raw = out.get("raw")
    for call in getattr(raw, "tool_calls", None) or []:
        name = str(call.get("name") or "").rsplit(".", 1)[-1]  # "functions.CameraExtraction" -> "CameraExtraction"
        if name == schema.__name__:
            return schema.model_validate(call.get("args") or {})
    raise out.get("parsing_error") or ValueError("The model returned no structured answer")