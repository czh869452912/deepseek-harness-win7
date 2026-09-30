import pytest

from dsh.cordis.context import Context
from dsh.llm.llm_deepseek import LLMDeepSeekPlugin
from dsh.llm.llm_service import LlmRuntime
from dsh.llm.deepseek_image_pricing import image_tokens


@pytest.mark.parametrize("width,height,expected", [
    (100, 100, 117), (384, 384, 117), (640, 480, 209), (800, 800, 349),
    (1024, 768, 357), (1920, 1080, 369), (2000, 2000, 349), (5000, 5000, 349),
    (300, 50, 101), (9000, 1, 113), (8192, 100, 113), (16, 8192, 381),
    (1, 9000, 381), (100, 4036, 253), (4921, 353, 289), (97, 7289, 245),
])
def test_pinned_provider_grid_fixtures(width, height, expected):
    assert image_tokens(width, height) == expected


@pytest.mark.asyncio
async def test_registered_route_prices_text_projection_and_oldest_image_offload():
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    await ctx.plugin(LLMDeepSeekPlugin, config={"maxImagesPerRequest": 2, "imageOffloadCountQuantum": 1})
    refs = [{"attachmentId": "sha256:" + str(index) * 64, "bytes": 1000, "width": 800, "height": 800, "mediaType": "image/png"} for index in range(3)]
    try:
        llm = ctx.get("llm")
        text = llm.image_request_pricing("deepseek-official", "deepseek-v4-flash").priceImages(refs)
        assert all(row["visualTokens"] == 0 and "text only" in row["text"] for row in text)
        vision = llm.imageRequestPricing("deepseek-official", "deepseek-v4-flash-vision-exp").priceImages(refs)
        assert [row["visualTokens"] for row in vision] == [0, 349, 349]
        assert "image limits" in vision[0]["text"]
        assert "request preview 800x800px" in vision[1]["text"]
        assert llm.imageRequestPricing("unregistered", "model") is None
        from dsh.core.session import Session
        from dsh.llm.token_meter import TokenMeter, estimate_message
        session = Session("image-pricing")
        session.append_request_header({"config": {"provider": "deepseek-official", "model": "deepseek-v4-flash-vision-exp"}})
        message = {"role": "user", "content": [{"type": "image", "attachment": ref} for ref in refs]}
        session.append_user_message(message["content"])
        meter = TokenMeter(ctx)
        assert meter.measure(session)["surfaceTokens"] == estimate_message(message, iter(vision))
        session.append_request_header({"config": {"provider": "deepseek-official", "model": "deepseek-v4-flash"}})
        assert meter.measure(session)["surfaceTokens"] == estimate_message(message, iter(text))
    finally:
        await ctx.fiber.dispose()
