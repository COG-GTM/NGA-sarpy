import json

import numpy
import pytest

from sarpy.io.complex.sicd_elements.SICD import SICDType
from sarpy.utils import dump_metadata


@pytest.fixture()
def sicd_structure(tests_path):
    xml_file = tests_path / 'data/example.sicd.xml'
    return SICDType().from_xml_file(xml_file)


class _FakeSICDReader(object):
    def __init__(self, sicd_meta):
        self.sicd_meta = sicd_meta
        self.closed = False

    def close(self):
        self.closed = True


def test_normalize_structures():
    assert dump_metadata._normalize_structures(None) == []
    assert dump_metadata._normalize_structures('a') == ['a']
    assert dump_metadata._normalize_structures(['a', None, 'b']) == ['a', 'b']
    assert dump_metadata._normalize_structures(('a', 'b')) == ['a', 'b']


def test_json_default():
    assert dump_metadata._json_default(numpy.int64(3)) == 3
    assert isinstance(dump_metadata._json_default(numpy.int64(3)), int)
    assert dump_metadata._json_default(numpy.float64(1.5)) == 1.5
    assert isinstance(dump_metadata._json_default(numpy.float64(1.5)), float)
    assert dump_metadata._json_default(numpy.array([1, 2])) == [1, 2]
    with pytest.raises(TypeError):
        dump_metadata._json_default(object())


def test_sicd_summary(sicd_structure):
    summary = dump_metadata._sicd_summary(sicd_structure)
    assert summary['collector_name'] == 'Synthetic'
    assert summary['core_name'] == 'SyntheticCore'
    assert summary['collect_type'] == 'MONOSTATIC'
    assert summary['mode_type'] == 'SPOTLIGHT'
    assert summary['num_rows'] == 1494
    assert summary['num_cols'] == 1723
    assert summary['pixel_type'] == 'RE32F_IM32F'
    assert summary['scp_lat'] == 0
    assert summary['scp_lon'] == 0
    assert summary['scp_hae'] == 0
    assert summary['tx_rcv_polarization'] == 'V:V'
    # the summary must be JSON serializable
    json.dumps(summary, default=dump_metadata._json_default)


def test_get_metadata_full(monkeypatch, sicd_structure):
    reader = _FakeSICDReader(sicd_structure)
    monkeypatch.setattr(
        dump_metadata, '_open_reader', lambda file_name: ('SICD', reader))

    metadata = dump_metadata.get_metadata('example.sicd')
    assert metadata['file_name'] == 'example.sicd'
    assert metadata['file_type'] == 'SICD'
    assert len(metadata['meta']) == 1
    assert metadata['meta'][0]['CollectionInfo']['CollectorName'] == 'Synthetic'
    assert reader.closed is True


def test_get_metadata_summary(monkeypatch, sicd_structure):
    reader = _FakeSICDReader(sicd_structure)
    monkeypatch.setattr(
        dump_metadata, '_open_reader', lambda file_name: ('SICD', reader))

    metadata = dump_metadata.get_metadata('example.sicd', summary=True)
    assert metadata['meta'][0]['collector_name'] == 'Synthetic'
    assert 'CollectionInfo' not in metadata['meta'][0]


def test_dump_metadata_string_is_valid_json(monkeypatch, sicd_structure):
    reader = _FakeSICDReader(sicd_structure)
    monkeypatch.setattr(
        dump_metadata, '_open_reader', lambda file_name: ('SICD', reader))

    result = dump_metadata.dump_metadata('example.sicd', dest='string')
    parsed = json.loads(result)
    assert parsed['file_type'] == 'SICD'
    assert parsed['meta'][0]['CollectionInfo']['CollectorName'] == 'Synthetic'


def test_dump_metadata_to_file(monkeypatch, sicd_structure, tmp_path):
    reader = _FakeSICDReader(sicd_structure)
    monkeypatch.setattr(
        dump_metadata, '_open_reader', lambda file_name: ('SICD', reader))

    out_file = tmp_path / 'out.json'
    ret = dump_metadata.dump_metadata(
        'example.sicd', dest=str(out_file), summary=True)
    assert ret is None
    with open(str(out_file), 'r') as fi:
        parsed = json.load(fi)
    assert parsed['meta'][0]['mode_type'] == 'SPOTLIGHT'
