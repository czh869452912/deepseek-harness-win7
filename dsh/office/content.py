"""Canonical Office result projections consumed by model tools."""
from dsh.cordis.utils import js_to_string


def fonts_line(missing):return '\nFonts not installed and substituted: '+', '.join(missing)+'.' if missing else ''


def location(image):
    if 'page' in image:return 'Page '+js_to_string(image['page'])
    if 'sheet' not in image:return 'Image'
    return 'Sheet "'+image['sheet']+'"'+(' '+image['range'] if 'range' in image else '')


def render_images_content(value):
    count=len(value['images']);blocks=[dict(type='text',text='Rendered {} image{} of {} ({} in the document) at {} DPI.{}'.format(count,'' if count==1 else 's',value['path'],js_to_string(value['pageCount']),js_to_string(value['dpi']),fonts_line(value['missingFonts'])))]
    for image in value['images']:
        blocks.append(dict(type='text',text='{}: {}x{} px'.format(location(image),js_to_string(image['width']),js_to_string(image['height']))))
        attachment={key:image[key] for key in ('attachmentId','mediaType','bytes','width','height')}
        if 'originalDimensions' in image:attachment['originalDimensions']=dict(image['originalDimensions'])
        blocks.append(dict(type='image',attachment=attachment))
    return blocks


def render_file_content(value):
    verb='Converted' if value['operation']=='convert' else 'Recalculated';pages='' if 'pageCount' not in value else ', {} page{}'.format(js_to_string(value['pageCount']),'' if value['pageCount']==1 else 's')
    return [dict(type='text',text='{} {} to {} ({} bytes{}): {}\nCopy this temporary file to its destination with the shell now; it may be deleted after a retention period or to free space, and is deleted when this conversation ends.{}'.format(verb,value['path'],value['format'],js_to_string(value['bytes']),pages,value['file'],fonts_line(value['missingFonts'])))]
