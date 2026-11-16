"""Model-facing Office families and operation-specific argument admission."""
import math

from dsh.cordis.text import lower_js,trim_js
from dsh.cordis.utils import js_to_string

FAMILIES=dict(doc='text',docx='text',odt='text',xls='spreadsheet',xlsx='spreadsheet',ods='spreadsheet',ppt='presentation',pptx='presentation',odp='presentation',pdf='pdf')
CONVERSION_OUTPUTS=dict(text=['pdf','docx','odt','txt'],spreadsheet=['pdf','xlsx','ods','csv'],presentation=['pdf','pptx','odp'])
OUTPUT_FORMATS=['pdf','docx','odt','txt','xlsx','ods','csv','pptx','odp']
RECALCULATION_FORMATS=['xlsx','ods']
PARAMETER_NAMES=dict(office_render=['input','pages','sheet','range','dpi'],office_convert=['input','format','sheet'],office_recalculate=['input','format'])


def check_parameter_names(tool,args,declared=PARAMETER_NAMES):
    for key in args:
        if key in declared[tool]:continue
        owners=[other for other in declared if key in declared[other]]
        raise ValueError(key+' applies only to '+' or '.join(owners) if owners else tool+' does not accept '+key)


def extension_of(path):
    name=path[max(path.rfind('/'),path.rfind('\\'))+1:];dot=name.rfind('.')
    return '' if dot<=0 else lower_js(name[dot+1:])


def input_family(operation,path):
    family=FAMILIES.get(extension_of(path))
    if operation=='recalculate':
        if family!='spreadsheet':raise ValueError('cannot recalculate "{}": recalculate accepts xls, xlsx, or ods workbooks'.format(path))
        return family
    if family is None or family=='pdf' and operation=='convert':
        accepted='doc, docx, odt, xls, xlsx, ods, ppt, pptx, odp, or pdf' if operation=='render' else 'doc, docx, odt, xls, xlsx, ods, ppt, pptx, or odp'
        raise ValueError('cannot {} "{}": {} accepts {} files'.format(operation,path,operation,accepted))
    return family


def _safe_integer(value):return type(value) in (int,float) and math.isfinite(value) and value==int(value) and abs(value)<=9007199254740991


def check_render_arguments(args,family):
    if 'pages' in args:
        if family=='spreadsheet':raise ValueError('pages does not apply to spreadsheets; select sheet and range instead')
        pages=args['pages']
        if not pages or any(not _safe_integer(page) or page<1 for page in pages) or len(set(pages))!=len(pages):raise ValueError('pages must list distinct one-based page numbers')
    if family!='spreadsheet' and 'sheet' in args:raise ValueError('sheet applies only to spreadsheets')
    if 'range' in args and 'sheet' not in args:raise ValueError('range requires sheet')
    if 'sheet' in args and not trim_js(args['sheet']):raise ValueError('sheet must be an exact worksheet name')
    if 'dpi' in args and (not _safe_integer(args['dpi']) or args['dpi']<24 or args['dpi']>600):raise ValueError('dpi must be an integer from 24 to 600')


def check_conversion_arguments(args,family):
    accepted=CONVERSION_OUTPUTS[family]
    if args['format'] not in accepted:raise ValueError('cannot convert "{}" to {}: this file converts to {}'.format(args['input'],js_to_string(args['format']),', '.join(accepted)))
    if 'sheet' in args and args['format']!='csv':raise ValueError('sheet applies only to CSV conversion')
    if 'sheet' in args and not trim_js(args['sheet']):raise ValueError('sheet must be an exact worksheet name')
