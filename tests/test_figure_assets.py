from pathlib import Path
import pytest
from sps import figure_assets as assets,figure_object as obj
from sps.model import demo


def test_linked_artwork_matches_editable_source_and_refreshes_explicitly(tmp_path):
    folder=tmp_path/'assets';assets.export(demo(),folder,tmp_path/'links');source=folder/'figure.spsfig'
    info=obj.load(source);edited=info['project'];edited.figure.title='updated linked artwork'
    obj.save(edited,source,expected_sha=info['sha256']);report=assets.refresh(folder)
    assert report['revision']==2
    assert obj.from_svg((folder/'figure.svg').read_bytes())['project'].figure.title==edited.figure.title
    assert obj.from_png((folder/'figure.png').read_bytes())['project'].to_dict()==edited.to_dict()
    with pytest.raises(FileExistsError):assets.export(demo(),folder,tmp_path/'links')


def test_externally_edited_artwork_is_preserved(tmp_path):
    folder=tmp_path/'assets';assets.export(demo(),folder,tmp_path/'links');svg=folder/'figure.svg'
    changed=svg.read_bytes().replace(b'<svg ',b'<svg data-external-edit="yes" ',1);svg.write_bytes(changed)
    with pytest.raises(ValueError,match='外部修改'):assets.refresh(folder)
    assert svg.read_bytes()==changed
