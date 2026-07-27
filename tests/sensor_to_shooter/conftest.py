import pathlib

import numpy
import pytest

from sarpy.io.complex.sicd import SICDWriter
from sarpy.io.complex.sicd_elements.SICD import SICDType

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="session")
def sicd_meta():
    return SICDType.from_xml_file(str(DATA_DIR / "example.sicd.xml"))


@pytest.fixture()
def synthetic_sicd(tmp_path, sicd_meta):
    """Write a small synthetic SICD NITF with two bright point targets."""
    meta = sicd_meta.copy()
    size = 64
    meta.ImageData.NumRows = size
    meta.ImageData.NumCols = size
    meta.ImageData.FullImage.NumRows = size
    meta.ImageData.FullImage.NumCols = size
    meta.ImageData.SCPPixel.Row = size // 2
    meta.ImageData.SCPPixel.Col = size // 2

    rng = numpy.random.default_rng(0)
    img = (
        rng.standard_normal((size, size)) + 1j * rng.standard_normal((size, size))
    ).astype(numpy.complex64)
    # Two strong point scatterers well above the noise floor.
    img[20, 40] = 80 + 80j
    img[45, 15] = 90 + 0j

    out_file = str(tmp_path / "synthetic.sicd.nitf")
    writer = SICDWriter(out_file, sicd_meta=meta)
    writer.write_chip(img, start_indices=(0, 0))
    writer.close()
    return out_file
