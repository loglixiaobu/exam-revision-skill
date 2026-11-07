"""Small original DOCX/PDF fixtures using only the stdlib and pypdf.

The image is an original raster bar chart. Nothing is downloaded, and all
documents are generated in the caller's temporary directory.
"""
import struct
import zipfile
import zlib
from xml.sax.saxutils import escape

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
WIDTH, HEIGHT = 320, 200


def chart_pixels():
    pixels = bytearray([255] * (WIDTH * HEIGHT * 3))

    def rectangle(left, top, right, bottom, color):
        for y in range(top, bottom):
            for x in range(left, right):
                start = (y * WIDTH + x) * 3
                pixels[start:start + 3] = bytes(color)

    rectangle(30, 20, 33, 173, (30, 30, 30))
    rectangle(30, 170, 300, 173, (30, 30, 30))
    for top in (50, 90, 130):
        rectangle(33, top, 300, top + 1, (215, 215, 215))
    for left, height in ((60, 45), (130, 85), (200, 130)):
        rectangle(left, 170 - height, left + 40, 170, (35, 90, 140))
    # Original bitmap text makes this a scanned-note fixture rather than only
    # an empty image container. No OCR engine or image/font library is needed.
    glyphs = {
        'A': ('01110', '10001', '10001', '11111', '10001', '10001', '10001'),
        'B': ('11110', '10001', '10001', '11110', '10001', '10001', '11110'),
        'C': ('01111', '10000', '10000', '10000', '10000', '10000', '01111'),
        'D': ('11110', '10001', '10001', '10001', '10001', '10001', '11110'),
        'E': ('11111', '10000', '10000', '11110', '10000', '10000', '11111'),
        'H': ('10001', '10001', '10001', '11111', '10001', '10001', '10001'),
        'I': ('11111', '00100', '00100', '00100', '00100', '00100', '11111'),
        'N': ('10001', '11001', '11001', '10101', '10011', '10011', '10001'),
        'O': ('01110', '10001', '10001', '10001', '10001', '10001', '01110'),
        'P': ('11110', '10001', '10001', '11110', '10000', '10000', '10000'),
        'R': ('11110', '10001', '10001', '11110', '10100', '10010', '10001'),
        'S': ('01111', '10000', '10000', '01110', '00001', '00001', '11110'),
        'T': ('11111', '00100', '00100', '00100', '00100', '00100', '00100'),
        'U': ('10001', '10001', '10001', '10001', '10001', '10001', '01110'),
        'Y': ('10001', '10001', '01010', '00100', '00100', '00100', '00100'),
    }
    for label, top in [('BINARY SEARCH', 2), ('SORTED INPUT', 180)]:
        for index, character in enumerate(label):
            for y, row in enumerate(glyphs.get(character, ())):
                for x, bit in enumerate(row):
                    if bit == '1':
                        left = 40 + index * 12 + x * 2
                        rectangle(left, top + y * 2, left + 2, top + y * 2 + 2, (20, 20, 20))
    return bytes(pixels)


def chart_png():
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))

    pixels = chart_pixels()
    scanlines = b''.join(b'\0' + pixels[y * WIDTH * 3:(y + 1) * WIDTH * 3]
                         for y in range(HEIGHT))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b''))


def paragraph(text):
    return '<w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p>'


