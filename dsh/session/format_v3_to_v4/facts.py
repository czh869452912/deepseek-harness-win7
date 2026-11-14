"""Historical child discovery evidence used to complete a parent's catalog."""
from dsh.core.session.json import UNDEFINED
from dsh.cordis.utils import _js_strict_equal
from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError, sessionFormatCount
from dsh.session.format_v2_to_v3.payload import display


def historicalChildCatalogSource(artifact):
    header = artifact['header']
    if header.get('origin') != 'subagent' or header.get('parentSession', UNDEFINED) is UNDEFINED:
        raise SessionFormatUnsupportedMigrationError('catalog migration requires a subagent child with a direct parent')
    descriptors = [event for event in artifact['events'] if event['type'] == 'subagent/descriptor'
                   and event['seq'] >= artifact['inheritedEventCount']]
    source = dict(childId=header['id'], childCreatedAt=header['createdAt'], descriptorCount=len(descriptors),
                  descriptor=descriptors[0]['data'] if descriptors else None)
    childCatalogFact(source)
    return source


def childCatalogSource(value):
    if not isinstance(value, dict) or not isinstance(value.get('childId'), str) or 'descriptor' not in value:
        raise SessionFormatUnsupportedMigrationError('catalog migration requires historical child identity and descriptor evidence')
    sessionFormatCount(value.get('childCreatedAt', UNDEFINED), 'catalog child creation time')
    sessionFormatCount(value.get('descriptorCount', UNDEFINED), 'child descriptor count')
    return value


def childCatalogFact(source):
    descriptor, count = source.get('descriptor'), source.get('descriptorCount', UNDEFINED)
    if (not _js_strict_equal(count, 1) or not isinstance(descriptor, dict)
            or not any(_js_strict_equal(descriptor.get('version', UNDEFINED), value) for value in (1, 2, 3))):
        return None
    subject = childCatalogSubject(source)
    if not isinstance(descriptor.get('provider'), str):
        raise SessionFormatUnsupportedMigrationError(subject + ' has an invalid subagent descriptor provider')
    version_one = _js_strict_equal(descriptor['version'], 1)
    if not version_one and descriptor.get('mode') not in ('continuable', 'one-shot'):
        raise SessionFormatUnsupportedMigrationError(subject + ' has an invalid subagent descriptor mode')
    value = dict(version=0, childId=source.get('childId', UNDEFINED), childCreatedAt=source.get('childCreatedAt', UNDEFINED),
                 mode='continuable' if version_one else descriptor['mode'])
    if descriptor.get('label', UNDEFINED) is not UNDEFINED:
        value['label'] = descriptor['label']
    return catalogFact(value, subject)


def catalogFact(value, subject='subagent/catalog'):
    if (not isinstance(value, dict)
            or not any(_js_strict_equal(value.get('version', UNDEFINED), version) for version in (0, 1, 2))
            or not isinstance(value.get('childId'), str)
            or value.get('mode') not in ('continuable', 'one-shot', 'external', 'unknown')
            or (_js_strict_equal(value.get('version', UNDEFINED), 2) != (value.get('mode') == 'external'))
            or (_js_strict_equal(value.get('version', UNDEFINED), 0) and value.get('mode') == 'unknown')
            or (value.get('mode') == 'continuable' and not isinstance(value.get('label'), str))
            or (value.get('label', UNDEFINED) is not UNDEFINED and not isinstance(value['label'], str))):
        raise SessionFormatError(subject + ' requires a supported versioned catalog fact')
    sessionFormatCount(value.get('childCreatedAt', UNDEFINED), 'catalog child creation time')
    return value


def childCatalogSubject(source):
    suffix = ' (raw log: ' + source['sourcePath'] + ')' if isinstance(source.get('sourcePath'), str) else ''
    return 'Session ' + display(source.get('childId', UNDEFINED)) + suffix
