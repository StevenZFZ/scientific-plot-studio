"""Personal-use research adapter for an explicitly selected external OPJU decoder.

No vendor runtime, formulas or scripts. Does not bundle the third-party module.
The modern framing below is independently checked against complete 147-byte
column records, capacity and CEFA array terminators. Raw vectors are retained.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import struct


DECODER_SHA256 = "6e5d7322723cee610dae63253a9a4460956fc68d91829527856fb0805a76d29e"


def properties(data, start, records, module):
    """Sample-bounded column records, including the observed 519-byte revision.

    IDs bind to complete dataset records, never guessed from displayed labels.
    Preserve raw property and label bytes for later format revisions.
    """
    result = {}
    for match in re.finditer(b"\x80", data[start:]):
        offset = start + match.start()
        try:
            length, _ = module.uint(data, offset + 1)
            if not 15 <= length <= 1000:
                continue
            raw, extension, end = module.object_record(data, offset)
            if len(raw) not in (515, 519) or raw[0] != 16 or raw[2:4] != b"\0\0":
                continue
            index = struct.unpack_from("<H", raw, 4)[0]
            name = raw[18:30].split(b"\0", 1)[0].decode("utf-8")
            if not 1 <= index <= len(records) or not name:
                continue
            size, pos = module.uint(data, end)
            label_bytes = b""
            if size:
                label_bytes, _ = module.rle_block(data, pos, size)
            label = label_bytes.rstrip(b"\0").decode("utf-8")
            parts = label.replace("\r\n", "\n").split("\n", 2)
            item = {"name": name, "long_name": parts[0].split("\0", 1)[0],
                    "units": parts[1].split("\0", 1)[0] if len(parts) > 1 else "",
                    "comments": parts[2] if len(parts) > 2 else "",
                    "rows": struct.unpack_from("<I", raw, 11)[0],
                    "designation_code": raw[17], "format_code": raw[30],
                    "metadata_offset": offset, "raw_hex": raw.hex(),
                    "extension_hex": extension.hex(), "label_hex": label_bytes.hex()}
            if index in result:
                # Two records even with the same label are ambiguous bindings.
                result[index] = {"conflict": True}
            else:
                result[index] = item
        except (module.DecodeError, UnicodeDecodeError, IndexError, struct.error):
            continue
    return result


def decode(source, decoder):
    source,decoder=Path(source),Path(decoder)
    if hashlib.sha256(decoder.read_bytes()).hexdigest() != DECODER_SHA256:
        raise ValueError("External decoder revision not reviewed; SHA256 mismatch")
    spec=importlib.util.spec_from_file_location('sps_external_opju_decoder',decoder)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data=source.read_bytes()
    if len(data)>50_000_000 or not data.startswith(b'CPYUA '):raise ValueError('Expected CPYUA OPJU <= 50 MB')
    records=[];datasets=[];rejected=[];internal=[];occupied_end=0;offset=0
    while True:
        offset=data.find(b'\x80',offset)
        if offset<0:break
        current=offset;offset+=1
        if current<occupied_end:continue
        try:
            length,_=module.uint(data,current+1)
            if not 15<=length<=300:continue
            raw,extension,end=module.object_record(data,current,maximum=2000)
            if len(raw)!=147:continue
            name_bytes=raw[88:113].split(b'\0',1)[0]
            match=module.NAME.fullmatch(name_bytes)
            if not match:continue
            name=name_bytes.decode('ascii')
        except (module.DecodeError,IndexError,struct.error):continue
        record={'dataset':name,'offset':current};records.append(record)
        try:
            tag=data[end]
            if tag not in (4,5):raise ValueError(f'unsupported storage tag {tag}')
            capacity,start=module.uint(data,end+1)
            if not 0<capacity<=2_000_000:raise ValueError('capacity out of bounds')
            cap,first,last=struct.unpack_from('<III',raw,25)
            if capacity!=cap:raise ValueError('capacity disagrees with column header')
            values,blocks,end=module.vector(data,start,capacity,reference_storage=tag==4)
            if data[end:end+2]!=b'\xce\xfa':raise ValueError('CEFA array terminator mismatch')
            item={'dataset_id':len(records),'dataset':name,'book_identifier':match[1].decode(),
                  'column_identifier':match[2].decode(),'sheet_suffix':match[3].decode()if match[3]else None,
                  'header_offset':current,'header_hex':raw.hex(),'header_extension_hex':extension.hex(),
                  'array_offset':start,'array_end':end+2,'capacity':capacity,'first_row':first,
                  'header_last_row':last,'values':values,'blocks':blocks,'storage_tag':tag}
            (internal if tag==4 else datasets).append(item);occupied_end=end+2
        except (module.DecodeError,ValueError,IndexError,struct.error)as error:
            rejected.append({**record,'reason':str(error)})
    start=max((d['array_end']for d in datasets+internal),default=0)
    column_properties=properties(data,start,records,module)
    books,sheets=module.project_metadata(data,start,records)
    for item in datasets+internal:
        metadata=column_properties.get(item['dataset_id'])
        if metadata and 'conflict' not in metadata and metadata['name'] != item['column_identifier']:
            metadata = {'conflict': True, 'reason': 'Stored ID/name binding is not independently confirmed',
                        'unverified_properties': metadata}
        item['metadata']=metadata
        logical=metadata.get('rows')if metadata and 'conflict'not in metadata else None
        if type(logical)is int and 0<=logical<=item['capacity']:
            item['logical_rows']=logical
            item['nonempty_beyond_logical']=sum(v is not None for v in item['values'][logical:])
        else:item['logical_rows']=None;item['nonempty_beyond_logical']=None
    if __package__:
        from .opju_graphs import graph_records
    else:
        from opju_graphs import graph_records
    graphs=graph_records(data,start,records,module)
    if __package__:
        from .opju_strings import resolve_pool
    else:
        from opju_strings import resolve_pool
    resolved=[];unresolved_pools=[]
    for item in internal:
        stop=min((r['offset']for r in records if r['offset']>item['header_offset']),default=len(data))
        try:
            pool=resolve_pool(data,item,stop)
            promoted=dict(item);promoted['encoded_values']=item['values'][:]
            promoted.update(pool);promoted['resolution']='verified per-column UTF-8 pool offsets'
            resolved.append(promoted)
        except (ValueError,UnicodeDecodeError,struct.error)as error:
            unresolved_pools.append({'dataset_id':item['dataset_id'],'dataset':item['dataset'],'reason':str(error)})

    return {'resolved_columns':resolved,'unresolved_pools':unresolved_pools,'graphs':graphs,'graph_status':'partial_stored_graph_records','schema':'sps.experimental.opju-probe/1','source':source.name,
            'source_sha256':hashlib.sha256(data).hexdigest(),'decoder_sha256':hashlib.sha256(decoder.read_bytes()).hexdigest(),
            'reader':'sch401 external primitives + SPS complete-record front end','datasets':datasets,
            'internal_reference_arrays':internal,'rejected':rejected,'workbooks':books,'sheets':sheets,
            'counts':{'datasets':len(datasets),'internal':len(internal),'rejected':len(rejected),
                      'numeric':sum(type(v)in(int,float)for d in datasets for v in d['values']),
                      'missing':sum(v is None for d in datasets for v in d['values']),
                      'text':sum(isinstance(v,str)for d in datasets for v in d['values']),
                      'resolved_reference_columns':len(resolved),'metadata_all':sum(bool(d['metadata'])and 'conflict'not in d['metadata']for d in datasets+resolved),
                      'metadata':sum(bool(d['metadata'])and 'conflict'not in d['metadata']for d in datasets)},
            'limits':['All capacity values retained; no row filtering or automatic plot pairing.',
                      'Graph records and explicit references are sample-bounded; unsupported styles remain explicit.',
                      'Origin numerical oracle has not been run; candidate coverage is sample-bounded.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('output');parser.add_argument('--decoder',required=True)
    args=parser.parse_args();out=Path(args.output)
    if out.exists():raise SystemExit('Output exists')
    result=decode(args.source,args.decoder)
    with out.open('x')as stream:json.dump(result,stream,ensure_ascii=False,allow_nan=False)
    print(json.dumps(result['counts']))
