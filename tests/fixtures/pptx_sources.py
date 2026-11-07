"""Original tiny OOXML engineering fixtures, not user-facing lesson decks.

The XML deliberately exercises package and extraction edge cases. No Office
installation, network, rendering, or third-party presentation library is used.
"""
from xml.sax.saxutils import escape, quoteattr
import zipfile

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
MAIN_TYPE = 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'
NS = (f'xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}" '
      'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
      'xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
      'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
      'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"')


def paragraph(text):
    return '<a:p><a:r><a:t>' + escape(text) + '</a:t></a:r></a:p>'


def shape(text='', *, placeholder=None, body=None):
    ph = '<p:ph type=' + quoteattr(placeholder) + '/>' if placeholder else ''
    return ('<p:sp><p:nvSpPr><p:cNvPr id="1" name="fixture"/><p:cNvSpPr/>'
            '<p:nvPr>' + ph + '</p:nvPr></p:nvSpPr><p:spPr/>'
            '<p:txBody><a:bodyPr/><a:lstStyle/>' + (body if body is not None else paragraph(text))
            + '</p:txBody></p:sp>')


def slide(body, *, hidden=False, notes=False):
    kind = 'notes' if notes else 'sld'
    return (f'<p:{kind} {NS}' + (' show="0"' if hidden else '')
            + '><p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>' + body
            + f'</p:spTree></p:cSld></p:{kind}>')


def table(rows):
    body = ''.join('<a:tr h="100">' + ''.join('<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>'
                   + paragraph(value) + '</a:txBody><a:tcPr/></a:tc>' for value in row)
                   + '</a:tr>' for row in rows)
    return ('<p:graphicFrame><p:nvGraphicFramePr/><p:xfrm/><a:graphic><a:graphicData '
            'uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr/>'
            '<a:tblGrid><a:gridCol w="100"/><a:gridCol w="100"/></a:tblGrid>'
            + body + '</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')


def relationships(items):
    """items: (Id, relationship suffix, Target[, TargetMode])."""
    return '<Relationships xmlns="' + REL + '">' + ''.join(
        '<Relationship Id=' + quoteattr(item[0]) + ' Type=' + quoteattr(R + '/' + item[1])
        + ' Target=' + quoteattr(item[2])
        + (' TargetMode=' + quoteattr(item[3]) if len(item) > 3 else '') + '/>'
        for item in items) + '</Relationships>'


def basic_parts():
    """Reordered slide parts, a table, and separate instructor notes."""
    return {
        '[Content_Types].xml': ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="' + MAIN_TYPE + '"/>'
            '<Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            '<Override PartName="/ppt/slides/slide9.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            '<Override PartName="/ppt/notesSlides/notesSlide8.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>'
            '</Types>'),
        '_rels/.rels': relationships([('main', 'officeDocument', 'ppt/presentation.xml')]),
        'ppt/presentation.xml': f'<p:presentation {NS}><p:sldIdLst>'
            '<p:sldId id="256" r:id="secondFile"/><p:sldId id="257" r:id="firstFile"/>'
            '</p:sldIdLst></p:presentation>',
        'ppt/_rels/presentation.xml.rels': relationships([
            ('firstFile', 'slide', 'slides/slide2.xml'), ('secondFile', 'slide', 'slides/slide9.xml')]),
        'ppt/slides/slide2.xml': slide(shape('Second displayed slide: verify the result.')),
        'ppt/slides/slide9.xml': slide(shape('First displayed slide: binary search.')
            + table([['Method', 'Precondition'], ['Binary search', 'Sorted input']])
            + shape('End of first slide.')),
        'ppt/slides/_rels/slide9.xml.rels': relationships([
            ('note', 'notesSlide', '../notesSlides/notesSlide8.xml')]),
        'ppt/notesSlides/notesSlide8.xml': slide(
            shape('Instructor note: mention the sorted-input precondition.', placeholder='body')
            + shape('SLIDE NUMBER MUST NOT BECOME NOTES', placeholder='sldNum')
            + shape('DATE MUST NOT BECOME NOTES', placeholder='dt'), notes=True),
    }


def write_pptx(path, parts=None, *, compression=zipfile.ZIP_DEFLATED, raw_names=False):
    """Write test packages, optionally preserving unsafe member-name bytes.

    ZipInfo's constructor sanitizes backslashes on Windows and NULs on every
    platform. Assigning filename after construction keeps adversarial fixtures
    identical across platforms in both local headers and the central directory.
    """
    with zipfile.ZipFile(path, 'w', compression=compression) as archive:
        for name, value in (basic_parts() if parts is None else parts).items():
            if raw_names:
                info = zipfile.ZipInfo('raw-name-fixture')
                info.filename = info.orig_filename = name
                archive.writestr(info, value, compress_type=compression)
            else:
                archive.writestr(name, value)


def mixed_pptx(path):
    """Simple destination-Path entrypoint for extraction/integration tests."""
    parts = basic_parts()
    formula = '<a:p><m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num>' \
              '<m:den><m:r><m:t>n</m:t></m:r></m:den></m:f></m:oMath></a:p>'
    visuals = ('<p:pic><p:nvPicPr><p:nvPr><a:videoFile r:link="externalVideo"/></p:nvPr>'
               '</p:nvPicPr><p:blipFill><a:blip r:embed="image"/></p:blipFill></p:pic>'
               '<p:graphicFrame><a:graphic><a:graphicData><c:chart r:id="chart"/>'
               '</a:graphicData></a:graphic></p:graphicFrame>'
               '<p:graphicFrame><a:graphic><a:graphicData><dgm:relIds r:dm="diagram"/>'
               '</a:graphicData></a:graphic></p:graphicFrame>'
               '<p:graphicFrame><p:oleObj r:id="object"/></p:graphicFrame>')
    parts['ppt/slides/slide2.xml'] = slide(shape('Hidden slide: visual-only material needs review.')
                                        + shape(body=formula) + visuals, hidden=True)
    parts['ppt/slides/_rels/slide2.xml.rels'] = relationships([
        ('externalVideo', 'video', 'https://example.invalid/never-fetch.mp4', 'External')])
    write_pptx(path, parts)
