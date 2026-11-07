"""Portable SPS figure: complete native document, selected view and sealed previews.

No external assets, scripts, extraction paths or executable contents. SHA values
verify integrity, not authorship. This format does not implement an OLE server.
"""
from __future__ import annotations
import hashlib,io,json,os,re,struct,tempfile,uuid,zipfile,zlib
from pathlib import Path
from PIL import Image
from .model import canonical
from .transfer import encode,decode

SCHEMA='sps.figure/1'
MIME='application/x-sps-figure'
MEMBERS={'manifest.json','project.json','preview.png','preview.svg'}
MAX_BYTES=80_000_000
MAX_MEMBER=50_000_000
PNG_TAG=b'spSf'


def sha(data):return hashlib.sha256(data).hexdigest()


def identity(value):
    if not isinstance(value,str)or str(uuid.UUID(value))!=value:raise ValueError('图形对象ID无效')
    return value


def _png_digest(data):
    try:
        with Image.open(io.BytesIO(data),formats=['PNG'])as image:
            if image.format!='PNG' or image.width*image.height>30_000_000:raise ValueError('图形预览PNG无效或过大')
            return sha(struct.pack('>II',*image.size)+image.convert('RGBA').tobytes())
    except (OSError,Image.DecompressionBombError)as error:
        raise ValueError('PNG预览结构无效')from error


def build(project,*,figure_id=None,revision=1,dpi=150):
    from .render import preflight
    project.validate()
    if type(revision)is not int or not 1<=revision<=1_000_000:raise ValueError('图形修订号无效')
    figure_id=identity(figure_id)if figure_id else str(uuid.uuid4())
    fig,checks=preflight(project,dpi)
    png,svg=io.BytesIO(),io.BytesIO()
    import matplotlib as mpl
    with mpl.rc_context({'svg.fonttype':'path','svg.hashsalt':'sps-figure-v1'}):
        fig.savefig(png,format='png',dpi=dpi,transparent=True,bbox_inches=None)
        fig.savefig(svg,format='svg',transparent=True,bbox_inches=None)
    payloads={'project.json':encode(project),'preview.png':png.getvalue(),'preview.svg':svg.getvalue()}
    if any(len(b)>MAX_MEMBER for b in payloads.values()):raise ValueError('图形对象部件超过50MB')
    page,layer=project.context
    manifest={'schema':SCHEMA,'id':figure_id,'revision':revision,
      'context':{'page':page,'layer':layer},'width_mm':project.figure.width_mm,'height_mm':project.figure.height_mm,
      'preview_scope':'all layers of selected page; complete document retained',
      'files':{n:sha(b)for n,b in payloads.items()},'png_pixels':_png_digest(payloads['preview.png'])}
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED)as archive:
        archive.writestr('manifest.json',canonical(manifest))
        for name,data in payloads.items():archive.writestr(name,data)
    result=output.getvalue()
    if len(result)>MAX_BYTES:raise ValueError('图形对象超过80MB')
    return result


def unpack(data):
    if not isinstance(data,bytes)or len(data)>MAX_BYTES:raise ValueError('图形对象无效或超过80MB')
    try:
        with zipfile.ZipFile(io.BytesIO(data))as archive:
            entries=archive.infolist();names=[i.filename for i in entries]
            if len(entries)!=4 or set(names)!=MEMBERS:raise ValueError('图形对象部件无效或重复')
            if any(e.file_size>MAX_MEMBER or e.flag_bits&1 for e in entries)or sum(e.file_size for e in entries)>100_000_000:raise ValueError('图形对象展开超出限制或被加密')
            blobs={name:archive.read(name)for name in names}
    except (zipfile.BadZipFile,RuntimeError)as error:raise ValueError('图形对象压缩结构损坏')from error
    if len(blobs['manifest.json'])>100_000:raise ValueError('图形清单过大')
    m=json.loads(blobs['manifest.json'])
    required={'schema','id','revision','context','width_mm','height_mm','preview_scope','files','png_pixels'}
    if not isinstance(m,dict)or set(m)!=required or m['schema']!=SCHEMA:raise ValueError('不支持的图形清单')
    identity(m['id'])
    if type(m['revision'])is not int or not 1<=m['revision']<=1_000_000:raise ValueError('修订号无效')
    if not isinstance(m['files'],dict)or set(m['files'])!=MEMBERS-{'manifest.json'}:raise ValueError('图形摘要清单无效')
    for name,digest in m['files'].items():
        if digest!=sha(blobs[name]):raise ValueError('图形对象摘要不一致：'+name)
    project=decode(blobs['project.json'])
    c=m['context']
    if not isinstance(c,dict)or set(c)!={'page','layer'}:raise ValueError('图形视图上下文无效')
    project.select_context(c['page'],c['layer'])
    if (m['width_mm'],m['height_mm'])!=(project.figure.width_mm,project.figure.height_mm):raise ValueError('图形尺寸和工程不一致')
    if _png_digest(blobs['preview.png'])!=m['png_pixels']:raise ValueError('图像像素与清单不一致')
    # SVG is never executed or fetched. Only our self-contained preview subset.
    from .office import xml
    svg=blobs['preview.svg']
    # Matplotlib's standard SVG doctype is removed before strict parser use.
    clean=re.sub(br'<!DOCTYPE\s+svg[^>]*>',b'',svg,flags=re.S)
    root=xml(clean)
    for e in root.iter():
        if e.tag.rsplit('}',1)[-1].lower()in('script','foreignobject','iframe'):raise ValueError('SVG含不支持的活动对象')
        for key,value in e.attrib.items():
            if key.rsplit('}',1)[-1].lower()in('href','src')and not value.startswith('#'):raise ValueError('SVG不接受外部资源')
    return {'project':project,'manifest':m,'files':blobs,'sha256':sha(data)}


