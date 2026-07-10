"""
Create high resolution JPEG or PDF image exports based on SICD type readers.

For a basic help on the command-line, check

>>> python -m sarpy.utils.export_image --help

"""

__classification__ = "UNCLASSIFIED"
__author__ = "Cognition AI"

import argparse
import logging

from sarpy.io.complex.converter import open_complex
from sarpy.visualization.image_export import create_image_export
import sarpy.visualization.remap as remap


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Create a JPEG or PDF image export from a SICD type file.",
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        'input_file', metavar='input_file',
        help='Path input data file, or directory for radarsat, RCM, or sentinel.\n'
             '* For radarsat or RCM, this can be the product.xml file, or parent directory\n'
             '  of product.xml or metadata/product.xml.\n'
             '* For sentinel, this can be the manifest.safe file, or parent directory of\n'
             '  manifest.safe.\n')
    parser.add_argument(
        'output_file', metavar='output_file',
        help='Path to the output image file to be created.')
    parser.add_argument(
        '-f', '--format', default='jpg', choices=['jpg', 'pdf'],
        help="The output image format. (default: %(default)s)")
    parser.add_argument(
        '-r', '--remap', default=remap.get_remap_names()[0], choices=remap.get_remap_names(),
        help="The pixel value remap function. (default: %(default)s)")
    parser.add_argument(
        '-s', '--size', default=-1, type=int,
        help='Maximum # of image rows/columns, put -1 for full resolution. (default: %(default)s)')
    parser.add_argument(
        '-d', '--dpi', default=300, type=int,
        help='The output resolution in dots per inch. (default: %(default)s)')
    parser.add_argument(
        '-i', '--index', default=0, type=int,
        help='The image index to use, for multi-image files. (default: %(default)s)')
    parser.add_argument(
        '-v', '--verbose', action='store_true', help='Verbose (level="INFO") logging?')

    args = parser.parse_args(args)

    level = 'INFO' if args.verbose else 'WARNING'
    logging.basicConfig(level=level)
    logger = logging.getLogger('sarpy')
    logger.setLevel(level)

    reader = open_complex(args.input_file)
    pixel_limit = None if args.size == -1 else args.size
    output_format = 'JPEG' if args.format == 'jpg' else 'PDF'
    create_image_export(
        reader, args.output_file, index=args.index,
        remap_function=remap.get_registered_remap(args.remap),
        pixel_limit=pixel_limit, output_format=output_format, dpi=args.dpi)


if __name__ == '__main__':
    main()