def write_docx(path, body):
    """Create a minimal valid Word package, including its actual image asset."""
    document = f'''<w:document xmlns:w="{W}" xmlns:m="{M}"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
      xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
      xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
      <w:body>{body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1000" w:right="1000" w:bottom="1000" w:left="1000"/>
      </w:sectPr></w:body></w:document>'''
    types = '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
      <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
      <Default Extension="xml" ContentType="application/xml"/>
      <Default Extension="png" ContentType="image/png"/>
      <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
      </Types>'''
    rels = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
      </Relationships>'''
    image_rels = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/chart.png"/>
      </Relationships>'''
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', types)
        archive.writestr('_rels/.rels', rels)
        archive.writestr('word/document.xml', document)
        archive.writestr('word/_rels/document.xml.rels', image_rels)
        archive.writestr('word/media/chart.png', chart_png())


FORMULA = '''<m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num>
    <m:den><m:r><m:t>n</m:t></m:r></m:den></m:f></m:oMath>'''
DRAWING = '''<w:drawing><wp:inline><wp:extent cx="3657600" cy="2286000"/>
    <wp:docPr id="1" name="Comparison chart" descr="Three original bars"/>
    <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
    <pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="chart.png"/>
    <pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rIdImage"/>
    <a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr>
    <a:xfrm><a:off x="0" y="0"/><a:ext cx="3657600" cy="2286000"/></a:xfrm>
    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>
    </a:graphicData></a:graphic></wp:inline></w:drawing>'''


def mixed_docx(path):
    cells = lambda values: ''.join('<w:tc>' + paragraph(v) + '</w:tc>' for v in values)
    table = ('<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/></w:tblPr>'
             '<w:tblGrid><w:gridCol w:w="4500"/><w:gridCol w:w="4500"/></w:tblGrid>'
             '<w:tr>' + cells(['Algorithm', 'Required condition']) + '</w:tr>'
             '<w:tr>' + cells(['Binary search', 'Sorted input']) + '</w:tr></w:tbl>')
    body = paragraph('Search methods revision') + paragraph('Compare the conditions before choosing an algorithm.')
    body += '<w:sdt><w:sdtPr/><w:sdtContent>' + paragraph('CONTROLLED NOTE: Binary search requires sorted input.') + table + '</w:sdtContent></w:sdt>'
    body += '<w:p><w:r><w:t>Step 1</w:t><w:tab/><w:t>Sort first</w:t><w:br/><w:t>Step 2</w:t><w:tab/><w:t>Search</w:t></w:r></w:p>'
    body += '<w:p><w:r><w:t>Mean weight is </w:t></w:r>' + FORMULA + '<w:r><w:t> for each item.</w:t></w:r></w:p>'
    body += '<w:p><m:oMathPara>' + FORMULA + '</m:oMathPara></w:p>'
    body += paragraph('Comparison chart') + '<w:p><w:r>' + DRAWING + '</w:r></w:p>'
    body += paragraph('The chart must be checked visually before claiming its values.')
    write_docx(path, body)


def mixed_pdf(path):
    """Text/table page, image-only page, text+image page, nested form image page.

    Page 1 references an unused image resource to catch false-positive scan
    warnings. Only pages 2-4 paint a raster image on the page.
    """
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                               NameObject, NumberObject)
    writer = PdfWriter()
    name = NameObject
    font = writer._add_object(DictionaryObject({
        name('/Type'): name('/Font'), name('/Subtype'): name('/Type1'),
        name('/BaseFont'): name('/Helvetica'),
    }))
    raster = DecodedStreamObject()
    raster.set_data(chart_pixels())
    raster.update({name('/Type'): name('/XObject'), name('/Subtype'): name('/Image'),
                   name('/Width'): NumberObject(WIDTH), name('/Height'): NumberObject(HEIGHT),
                   name('/ColorSpace'): name('/DeviceRGB'), name('/BitsPerComponent'): NumberObject(8)})
    raster_ref = writer._add_object(raster.flate_encode())
    form = DecodedStreamObject()
    form.set_data(b'q 320 0 0 200 0 0 cm /Chart Do Q')
    form.update({name('/Type'): name('/XObject'), name('/Subtype'): name('/Form'),
                 name('/BBox'): ArrayObject([NumberObject(x) for x in [0, 0, 320, 200]]),
                 name('/Resources'): DictionaryObject({name('/XObject'): DictionaryObject({name('/Chart'): raster_ref})})})
    form_ref = writer._add_object(form)
    streams = [
        b'BT /F1 18 Tf 50 740 Td (Search methods revision) Tj '
        b'0 -36 Td /F1 12 Tf (Algorithm         Required condition) Tj '
        b'0 -24 Td (Binary search     Sorted input) Tj '
        b'0 -24 Td (Linear search     Any order) Tj ET',
        b'q 480 0 0 300 50 380 cm /Chart Do Q',
        b'BT /F1 14 Tf 50 740 Td (Mixed page: the body below is a scanned diagram.) Tj ET '
        b'q 480 0 0 300 50 380 cm /Chart Do Q',
        b'BT /F1 14 Tf 50 740 Td (Nested form: verify all chart values visually.) Tj ET '
        b'q 1.5 0 0 1.5 50 380 cm /NestedChart Do Q',
    ]
    for stream in streams:
        page = writer.add_blank_page(width=612, height=792)
        page[name('/Resources')] = DictionaryObject({
            name('/Font'): DictionaryObject({name('/F1'): font}),
            name('/XObject'): DictionaryObject({name('/Chart'): raster_ref, name('/NestedChart'): form_ref}),
        })
        content = DecodedStreamObject()
        content.set_data(stream)
        page[name('/Contents')] = writer._add_object(content)
    with open(path, 'wb') as output:
        writer.write(output)
