import json
import os
import pytest

from tests import parse_file_entry

from sarpy.io.complex.converter import open_complex
from sarpy.visualization.image_export import create_image_export
import sarpy.visualization.remap as remap

try:
    import PIL
except ImportError:
    PIL = None

complex_file_types = {}
this_loc = os.path.abspath(__file__)
file_reference = os.path.join(
    os.path.split(this_loc)[0], '..', 'processing', 'sidd', 'complex_file_types.json')
if os.path.isfile(file_reference):
    with open(file_reference, 'r') as local_file:
        test_files_list = json.load(local_file)
        for test_files_type in test_files_list:
            valid_entries = []
            for entry in test_files_list[test_files_type]:
                the_file = parse_file_entry(entry)
                if the_file is not None:
                    valid_entries.append(the_file)
            complex_file_types[test_files_type] = valid_entries

sicd_files = complex_file_types.get('SICD', [])


def get_test_reader():
    input_file = sicd_files[0]
    reader = open_complex(input_file)
    return reader


@pytest.mark.skipif(len(sicd_files) == 0, reason='No sicd files found')
@pytest.mark.skipif(PIL is None, reason='Pillow is not available')
def test_create_image_export_jpg(tmp_path):
    reader = get_test_reader()
    output_file = str(tmp_path / 'export.jpg')
    result = create_image_export(reader, output_file, pixel_limit=1024, output_format='JPEG')
    assert result == output_file
    assert os.path.isfile(output_file)
    assert os.path.getsize(output_file) > 0


@pytest.mark.skipif(len(sicd_files) == 0, reason='No sicd files found')
@pytest.mark.skipif(PIL is None, reason='Pillow is not available')
def test_create_image_export_pdf(tmp_path):
    reader = get_test_reader()
    output_file = str(tmp_path / 'export.pdf')
    result = create_image_export(reader, output_file, pixel_limit=1024, output_format='PDF')
    assert result == output_file
    assert os.path.isfile(output_file)
    assert os.path.getsize(output_file) > 0


@pytest.mark.skipif(len(sicd_files) == 0, reason='No sicd files found')
@pytest.mark.skipif(PIL is None, reason='Pillow is not available')
def test_create_image_export_from_file_path(tmp_path):
    output_file = str(tmp_path / 'export.jpg')
    result = create_image_export(
        sicd_files[0], output_file, pixel_limit=1024, output_format='jpg',
        remap_function=remap.get_registered_remap('density'))
    assert result == output_file
    assert os.path.isfile(output_file)
    assert os.path.getsize(output_file) > 0


@pytest.mark.skipif(len(sicd_files) == 0, reason='No sicd files found')
@pytest.mark.skipif(PIL is None, reason='Pillow is not available')
def test_create_image_export_bad_format(tmp_path):
    reader = get_test_reader()
    output_file = str(tmp_path / 'export.tiff')
    with pytest.raises(ValueError, match='output_format must be one of'):
        create_image_export(reader, output_file, pixel_limit=1024, output_format='TIFF')
