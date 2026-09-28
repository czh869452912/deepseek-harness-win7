"""Pinned V4 vision-grid pricing, including worst-case four-token alignment."""
import math
from types import SimpleNamespace

from dsh.attachment.image_codec import dimensions
from dsh.llm.image_content import handle, omitted, offload, project_text_only


def grid_tokens(height, width):
    return height * (width + 1) + 2 + ((width + 1) if height % 2 else 0) + (((height + 1) // 2 * (width + 1)) % 2) * 2


def solve(height, width, budget):
    aspect = height / width
    ideal_width = math.sqrt((budget - 2) / aspect + 0.25) - 0.5
    ideal_height = ideal_width * aspect
    if ideal_width < 1:
        gw, gh = 1, (budget - 2) // 2
        gh -= gh % 2
        bw, bh = gw * 42, gh * 42
    elif ideal_height < 2:
        gh, gw = 2, (budget - 2) // 2 - 1
        if gw <= 1:
            raise ValueError("no image grid fits token budget")
        bw, bh = gw * 42, gh * 42
    else:
        gw, gh = int(ideal_width), int(ideal_height)
        gh -= gh % 2
        scale = min(gw * 42 / width, gh * 42 / height)
        bw, bh = int(width * scale / 14) * 14, int(height * scale / 14) * 14
    gh, gw = (bh // 14 + 2) // 3, (bw // 14 + 2) // 3
    return bw, bh, gh, gw, grid_tokens(gh, gw)


def resize(width, height):
    width = min(width, height * 8)
    pixels = width * height
    if pixels < 384 * 384:
        scale = math.sqrt(384 * 384 / pixels)
        width, height = int(width * scale), int(height * scale)
    pw, ph = (width + 13) // 14 * 14, (height + 13) // 14 * 14
    gw, gh = (pw // 14 + 2) // 3, (ph // 14 + 2) // 3
    result = pw, ph, gh, gw, grid_tokens(gh, gw)
    budget = 381
    while result[-1] > 381:
        result = solve(height, width, budget)
        budget -= 1
    return result[:-1] + (result[-1] + 3,)


def image_tokens(width, height):
    if type(width) is not int or type(height) is not int or min(width, height) < 1:
        raise ValueError("image dimensions must be positive integers")
    result = resize(width, height)
    for _ in range(1, 10):
        following = resize(result[0], result[1])
        if following == result:
            return result[-1]
        result = following
    raise ValueError("DeepSeek image resize did not converge")


def request_pricing(options, model_id, access=None):
    model = next((row for row in options["models"] if row["id"] == model_id), {})
    def price(refs):
        content = [{"type": "image", "attachment": ref} for ref in refs]
        messages = [{"role": "user", "content": content}]
        if "image" not in model.get("inputModalities", []):
            return [{"visualTokens": 0, "text": block["text"]} for block in project_text_only(messages)[0]["content"]]
        projected = offload(messages, options["maxRequestFilesBytes"], options["maxImagesPerRequest"],
            options["imageOffloadByteQuantum"], options["imageOffloadCountQuantum"],
            lambda ref: min(ref["bytes"], model["imageMaxBytes"]), access=access)[0]["content"]
        result = []
        for ref, block in zip(refs, projected):
            if block["type"] == "text":
                result.append({"visualTokens": 0, "text": block["text"]})
            else:
                width, height = dimensions(ref["width"], ref["height"], model["imagePixelBudget"])
                result.append({"visualTokens": image_tokens(width, height),
                    "text": handle(ref, {"width": width, "height": height}, access(ref) if access else None)})
        return result
    return SimpleNamespace(priceImages=price, price_images=price)
