"""
This module provides tools for exporting high resolution JPEG or PDF image
products for a SICD type element.

.. Note::
    Image export requires the optional Pillow dependency for image manipulation.

Examples
--------
Create a high resolution JPEG export for the contents of a sicd type reader.

.. code-block:: python

    import os
    from sarpy.io.complex.converter import open_complex
    from sarpy.visualization.image_export import create_image_export

    test_root = '<root directory>'
    reader = open_complex(os.path.join(test_root, '<file name>'))
    create_image_export(reader, os.path.join(test_root, 'export.jpg'),
                        output_format='JPEG')
"""

__classification__ = "UNCLASSIFIED"
__author__ = "Cognition AI"

import logging
import os

import numpy

from sarpy.processing.rational_polynomial import SarpyRatPolyError
from sarpy.processing.ortho_rectify.base import FullResolutionFetcher, OrthorectificationIterator
from sarpy.processing.ortho_rectify.ortho_methods import NearestNeighborMethod
from sarpy.processing.ortho_rectify.projection_helper import PGProjection, PGRatPolyProjection
from sarpy.io.complex.base import SICDTypeReader
from sarpy.io.complex.converter import open_complex
from sarpy.visualization.remap import RemapFunction, NRL

try:
    # noinspection PyPackageRequirements
    import PIL
    import PIL.Image
except ImportError:
    PIL = None

logger = logging.getLogger(__name__)

_FORMAT_EXTENSIONS = {
    'JPEG': ('.jpg', '.jpeg'),
    'PDF': ('.pdf', )}


def get_orthorectified_array(reader, index=0, pixel_limit=None, remap_function=None, block_size=10):
    """
    Fetch the full ortho-rectified, remapped image array for the given reader
    and image index.

    Parameters
    ----------
    reader : SICDTypeReader
    index : int
        The image index to use.
    pixel_limit : None|int
        The maximum size for rows/columns of the ortho-rectified image. If
        `None`, the full resolution image will be produced.
    remap_function : None|RemapFunction
        The remap function to apply, `NRL` will be used if `None`.
    block_size : None|int|float
        The block size for the ortho-rectification iterator.

    Returns
    -------
    numpy.ndarray
        The 8-bit remapped, ortho-rectified image array.
    """

    if not isinstance(reader, SICDTypeReader):
        raise TypeError('reader must be a instance of SICDTypeReader. Got type {}'.format(type(reader)))

    if pixel_limit is not None:
        pixel_limit = int(pixel_limit)
        if pixel_limit < 512:
            pixel_limit = 512

    index = int(index)
    sicd = reader.get_sicds_as_tuple()[index]
    try:
        proj_helper = PGRatPolyProjection(sicd)
    except SarpyRatPolyError:
        proj_helper = PGProjection(sicd)
    ortho_helper = NearestNeighborMethod(reader, index=index, proj_helper=proj_helper)
    if pixel_limit is not None:
        ortho_size = ortho_helper.get_full_ortho_bounds()
        row_count = ortho_size[1] - ortho_size[0]
        col_count = ortho_size[3] - ortho_size[2]
        if row_count > pixel_limit:
            proj_helper.row_spacing *= row_count / float(pixel_limit)
        if col_count > pixel_limit:
            proj_helper.col_spacing *= col_count / float(pixel_limit)
        if isinstance(proj_helper, PGRatPolyProjection):
            proj_helper.perform_rational_poly_fitting()

    if remap_function is None:
        remap_function = NRL()
    if not isinstance(remap_function, RemapFunction):
        raise TypeError(
            'remap_function must be an instance of RemapFunction, got type {}'.format(type(remap_function)))
    if remap_function.bit_depth != 8:
        raise ValueError('The bit depth for the remap function must be 8.')

    calculator = FullResolutionFetcher(
        ortho_helper.reader, index=ortho_helper.index, dimension=1, block_size=block_size)
    ortho_iterator = OrthorectificationIterator(
        ortho_helper, calculator=calculator, remap_function=remap_function,
        recalc_remap_globals=True)

    image_data = numpy.zeros(ortho_iterator.ortho_data_size, dtype=ortho_iterator.remap_function.output_dtype)
    for data, start_indices in ortho_iterator:
        image_data[start_indices[0]:start_indices[0] + data.shape[0],
                   start_indices[1]:start_indices[1] + data.shape[1]] = data
    return image_data


def create_image_export(
        reader, output_file, index=0, remap_function=None, pixel_limit=None,
        output_format='JPEG', dpi=300, quality=95, block_size=10):
    """
    Create a JPEG or PDF image export of the ortho-rectified, remapped contents
    of a SICD type reader.

    Parameters
    ----------
    reader : str|SICDTypeReader
        A file name/path to be opened with
        :func:`sarpy.io.complex.converter.open_complex`, or an already opened
        SICD type reader instance.
    output_file : str
        The path of the output file to be created.
    index : int
        The image index to use.
    remap_function : None|RemapFunction
        The remap function to apply, `NRL` will be used if `None`.
    pixel_limit : None|int
        The maximum size for rows/columns of the exported image. If `None`,
        the full resolution image will be produced.
    output_format : str
        One of `'JPEG'` or `'PDF'`.
    dpi : int
        The resolution (dots per inch). Determines the physical page size for
        PDF output, and is recorded as resolution metadata for JPEG output.
    quality : int
        The JPEG quality (1-95), only used for JPEG output.
    block_size : None|int|float
        The block size for the ortho-rectification iterator.

    Returns
    -------
    str
        The path of the created output file.
    """

    if PIL is None:
        raise RuntimeError(
            'Image export functionality requires the optional Pillow dependency, '
            'which appears to be missing. Install it via `pip install pillow`.')

    output_format = output_format.upper()
    if output_format == 'JPG':
        output_format = 'JPEG'
    if output_format not in _FORMAT_EXTENSIONS:
        raise ValueError(
            'output_format must be one of {}, got `{}`'.format(
                sorted(_FORMAT_EXTENSIONS.keys()), output_format))

    close_reader = False
    if isinstance(reader, str):
        reader = open_complex(reader)
        close_reader = True

    extension = os.path.splitext(output_file)[1].lower()
    if extension not in _FORMAT_EXTENSIONS[output_format]:
        logger.warning(
            'The output file extension `%s` does not match the output format `%s`.',
            extension, output_format)

    try:
        image_data = get_orthorectified_array(
            reader, index=index, pixel_limit=pixel_limit,
            remap_function=remap_function, block_size=block_size)
    finally:
        if close_reader:
            reader.close()

    img = PIL.Image.fromarray(image_data)
    if output_format == 'JPEG':
        img.save(output_file, 'JPEG', quality=quality, dpi=(dpi, dpi))
    else:
        img.save(output_file, 'PDF', resolution=float(dpi))
    logger.info('Created %s export at %s', output_format, output_file)
    return output_file
