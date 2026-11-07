"""Bounded LZ4 blocks and observed OPJU per-column UTF-8 string pools.

Reference numbers are byte offsets into a verified pool, never numeric cells.
Original encoded vectors and pool bytes remain alongside resolved values.
"""
import struct


def lz4_block(data,expected,maximum=4_000_000):
    if not 0<=expected<=maximum:raise ValueError('LZ4 output exceeds budget')
    out=bytearray();pos=0
    def length(value):
        nonlocal pos
        if value==15:
            while True:
                if pos>=len(data):raise ValueError('Truncated LZ4 length')
                extra=data[pos];pos+=1;value+=extra
                if value>expected:raise ValueError('Oversized LZ4 sequence')
                if extra!=255:break
        return value
    while pos<len(data):
        token=data[pos];pos+=1;count=length(token>>4)
        if pos+count>len(data)or len(out)+count>expected:raise ValueError('Invalid LZ4 literals')
        out.extend(data[pos:pos+count]);pos+=count
        if pos==len(data):break
        if pos+2>len(data):raise ValueError('Truncated LZ4 match')
        offset=int.from_bytes(data[pos:pos+2],'little');pos+=2
        count=length(token&15)+4
        if not 1<=offset<=len(out)or len(out)+count>expected:raise ValueError('Invalid LZ4 match')
        for _ in range(count):out.append(out[-offset])
    if len(out)!=expected:raise ValueError('LZ4 output size mismatch')
    return bytes(out)


def resolve_pool(data,item,stop):
    marker=b'_MSER_STRINGS_PSET'
    offset=data.find(marker,item['array_end'],stop)
    if offset<0:raise ValueError('Per-column string pool not found')
    pos=offset+len(marker)
    if data[pos:pos+2]!=b'\x05\x01':raise ValueError('Unsupported string pool envelope')
    stored=struct.unpack_from('<H',data,pos+2)[0];size=struct.unpack_from('<I',data,pos+4)[0]
    if stored<4 or pos+4+stored>stop:raise ValueError('String pool envelope exceeds column')
    raw=lz4_block(data[pos+8:pos+4+stored],size)
    if len(raw)<28 or raw[:8]!=b'\x77\x11\x11\x11\x02\0\x01\0':raise ValueError('Unsupported string pool revision')
    length,count=struct.unpack_from('<II',raw,16)
    if len(raw)!=28+length or raw[-4:]!=b'\0'*4:raise ValueError('String pool size mismatch')
    pool=raw[24:24+length];strings={};p=0
    while p<len(pool):
        end=pool.find(b'\0',p)
        if end<0:raise ValueError('Unterminated pool string')
        strings[p+1]=pool[p:end].decode('utf-8');p=end+1
    if len(strings)!=count:raise ValueError('String pool count mismatch')
    values=item['values'][:];row=0
    for block in item['blocks']:
        if block['kind']==1:
            for index in range(row,row+block['rows']):
                reference=values[index]
                if type(reference)is not int or reference not in strings:raise ValueError('Unknown string reference; not a numeric value')
                values[index]=strings[reference]
        row+=block['rows']
    if row!=len(values):raise ValueError('String vector row count mismatch')
    return {'values':values,'pool_offset':offset,'pool_raw_hex':raw.hex(),'strings':strings}
