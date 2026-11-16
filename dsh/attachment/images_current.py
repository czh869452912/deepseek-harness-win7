"""Current image publication and Pillow request variants for the Win7 runtime.

Pillow's explicit encoder identity stays distinct from Sharp's upstream key.
The surrounding durability, admission and cancellation contract is shared.
"""
import math
import os
import uuid

from dsh.attachment.error import AttachmentError
from dsh.attachment.immutable_current import check_abort, disk, publish_object
from dsh.attachment.local import digest_bytes, ensure_reference, object_path, probe_image, request_image_variant_id


async def commit_prepared_image(root, prepared):
    data, ref = prepared['data'], prepared['ref']
    digest = ensure_reference(ref)
    if digest_bytes(data) != digest or len(data) != ref['bytes']:
        raise AttachmentError('Prepared attachment bytes do not match their reference.', 'ATTACHMENT_CORRUPT')
    await publish_object(root, object_path(root, digest), data, digest)
    return ref


def validate_policy(policy):
    # Retain the earlier pixel-policy capability while the combined adapter
    # and its frozen historical consumers are retired in a later composition.
    legacy = 'maxPixels' in policy and 'width' not in policy and 'height' not in policy
    for key in (('maxPixels', 'maxBytes') if legacy else ('width', 'height', 'maxBytes')):
        value = policy.get(key)
        if type(value) not in (int, float) or value < 1 or value > 9007199254740991 or not math.isfinite(value) or int(value) != value:
            raise AttachmentError('Image request {} must be a positive integer.'.format(key), 'INVALID_ATTACHMENT_REF')


def alpha_compatible(alpha, facts):
    return facts['hasAlpha'] == alpha or (alpha and not facts['hasAlpha'] and facts['mediaType'] == 'image/webp')


def read_cached(path, width, height, alpha):
    try:
        with open(path, 'rb') as stream:
            data = stream.read()
        facts = probe_image(data)
        if (facts['width'] <= width and facts['height'] <= height and alpha_compatible(alpha, facts)
                and facts['depth'] == 'uchar' and facts['space'] == 'srgb'):
            return data, facts
    except (OSError, AttachmentError):
        pass
    return None


def write_cached(path, data):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    temporary = path + '.' + str(uuid.uuid4()) + '.tmp'
    try:
        with open(temporary, 'xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


async def read_request_image(root, stored, policy, signal=None):
    from dsh.attachment.image_codec import dimensions, encode, long_edge_dimensions
    from dsh.attachment.local import detect_image
    check_abort(signal)
    validate_policy(policy)
    ref, original = stored['ref'], stored['data']
    source = probe_image(original)
    # The source long edge chooses the encoder axis; the other target bound
    # still participates in cache validation and transform identity.
    legacy = 'maxPixels' in policy and 'width' not in policy and 'height' not in policy
    if legacy:
        width, height = dimensions(ref['width'], ref['height'], policy['maxPixels'])
        target_width, target_height = width, height
    else:
        axis = 'width' if ref['width'] >= ref['height'] else 'height'
        projected = long_edge_dimensions(ref['width'], ref['height'], int(policy[axis]))
        width, height = projected['width'], projected['height']
        target_width, target_height = policy['width'], policy['height']
    variant = request_image_variant_id(ref, policy)
    digest = str(variant)[7:]
    path = os.path.join(root, 'request-images', digest[:2], digest)
    cached = await disk(read_cached, path, target_width, target_height, source['hasAlpha'])
    check_abort(signal)
    if cached is not None:
        data, facts = cached
    elif target_width >= ref['width'] and target_height >= ref['height'] and len(original) <= policy['maxBytes']:
        data, facts = original, source
    else:
        version = await disk(encode, original, width, height, policy['maxBytes'], not legacy)
        data = version['data']
        facts = await disk(detect_image, data)
        if (facts['depth'] != 'uchar' or facts['space'] != 'srgb' or facts['width'] != version['width']
                or facts['height'] != version['height'] or facts['mediaType'] != version['mediaType']
                or not alpha_compatible(source['hasAlpha'], facts)):
            raise AttachmentError('Encoded model-request image does not match its verified 8-bit sRGB metadata.', 'ATTACHMENT_WRITE_FAILED')
        check_abort(signal)
        await disk(write_cached, path, data)
    check_abort(signal)
    return dict(variantId=variant, attachment=ref, data=data, mediaType=facts['mediaType'], bytes=len(data),
                width=facts['width'], height=facts['height'], depth='uchar', space='srgb', hasAlpha=facts['hasAlpha'])


async def request_image(attachments, ref, policy, signal=None):
    """Prefer the current async capability; retain old synchronous providers."""
    method = getattr(attachments, 'readImageRequest', None)
    if method is not None:
        # The historical combined adapter still supplies its pixel policy.
        # Adapt that caller at this boundary; the current public API uses targets.
        if 'maxPixels' in policy and 'width' not in policy and 'height' not in policy:
            from dsh.attachment.image_codec import dimensions
            width, height = dimensions(ref['width'], ref['height'], policy['maxPixels'])
            policy = dict(width=width, height=height, maxBytes=policy['maxBytes'])
        return await method(ref, policy, signal)
    return await disk(attachments.read_image_request, ref, policy, signal)
