"""Synthetic binary fixtures only; real research projects stay private."""
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from sps.origin_reader import Column, OriginProject, Spreadsheet
from sps.opju_worker import DECODER_SHA256

ROOT = Path(__file__).resolve().parents[1]
DECODER = ROOT / '.local-tools/origin-evaluation/sch401-opju/opju_decode.py'


def uint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def literal(raw):
    return b''.join(bytes([len(raw[i:i+127])]) + raw[i:i+127] for i in range(0, len(raw), 127))


def record(raw, extension=b''):
    payload = literal(raw)
    return b'\x80' + uint(len(payload)) + payload + uint(len(extension)) + extension + (b'\n' if extension else b'')


def fixture(path, values=(1.0000000000000002, -0.0), *, metadata=True, bad_marker=False, capacity=None, extension=b'24-byte revision\0\0\0\0\0\0\0\0', vector=None):
    header = bytearray(147)
    struct.pack_into('<III', header, 25, len(values), 0, len(values))
    header[88:95] = b'Book1_A'
    if vector is None:
        vector = b''.join(b'\0\0' + (b'\x65' if x is None else b'\x50' + struct.pack('<d', x)) for x in values)
    data = b'CPYUA 4.3748 212\n' + record(header, extension) + b'\x05' + uint(len(values) if capacity is None else capacity) + vector + (b'XX' if bad_marker else b'\xce\xfa')
    if metadata:
        props = bytearray(519)
        props[0] = 16
        struct.pack_into('<H', props, 4, 1)
        struct.pack_into('<I', props, 11, 1)  # Must NOT trim second nonempty row.
        props[17] = 3
        props[18] = 65
        label = literal(b'Distance\nmm\nsynthetic fixture\0')
        data += record(props) + uint(len(label)) + label + b'\n'
    path.write_bytes(data)
    return data


@pytest.fixture
def decoder():
    if not DECODER.exists():
        pytest.skip('Optional external decoder not bundled; see docs/ORIGIN_HEADLESS.md')
    return DECODER


def test_signature_no_extension_guess_or_empty_name_scan(tmp_path, decoder):
    p = tmp_path/'fake.opju'
    p.write_bytes(b'CPYUA 4.3748 212\nBook1_A and Book1_B only')
    with pytest.raises(ValueError, match='没有成功解码'):
        OriginProject(p, opju_decoder=decoder)
    p.write_bytes(b'Book1_A only')
    with pytest.raises(ValueError, match='文件头'):
        OriginProject(p, opju_decoder=decoder)


def test_explicit_decoder_hash_checked_before_import(tmp_path):
    p=tmp_path/'fixture.opju';fixture(p)
    sentinel=tmp_path/'ran'
    decoder=tmp_path/'decoder.py'
    decoder.write_text(f'from pathlib import Path\nPath({str(sentinel)!r}).touch()\n')
    with pytest.raises(ValueError, match='SHA256'):
        OriginProject(p, opju_decoder=decoder)
    assert not sentinel.exists()


def test_modern_extension_precision_properties_and_no_trimming(tmp_path, decoder):
    source=tmp_path/'fixture.opju';before=fixture(source)
    p=OriginProject(source, opju_decoder=decoder)
    c=p.spreadsheets[0].columns[0]
    assert c.data == [1.0000000000000002, -0.0] and math.copysign(1,c.data[1]) == -1
    assert c.role=='X' and c.units=='mm' and c.long_name=='Distance'
    assert c.logical_rows==1 and c.rows==2
    assert c.metadata['nonempty_beyond_logical']==1
    assert p.status=='partial_data_recovery' and source.read_bytes()==before
    target=p.export_csv(tmp_path/'out')
    saved=json.loads((target/'project.json').read_text())
    assert saved['raw']==p.raw and saved['spreadsheets'][0]['columns'][0]['data']==c.data
    with (target/'sheet-001.csv').open(newline='')as f:rows=list(csv.reader(f))
    assert rows==[['A'],['1.0000000000000002'],['-0.0']]
    with pytest.raises(ValueError, match='已存在'):p.export_csv(target)


@pytest.mark.parametrize('options', [{'bad_marker':True},{'capacity':3},{'vector':b'unsupported'}])
def test_corrupt_vectors_never_report_success(tmp_path, decoder, options):
    source=tmp_path/'broken.opju';fixture(source,**options)
    with pytest.raises(ValueError, match='没有成功解码'):
        OriginProject(source,opju_decoder=decoder)


