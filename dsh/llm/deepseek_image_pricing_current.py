"""V4.1 request geometry and per-occurrence pricing from the fixed rc.3 Source."""
import math
from types import SimpleNamespace

from dsh.attachment.image_codec import dimensions, long_edge_dimensions as longEdgeDimensions
from dsh.llm.image_content_current import offloadedImageText, requestImageHandleText


def _cells(pixels):
    return (pixels//14+2)//3


def _tokens(height, width):
    return height*(width+1)+2


def _solve(height, width):
    aspect = height/width
    ideal_width = math.sqrt(1022/aspect+0.25)-0.5
    ideal_height = ideal_width*aspect
    if ideal_width < 1:
        best_width, best_height = 42, 511*42
    elif ideal_height < 1:
        best_width, best_height = 1021*42, 42
    else:
        scale = min(math.trunc(ideal_width)*42/width, math.trunc(ideal_height)*42/height)
        best_width, best_height = math.trunc(width*scale/14)*14, math.trunc(height*scale/14)*14
    gh, gw = _cells(best_height), _cells(best_width)
    return best_width, best_height, gh, gw, _tokens(gh, gw)


def _resize(width, height):
    pixels = width*height
    if 0 < pixels < 544*544:
        scale = math.sqrt(544*544/pixels)
        width, height = math.trunc(width*scale), math.trunc(height*scale)
    pw, ph = (width+13)//14*14, (height+13)//14*14
    gh, gw = _cells(ph), _cells(pw)
    return (pw, ph, gh, gw, _tokens(gh, gw)) if _tokens(gh, gw) <= 1024 else _solve(height, width)


def deepSeekImageTokens(width, height):
    result = _resize(width, height)
    for _ in range(1, 10):
        following = _resize(result[0], result[1])
        if following == result:
            return result[-1]
        result = following
    raise ValueError('deepseek image tokens: resize did not converge for %sx%s' % (width, height))


def deepSeekRequestImageDimensions(width, height):
    pw, ph = (width+13)//14*14, (height+13)//14*14
    if _tokens(_cells(ph), _cells(pw)) <= 1024:
        return dict(width=width, height=height)
    solved = _solve(height, width)
    return longEdgeDimensions(width, height, solved[0 if width >= height else 1])


def resolveRequestImageTarget(model, source):
    width, height = source['width'], source['height']
    budget = model.get('imagePixelBudget')
    if budget == 'low':
        budget = 512*512
    if budget is None:
        projected = deepSeekRequestImageDimensions(width, height)
    else:
        w, h = dimensions(width, height, budget)
        projected = dict(width=w, height=h)
    if max(projected.values()) > 4096:
        projected = longEdgeDimensions(width, height, 4096)
    return dict(projected, maxBytes=model.get('imageMaxBytes', 2*1024*1024))


def imagePricing(connection, model, resolveAccess=None):
    catalog = next((entry for entry in connection['models'] if entry['id'] == model), {})
    def price(images):
        result = []
        for block in images:
            ref = block['attachment']
            if 'image' not in catalog.get('inputModalities', []):
                result.append(dict(visualTokens=0, text='[image omitted because this model accepts text only; attachment sha256:%s]' % str(ref['attachmentId'])[7:15]))
            elif block.get('offloaded') is True:
                result.append(dict(visualTokens=0, text=offloadedImageText(ref, resolveAccess(ref) if resolveAccess else None)))
            else:
                target = resolveRequestImageTarget(catalog, ref)
                result.append(dict(visualTokens=deepSeekImageTokens(target['width'], target['height']),
                    text=requestImageHandleText(ref, target, resolveAccess(ref) if resolveAccess else None)))
        return result
    return SimpleNamespace(priceImages=price, price_images=price)
