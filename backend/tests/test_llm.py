"""The 'functions.CameraExtraction' quirk, and skipping sites that never sell the product."""
import pytest
from langchain_core.messages import AIMessage
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from pydantic import ValidationError

from app.devices.camera import CameraExtraction
from app.services import extractor, web_search
from app.services.llm import structured_invoke

real_extract_page = extractor.extract_page  # captured at import, before the autouse fakes replace them
REAL_SEARCH = web_search.search_web


class RawLLM:
    """Behaves like ChatGroq + LangChain with include_raw=True: runs the real LangChain parser
    on the tool call the model made, and reports a parsing error the way LangChain does."""

    def __init__(self, tool_name, args):
        self.message = AIMessage(content="", tool_calls=[{"name": tool_name, "args": args, "id": "call_1"}])

    def with_structured_output(self, schema, include_raw=False):
        self.schema = schema
        return self

    def invoke(self, messages):
        parser = PydanticToolsParser(tools=[self.schema], first_tool_only=True)
        try:
            return {"raw": self.message, "parsed": parser.invoke(self.message), "parsing_error": None}
        except Exception as e:
            return {"raw": self.message, "parsed": None, "parsing_error": e}


def test_the_real_parser_rejects_a_prefixed_name():
    """This is the error from the logs: LangChain refuses 'functions.CameraExtraction'."""
    msg = AIMessage(content="", tool_calls=[{"name": "functions.CameraExtraction", "args": {"is_product_page": False}, "id": "1"}])
    with pytest.raises(Exception, match="Unknown tool type: 'functions.CameraExtraction'"):
        PydanticToolsParser(tools=[CameraExtraction], first_tool_only=True).invoke(msg)


def test_prefixed_tool_name_is_accepted():
    llm = RawLLM("functions.CameraExtraction", {"is_product_page": True, "title": "Basler ace 2", "megapixels": 5})
    got = structured_invoke(llm, CameraExtraction, [])
    assert isinstance(got, CameraExtraction) and got.title == "Basler ace 2" and got.megapixels == 5


def test_normal_tool_name_still_works():
    got = structured_invoke(RawLLM("CameraExtraction", {"is_product_page": False}), CameraExtraction, [])
    assert got.is_product_page is False


def test_a_genuinely_bad_answer_still_fails():
    with pytest.raises(Exception, match="Unknown tool type"):
        structured_invoke(RawLLM("functions.SomethingElse", {}), CameraExtraction, [])
    with pytest.raises(ValidationError):
        structured_invoke(RawLLM("functions.CameraExtraction", {"title": "no is_product_page"}), CameraExtraction, [])


def test_extraction_survives_the_quirk_end_to_end(monkeypatch):
    llm = RawLLM("functions.CameraExtraction", {
        "is_product_page": True, "is_right_device_type": True, "title": "Hikrobot MV-CS050-10GM",
        "megapixels": 5, "fps": 24})
    monkeypatch.setattr(extractor, "_llm", lambda *a: llm)
    kind, product = real_extract_page("camera", "https://shop.test/p", "", "Hikrobot MV-CS050-10GM 5 MP 24 fps")
    assert kind == "product" and product["title"] == "Hikrobot MV-CS050-10GM"


@pytest.mark.parametrize("url, skipped", [
    ("https://www.youtube.com/watch?v=i9b4EwNNqak", True),
    ("https://m.youtube.com/watch?v=x", True),
    ("https://youtu.be/abc", True),
    ("https://en.wikipedia.org/wiki/Machine_vision", True),
    ("https://www.facebook.com/somecamerashop", True),
    ("https://www.eureca.de/20-1-Lightings.html", False),
    ("https://www.notyoutube.com/p", False),
])
def test_video_and_social_sites_are_skipped(url, skipped):
    assert web_search.is_skipped(url) is skipped


def test_search_drops_skipped_sites_and_tells_tavily(monkeypatch):
    seen = {}

    class Client:
        def search(self, **kw):
            seen.update(kw)
            return {"results": [{"url": "https://www.youtube.com/watch?v=1", "title": "video"},
                                {"url": "https://shop.test/p", "title": "camera"}]}

    monkeypatch.setattr(web_search, "_client", lambda: Client())
    hits = REAL_SEARCH("machine vision camera price")
    assert [h["url"] for h in hits] == ["https://shop.test/p"]
    assert "youtube.com" in seen["exclude_domains"]
