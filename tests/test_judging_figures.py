"""Synthetic OOXML figures test package boundaries, never photographic results."""
from copy import deepcopy
import hashlib
from io import BytesIO
import struct
import xml.etree.ElementTree as ET
import zlib

import pytest
from tools.create_judging_report import verify_added_images, OfficialFormError, REL, R, CT, IMAGE_REL


def picture():
    def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',32,32,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff'*96)*32))+chunk(b'IEND',b'')


@pytest.fixture
def package():
    a={'word/_rels/document.xml.rels':f'<Relationships xmlns="{REL}"><Relationship Id="rId1" Type="styles" Target="styles.xml"/></Relationships>'.encode(),
       '[Content_Types].xml':f'<Types xmlns="{CT}"/>'.encode()}
    b=deepcopy(a);blob=picture();name='word/media/ht-'+hashlib.sha256(blob).hexdigest()+'.png';b[name]=blob
    rels=ET.fromstring(b['word/_rels/document.xml.rels'])
    ET.SubElement(rels,'{'+REL+'}Relationship',Id='htImage1',Type=IMAGE_REL,Target=name[5:])
    b['word/_rels/document.xml.rels']=ET.tostring(rels)
    types=ET.fromstring(b['[Content_Types].xml']);ET.SubElement(types,'{'+CT+'}Default',Extension='png',ContentType='image/png')
    b['[Content_Types].xml']=ET.tostring(types)
    body=ET.Element('body');ET.SubElement(body,'blip',{'{'+R+'}embed':'htImage1'})
    return a,b,body,name


def test_internal_hash_named_figure_is_allowed(package):
    a,b,body,_=package
    assert verify_added_images(a,b,body)==1


@pytest.mark.parametrize('problem',['private_extra','changed_bytes','missing_original','missing_rel','external',
                                  'traversal','duplicate_id','original_rel_changed','orphan_image',
                                  'orphan_rel','external_blip','bad_type'])
def test_reject_uncontrolled_package_mutations(package,problem):
    a,b,body,name=package;rels=ET.fromstring(b['word/_rels/document.xml.rels'])
    if problem=='private_extra':b['private.txt']=b'not allowed'
    elif problem=='changed_bytes':b[name]+=b'changed'
    elif problem=='missing_original':b.pop('[Content_Types].xml')
    elif problem=='missing_rel':rels.remove(rels[-1])
    elif problem=='external':rels[-1].set('TargetMode','External')
    elif problem=='traversal':rels[-1].set('Target','../secret.png')
    elif problem=='duplicate_id':rels[-1].set('Id','rId1')
    elif problem=='original_rel_changed':rels[0].set('Target','changed.xml')
    elif problem=='orphan_image':rels[-1].set('Target','media/no-such-file.png')
    elif problem=='orphan_rel':body.clear()
    elif problem=='external_blip':body[0].set('{'+R+'}link','https://invalid.test/photo')
    elif problem=='bad_type':b['[Content_Types].xml']=f'<Types xmlns="{CT}"><Default Extension="exe" ContentType="application/octet-stream"/></Types>'.encode()
    b['word/_rels/document.xml.rels']=ET.tostring(rels)
    with pytest.raises(OfficialFormError):verify_added_images(a,b,body)


def replace_picture(package, blob, extension='png'):
    a,b,body,old_name=package
    name='word/media/ht-'+hashlib.sha256(blob).hexdigest()+'.'+extension
    del b[old_name]
    b[name]=blob
    rels=ET.fromstring(b['word/_rels/document.xml.rels'])
    rels[-1].set('Target',name[5:])
    b['word/_rels/document.xml.rels']=ET.tostring(rels)
    types=ET.fromstring(b['[Content_Types].xml'])
    types[-1].set('Extension',extension)
    types[-1].set('ContentType','image/png' if extension=='png' else 'image/jpeg')
    b['[Content_Types].xml']=ET.tostring(types)
    return a,b,body


def jpeg_picture():
    from PIL import Image
    buffer=BytesIO()
    Image.new('RGB',(32,32),'white').save(buffer,format='JPEG')
    return buffer.getvalue()


def test_fully_decodable_jpeg_is_allowed(package):
    assert verify_added_images(*replace_picture(package,jpeg_picture(),'jpg'))==1


@pytest.mark.parametrize('damage',['header_only','truncated_png','truncated_jpeg'])
def test_hash_matching_but_undecodable_figure_is_rejected(package,damage):
    extension='png'
    if damage=='header_only':
        blob=picture()[:24]+b'TEST_ONLY arbitrary bytes, not image data'
    elif damage=='truncated_png':
        blob=picture()[:-15]
    else:
        blob=jpeg_picture()[:-20]
        extension='jpg'
    with pytest.raises(OfficialFormError,match='fully decoded'):
        verify_added_images(*replace_picture(package,blob,extension))


def test_oversized_header_is_rejected_before_image_decode(package,monkeypatch):
    from PIL import Image
    blob=picture()[:16]+struct.pack('>II',6000,6000)+picture()[24:]
    def forbidden_decode(*args,**kwargs):
        pytest.fail('Decoder must not open an oversized image')
    monkeypatch.setattr(Image,'open',forbidden_decode)
    with pytest.raises(OfficialFormError,match='dimensions'):
        verify_added_images(*replace_picture(package,blob))
