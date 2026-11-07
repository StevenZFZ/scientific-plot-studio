"""Local, non-network editor links. URLs contain UUIDs, never commands or paths."""
import io,json,uuid
from pathlib import Path
from urllib.parse import urlsplit
from . import figure_object as obj
from .model import read_json,write_json


def root_dir():
    from .local_paths import data_dir
    return data_dir()/'figure-links'


def register(path,root=None):
    root=Path(root)if root else root_dir();path=Path(path).resolve(strict=True)
    info=obj.load(path);ident=info['manifest']['id'];ref=root/'references'/(ident+'.json');previous=read_json(ref)if ref.is_file()else None
    if previous and Path(previous['path'])!=path and Path(previous['path']).is_file():
        raise ValueError('此图形ID已有另一份本地源；未更改编辑链接，请打开已有源或导出新图形对象')
    write_json(ref,{'schema':'sps.figure-link/1','path':str(path),'sha256':info['sha256'],'revision':info['manifest']['revision']})
    return 'spsfigure://edit/'+ident


def resolve(url,root=None):
    root=Path(root)if root else root_dir();parts=urlsplit(url)
    if parts.scheme!='spsfigure'or parts.netloc!='edit'or parts.query or parts.fragment:raise ValueError('不支持的SPS编辑链接')
    ident=obj.identity(parts.path.removeprefix('/'))
    ref=root/'references'/(ident+'.json')
    entry=read_json(ref)if ref.is_file()else None
    if not isinstance(entry,dict)or not isinstance(entry.get('path'),str):raise ValueError('此电脑没有对应图形。请先用SPS打开带数据的Word/PPT文件或.spsfig对象恢复。')
    path=Path(entry['path']);info=obj.load(path)
    if info['manifest']['id']!=ident:raise ValueError('图形链接身份不一致')
    return path


def publish(project,root=None):
    root=Path(root)if root else root_dir();ident=str(uuid.uuid4());folder=root/ident;folder.mkdir(parents=True,exist_ok=False)
    path=folder/'figure.spsfig';info=obj.save(project,path,figure_id=ident);url=register(path,root)
    payload=path.read_bytes();png=obj.png_carrier(payload);svg=obj.svg_carrier(payload)
    (folder/'preview.png').write_bytes(png);(folder/'preview.svg').write_bytes(svg)
    return {'path':path,'url':url,'info':info,'png':png,'svg':svg}


def restore(data,root=None):
    root=Path(root)if root else root_dir();info=obj.unpack(data)
    ref=root/'references'/(info['manifest']['id']+'.json')
    if ref.is_file():
        existing=Path(read_json(ref)['path'])
        if existing.is_file():
            if obj.sha(existing.read_bytes())==info['sha256']:return existing
            raise ValueError('本机已有此图形的另一修订，未用嵌入旧版本覆盖本地编辑；请使用现有SPS对象或另存恢复包')
    folder=root/(info['manifest']['id']+'-'+info['sha256'][:12]);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'figure.spsfig'
    if path.exists()and obj.sha(path.read_bytes())!=info['sha256']:raise ValueError('恢复目标被修改，请另选输出')
    if not path.exists():
        with path.open('xb')as stream:stream.write(data)
    register(path,root);return path


def mime_data(project,root=None):
    from PySide6.QtCore import QMimeData,QByteArray
    from PySide6.QtGui import QImage
    from .transfer import MIME,encode
    item=publish(project,root);result=QMimeData()
    result.setData(obj.MIME,QByteArray(item['path'].read_bytes()));result.setData(MIME,QByteArray(encode(project)))
    result.setImageData(QImage.fromData(item['png'],'PNG'))
    result.setData('image/png',QByteArray(item['png']));result.setData('image/svg+xml',QByteArray(item['svg']))
    # Word for Mac turns file:// HTML images into unresolved INCLUDEPICTURE
    # fields (not embedded images). RTF carries the bytes inside the picture.
    twips=lambda mm:round(mm/25.4*1440)
    rtf=('{\\rtf1\\ansi{\\field{\\*\\fldinst HYPERLINK "'+item['url']+'"}'
         '{\\fldrslt{\\pict\\pngblip\\picwgoal'+str(twips(project.figure.width_mm))+
         '\\pichgoal'+str(twips(project.figure.height_mm))+'\n'+item['png'].hex()+'}}}}')
    result.setData('text/rtf',QByteArray(rtf.encode('ascii')))
    return result,item
