"""Explicit linked artwork exports; external artwork edits are never overwritten."""
from pathlib import Path
import json,os,tempfile
from . import figure_object as obj,figure_links as links
from .model import canonical

MANIFEST='sps-assets.json'


def export(project,directory,root=None):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    source=directory/'figure.spsfig';info=obj.save(project,source)
    links.register(source,root)
    payload=source.read_bytes();images={'figure.svg':obj.svg_carrier(payload),'figure.png':obj.png_carrier(payload)}
    for name,data in images.items():(directory/name).write_bytes(data)
    manifest={'schema':'sps.linked-assets/1','id':info['manifest']['id'],
              'images':{n:obj.sha(b)for n,b in images.items()}}
    (directory/MANIFEST).write_text(canonical(manifest),encoding='utf-8')
    return {'directory':str(directory),'source':str(source),'artwork':str(directory/'figure.svg')}


def refresh(directory):
    directory=Path(directory);m=json.loads((directory/MANIFEST).read_text())
    if m.get('schema')!='sps.linked-assets/1' or set(m.get('images',{}))!={'figure.svg','figure.png'}:raise ValueError('不是SPS链接资源目录')
    payload=(directory/'figure.spsfig').read_bytes();info=obj.unpack(payload)
    if info['manifest']['id']!=m['id']:raise ValueError('链接资源与图形工程身份不一致')
    for name,digest in m['images'].items():
        if obj.sha((directory/name).read_bytes())!=digest:raise ValueError('链接图像已被外部修改，未覆盖；请导出新的链接资源包')
    images={'figure.svg':obj.svg_carrier(payload),'figure.png':obj.png_carrier(payload)}
    # Stage all bytes before replacing. Original bytes retained for IO rollback.
    m['images']={n:obj.sha(b)for n,b in images.items()};images[MANIFEST]=canonical(m).encode()
    previous={n:(directory/n).read_bytes()for n in images};staged={}
    try:
        for name,data in images.items():
            fd,temp=tempfile.mkstemp(prefix='.sps-assets-',dir=directory)
            with os.fdopen(fd,'wb')as stream:stream.write(data)
            staged[name]=Path(temp)
        for name,temp in staged.items():os.replace(temp,directory/name)
    except BaseException:
        for name,data in previous.items():(directory/name).write_bytes(data)
        raise
    finally:
        for temp in staged.values():temp.unlink(missing_ok=True)
    return {'directory':str(directory),'revision':info['manifest']['revision']}
