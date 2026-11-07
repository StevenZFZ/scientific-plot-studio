"""Pictures with SPS editor links and portable data in DOCX/PPTX.

No OLE activation or macros. Updates create a new document and preserve host
layout. A hyperlink is not a host double-click object editor or a live link.
"""
import io,json,zipfile,posixpath
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape,quoteattr
from . import figure_object as obj,figure_links as links
from .model import canonical
from .office import package,read_part,xml,relationships

MANIFEST='sps/figures.json'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
OFFICE_REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
CTYPE='http://schemas.openxmlformats.org/package/2006/content-types'


def _write_zip(parts,path):
    path=Path(path)
    if path.exists():raise FileExistsError('目标文档已存在，请另存')
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED)as archive:
        for name,data in parts.items():archive.writestr(name,data)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb')as output:output.write(stream.getvalue())


def export(project,path,root=None):
    path=Path(path);kind=path.suffix.lower()
    if kind not in('.docx','.pptx'):raise ValueError('请选择DOCX或PPTX')
    if path.exists():raise FileExistsError('文档已存在，请另存')
    item=links.publish(project,root);payload=item['path'].read_bytes();info=item['info'];ident=info['manifest']['id']
    image=info['files']['preview.png'];url=item['url']
    if kind=='.pptx':
        from pptx import Presentation
        from pptx.util import Mm
        deck=Presentation();deck.slide_width=Mm(project.figure.width_mm+20);deck.slide_height=Mm(project.figure.height_mm+20)
        slide=deck.slides.add_slide(deck.slide_layouts[6]);picture=slide.shapes.add_picture(io.BytesIO(image),Mm(10),Mm(10),width=Mm(project.figure.width_mm),height=Mm(project.figure.height_mm))
        picture.name='SPSFigure:'+ident;picture.click_action.hyperlink.address=url
        picture._element.nvPicPr.cNvPr.set('descr','在SPS编辑；此图包含完整科研工程。')
        stream=io.BytesIO();deck.save(stream)
        with zipfile.ZipFile(stream)as archive:parts={n:archive.read(n)for n in archive.namelist()}
        media='ppt/media/image1.png';main='ppt/slides/slide1.xml';relfile='ppt/slides/_rels/slide1.xml.rels'
    else:
        width=min(project.figure.width_mm,170);height=width*project.figure.height_mm/project.figure.width_mm
        cx,cy=round(width*36000),round(height*36000)
        doc=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="{R}" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="{A}" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body><w:p><w:r><w:drawing><wp:inline><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="1" name="SPSFigure:{ident}" descr="在SPS编辑；包含完整科研工程"><a:hlinkClick r:id="rIdEdit"/></wp:docPr><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="SPS figure"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p><w:p><w:r><w:t>选中图像后打开链接，在 SPS 中编辑。修改后通过 SPS 生成更新的文档副本。</w:t></w:r></w:p><w:sectPr><w:pgSz w="11906" h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>'''
        rels=f'<Relationships xmlns="{REL}"><Relationship Id="rIdImage" Type="{OFFICE_REL}image" Target="media/figure.png"/><Relationship Id="rIdEdit" Type="{OFFICE_REL}hyperlink" Target={quoteattr(url)} TargetMode="External"/></Relationships>'
        parts={'[Content_Types].xml':f'<Types xmlns="{CTYPE}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'.encode(),
         '_rels/.rels':f'<Relationships xmlns="{REL}"><Relationship Id="rIdOffice" Type="{OFFICE_REL}officeDocument" Target="word/document.xml"/></Relationships>'.encode(),
         'word/document.xml':doc.encode(),'word/_rels/document.xml.rels':rels.encode(),'word/media/figure.png':image}
        media='word/media/figure.png';main='word/document.xml';relfile='word/_rels/document.xml.rels'
    portable='sps/figures/'+ident+'.spsfig';parts[portable]=payload
    manifest={'schema':'sps.office-figures/1','figures':[{'id':ident,'image':media,'object':portable,'main':main,'image_sha256':obj.sha(image),'object_sha256':obj.sha(payload),'width_mm':project.figure.width_mm,'height_mm':project.figure.height_mm}]}
    parts[MANIFEST]=canonical(manifest).encode()
    ct=xml(parts['[Content_Types].xml'])
    ET.SubElement(ct,'{'+CTYPE+'}Default',Extension='spsfig',ContentType='application/vnd.sps.figure+zip')
    ET.SubElement(ct,'{'+CTYPE+'}Override',PartName='/'+MANIFEST,ContentType='application/json')
    parts['[Content_Types].xml']=ET.tostring(ct,encoding='utf-8',xml_declaration=True)
    rels=xml(parts[relfile]);base=posixpath.dirname(main)
    ET.SubElement(rels,'{'+REL+'}Relationship',Id='rIdSPSManifest',Type='urn:sps:relationships:figures',Target=posixpath.relpath(MANIFEST,base))
    ET.SubElement(rels,'{'+REL+'}Relationship',Id='rIdSPSFigure',Type='urn:sps:relationships:figure',Target=posixpath.relpath(portable,base))
    parts[relfile]=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
    _write_zip(parts,path)
    return {'file':str(path),'url':url,'figure':str(item['path']),'id':ident,'limits':'Link opens SPS; not generic Mac OLE double-click. Refresh creates a new document.'}


def _picture_part(archive, ident):
    """Resolve the actual drawing after Office renumbers media/relationship IDs."""
    matches=set()
    for main in archive.namelist():
        if not (main=='word/document.xml' or (main.startswith('ppt/slides/slide') and main.endswith('.xml'))):continue
        tree=xml(read_part(archive,main));rels=relationships(archive,main)
        for drawing in tree.iter():
            local=drawing.tag.rsplit('}',1)[-1]
            if local not in ('inline','anchor','pic'):continue
            if not any(e.get('name')=='SPSFigure:'+ident for e in drawing.iter()):continue
            for blip in drawing.iter('{'+A+'}blip'):
                rel=rels.get(blip.get('{'+R+'}embed'),{})
                if not rel.get('external') and rel.get('type')==OFFICE_REL+'image' and rel.get('part'):
                    matches.add((main,rel['part']))
    if len(matches)!=1:raise ValueError('无法唯一匹配SPS图形与文档图片；未替换任何内容，请重新导出')
    return next(iter(matches))


def recover(path):
    """Recover embedded objects without following their editor hyperlinks."""
    with package(path)as archive:
        names=archive.namelist();result=[]
        if MANIFEST in names:
            m=json.loads(read_part(archive,MANIFEST,1_000_000))
            if not isinstance(m,dict)or m.get('schema')!='sps.office-figures/1'or not isinstance(m.get('figures'),list)or not 1<=len(m['figures'])<=100:raise ValueError('Office SPS图形清单无效')
            for item in m['figures']:
                obj.identity(item['id']);data=read_part(archive,item['object'])
                if obj.sha(data)!=item['object_sha256']:raise ValueError('Office嵌入工程摘要变化')
                info=obj.unpack(data)
                if info['manifest']['id']!=item['id']:raise ValueError('Office图形身份不一致')
                main,media=_picture_part(archive,item['id'])
                item=dict(item,main=main,image=media)
                image=read_part(archive,media)
                if obj.sha(image)!=item['image_sha256']:raise ValueError('Office图像已被重写，未将旧工程冒充最新图像；请保留原文档并使用SPS源对象')
                result.append({'info':info,'package':data,'record':item})
            return result
        # Ordinary copy/paste may retain the self-contained PNG chunk but no
        # custom Office part. Never infer data from pixels when it is absent.
        for name in names:
            if name.endswith('.png')and('/media/'in name):
                data=read_part(archive,name)
                if obj.PNG_TAG not in data:continue
                try:info=obj.from_png(data)
                except ValueError:continue
                result.append({'info':info,'package':info['package'],'record':{'image':name}})
        if not result:raise ValueError('文档没有保留下可恢复SPS工程；普通图片不能还原原始数值')
        return result


def refresh(source,target,root=None):
    """Clone a closed saved Office file; replace only our sealed picture parts."""
    source,target=Path(source),Path(target)
    if source.resolve()==target.resolve()or target.exists():raise ValueError('更新必须使用新文档文件名，保留原文档')
    if source.suffix.lower()!=target.suffix.lower():raise ValueError('更新后的文档扩展名需保持一致')
    records=recover(source)
    if any('object'not in e['record']for e in records):raise ValueError('此粘贴文档只保留PNG数据，尚未建立安全更新映射；可恢复到SPS后重新生成文档')
    with package(source)as archive:parts={n:read_part(archive,n)for n in archive.namelist()}
    m=json.loads(parts[MANIFEST]);changed=[]
    resolved={e['record']['id']:e['record'] for e in records}
    media=[e['record']['image'] for e in records]
    if len(set(media))!=len(media):raise ValueError('多个SPS对象共用文档图片，未进行有歧义的更新')
    for entry in m['figures']:
        entry.update(main=resolved[entry['id']]['main'],image=resolved[entry['id']]['image'])
        path=links.resolve('spsfigure://edit/'+entry['id'],root);data=path.read_bytes();info=obj.unpack(data)
        parts[entry['image']]=info['files']['preview.png'];parts[entry['object']]=data
        entry['image_sha256']=obj.sha(parts[entry['image']]);entry['object_sha256']=obj.sha(data)
        changed.append({'id':entry['id'],'revision':info['manifest']['revision'],'aspect_changed':abs(info['manifest']['width_mm']/info['manifest']['height_mm']-entry['width_mm']/entry['height_mm'])>1e-6})
        entry['width_mm']=info['manifest']['width_mm'];entry['height_mm']=info['manifest']['height_mm']
    parts[MANIFEST]=canonical(m).encode();_write_zip(parts,target)
    return {'file':str(target),'updated':changed,'layout':'Host positions, sizes, cropping and other content preserved; review if aspect changed.'}