def load(path):
    path=Path(path)
    if path.stat().st_size>MAX_BYTES:raise ValueError('图形对象超过80MB')
    return unpack(path.read_bytes())


def save(project,path,*,expected_sha=None,figure_id=None,revision=1):
    path=Path(path)
    if path.suffix.lower()!='.spsfig':raise ValueError('图形对象扩展名需为.spsfig')
    if expected_sha is None and path.exists():raise FileExistsError('图形对象已存在，请另存')
    if expected_sha is not None:
        if not path.is_file()or sha(path.read_bytes())!=expected_sha:raise ValueError('图形对象被其他程序修改，未覆盖；请另存')
        previous=load(path)['manifest'];figure_id=previous['id'];revision=previous['revision']+1
    data=build(project,figure_id=figure_id,revision=revision);unpack(data)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.sps-figure-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb')as stream:stream.write(data)
        if expected_sha is not None:
            if sha(path.read_bytes())!=expected_sha:raise ValueError('保存期间图形源变化，未覆盖')
            os.replace(temp,path)
        else:
            # Exclusive publication: never replace a same-name file created meanwhile.
            os.link(temp,path);os.unlink(temp)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return unpack(data)


def png_carrier(data):
    info=unpack(data);png=info['files']['preview.png']
    chunk=struct.pack('>I',len(data))+PNG_TAG+data+struct.pack('>I',zlib.crc32(PNG_TAG+data)&0xffffffff)
    return png[:-12]+chunk+png[-12:]


def from_png(data):
    if len(data)>MAX_BYTES or not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('不是支持的PNG')
    pos=8;payloads=[]
    while pos<len(data):
        if pos+12>len(data):raise ValueError('PNG块截断')
        length=struct.unpack_from('>I',data,pos)[0];kind=data[pos+4:pos+8];stop=pos+12+length
        if stop>len(data):raise ValueError('PNG块长度无效')
        if kind==PNG_TAG:
            payload=data[pos+8:stop-4]
            if zlib.crc32(kind+payload)&0xffffffff!=struct.unpack_from('>I',data,stop-4)[0]:raise ValueError('PNG工程块损坏')
            payloads.append(payload)
        pos=stop
        if kind==b'IEND':break
    if len(payloads)!=1:raise ValueError('PNG未包含唯一的SPS工程；普通图片无法还原数据')
    result=unpack(payloads[0])
    if _png_digest(data)!=result['manifest']['png_pixels']:raise ValueError('PNG图像已经改变，不能冒充原工程预览')
    result['package']=payloads[0];return result


def svg_carrier(data):
    import base64
    info=unpack(data);svg=info['files']['preview.svg']
    match=re.search(br'<svg\b[^>]*>',svg,re.S)
    if not match:raise ValueError('SVG根无效')
    metadata=b'<metadata id="sps-figure-v1">'+base64.b64encode(data)+b'</metadata>'
    return svg[:match.end()]+metadata+svg[match.end():]


def from_svg(data):
    import base64
    if len(data)>110_000_000:raise ValueError('SVG超过限制')
    match=re.search(br'<metadata id="sps-figure-v1">([A-Za-z0-9+/=]+)</metadata>',data)
    if not match:raise ValueError('SVG没有可恢复SPS工程')
    payload=base64.b64decode(match[1],validate=True);info=unpack(payload)
    if sha(data[:match.start()]+data[match.end():])!=info['manifest']['files']['preview.svg']:raise ValueError('SVG路径已改变，不能把旧工程当最新编辑结果')
    info['package']=payload;return info