def test_fpc_known_double_bits_and_missing_preserved(tmp_path, decoder):
    # Hand-built FPC stream: size-1 FCM table, full residuals, low nibble first.
    # First predictor=0; next predictor is the preceding bit pattern.
    a,b = 0x3ff0000000000001, 0x8000000000000000
    vector=b'\xff\xff\x02\x00\x03\x00\x77'+struct.pack('<QQ',a,a^b)
    source=tmp_path/'fpc.opju';fixture(source,vector=vector,metadata=False)
    p=OriginProject(source,opju_decoder=decoder)
    values=p.spreadsheets[0].columns[0].data
    assert [struct.unpack('<Q',struct.pack('<d',v))[0]for v in values]==[a,b]
    assert p.spreadsheets[0].columns[0].role is None
    source2=tmp_path/'missing.opju';fixture(source2,(None,0.0,None),metadata=False)
    assert OriginProject(source2,opju_decoder=decoder).spreadsheets[0].columns[0].data==[None,0.0,None]


def test_csv_quotes_and_ragged_lengths_stay_in_dictionary(tmp_path):
    s=Spreadsheet('../../source', [Column('a,b',[1.,None,3.]),Column('text',['quoted,"字"\nline'])])
    data=s.to_dict();data['a,b'][0]=999
    assert s.columns[0].data[0]==1.
    with pytest.raises(ValueError,match='容量不同'):s.to_dataframe()
    p=tmp_path/'quoted.csv';s.to_csv(p)
    with p.open(newline='')as f:rows=list(csv.reader(f))
    assert rows==[['a,b','text'],['1.0','quoted,"字"\nline'],['',''],['3.0','']]
    with pytest.raises(FileExistsError):s.to_csv(p)
    with pytest.raises(ValueError,match='重复列名'):
        Spreadsheet('same',[Column('A',[1]),Column('A',[2])]).to_dict()


def test_cli_and_python_api_import_no_gui(tmp_path, decoder):
    source=tmp_path/'source.opju';fixture(source)
    env=os.environ.copy();env.pop('DISPLAY',None)
    command=[sys.executable,'-m','sps','origin-read',str(source),str(tmp_path/'out'),'--decoder',str(decoder)]
    r=subprocess.run(command,capture_output=True,text=True,env=env,timeout=10)
    assert r.returncode==0, r.stderr
    assert json.loads(r.stdout)['columns']==1
    assert subprocess.run(command,capture_output=True,env=env,timeout=10).returncode==2
    code='from sps.origin_reader import OriginProject; import sys; p=OriginProject(sys.argv[1],opju_decoder=sys.argv[2]); assert not any(x.startswith(("PySide6", "tkinter"))for x in sys.modules)'
    r=subprocess.run([sys.executable,'-c',code,str(source),str(decoder)],capture_output=True,text=True,env=env,timeout=10)
    assert r.returncode==0,r.stderr


def test_ambiguous_id_name_binding_never_assigns_units_or_roles(tmp_path, decoder):
    source=tmp_path/'alias.opju';data=fixture(source)
    source.write_bytes(data.replace(b'Book1_A',b'Book1_B'))
    p=OriginProject(source,opju_decoder=decoder)
    c=p.spreadsheets[0].columns[0]
    assert c.name=='B' and c.role is None and c.units is None and c.logical_rows is None
    assert c.metadata['metadata']['conflict']
    assert c.metadata['metadata']['unverified_properties']['units']=='mm'
    assert c.rows==2 and p.raw['counts']['metadata']==0


def test_real_pandas_object_conversion_preserves_missing_and_double_bits():
    pytest.importorskip('pandas')
    s=Spreadsheet('fixture',[Column('A',[1.0000000000000002,None,-0.0]),Column('B',['literal',None,'=1+1'])])
    df=s.to_dataframe()
    assert df.shape==(3,2) and str(df.dtypes['A'])=='object'
    assert df.iloc[1,0] is None and df.iloc[2,1]=='=1+1'
    assert struct.pack('<d',df.iloc[0,0])==struct.pack('<Q',0x3ff0000000000001)
    assert math.copysign(1,df.iloc[2,0])==-1
