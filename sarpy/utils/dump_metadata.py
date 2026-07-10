"""
A utility for dumping SAR metadata (SICD, SIDD, or CPHD) to JSON.

To print the metadata of a file to the console as JSON

>>> python -m sarpy.utils.dump_metadata <path to file>

To write the metadata to a JSON file

>>> python -m sarpy.utils.dump_metadata <path to file> -o <path to output.json>

To print only a short, human oriented summary of the key collection fields

>>> python -m sarpy.utils.dump_metadata <path to file> --summary

For a basic help on the command-line, check

>>> python -m sarpy.utils.dump_metadata --help

"""

__classification__ = "UNCLASSIFIED"
__author__ = "SarPy Contributors"

import argparse
import json
import sys
from collections import OrderedDict
from typing import Optional, Tuple

import numpy

from sarpy.io.complex.converter import open_complex
from sarpy.io.product.converter import open_product
from sarpy.io.phase_history.converter import open_phase_history


def _json_default(value):
    """
    Fallback serializer for the small number of numpy types that can appear in a
    metadata dictionary.
    """

    if isinstance(value, numpy.integer):
        return int(value)
    if isinstance(value, numpy.floating):
        return float(value)
    if isinstance(value, numpy.ndarray):
        return value.tolist()
    raise TypeError('Object of type {} is not JSON serializable'.format(type(value)))


def _normalize_structures(meta) -> list:
    """
    Normalize a reader metadata attribute, which may be a single structure or a
    collection of structures, into a list.
    """

    if meta is None:
        return []
    if isinstance(meta, (list, tuple)):
        return [entry for entry in meta if entry is not None]
    return [meta]


def _open_reader(file_name: str) -> Tuple[str, object]:
    """
    Open the given file using the appropriate reader.

    Parameters
    ----------
    file_name : str

    Returns
    -------
    (str, object)
        The file type ('SICD', 'SIDD', or 'CPHD') and the opened reader.

    Raises
    ------
    IOError
        If the file cannot be opened by any of the supported readers.
    """

    for file_type, opener in (
            ('SICD', open_complex),
            ('SIDD', open_product),
            ('CPHD', open_phase_history)):
        try:
            return file_type, opener(file_name)
        except Exception:
            continue
    raise IOError(
        'Unable to open {} as a SICD, SIDD, or CPHD file.'.format(file_name))


def _structures_for_reader(file_type: str, reader) -> list:
    """
    Extract the metadata structures from a reader based on its file type.
    """

    if file_type == 'SICD':
        return _normalize_structures(reader.sicd_meta)
    if file_type == 'SIDD':
        return _normalize_structures(reader.sidd_meta)
    return _normalize_structures(reader.cphd_meta)


def _sicd_summary(structure) -> OrderedDict:
    """
    Extract a small, human oriented summary of the key collection fields from a
    SICD metadata structure.
    """

    out = OrderedDict()

    collection_info = structure.CollectionInfo
    if collection_info is not None:
        out['collector_name'] = collection_info.CollectorName
        out['core_name'] = collection_info.CoreName
        out['collect_type'] = collection_info.CollectType
        out['classification'] = collection_info.Classification
        if collection_info.RadarMode is not None:
            out['mode_type'] = collection_info.RadarMode.ModeType

    timeline = structure.Timeline
    if timeline is not None:
        out['collect_start'] = None if timeline.CollectStart is None \
            else str(timeline.CollectStart)
        out['collect_duration'] = timeline.CollectDuration

    image_data = structure.ImageData
    if image_data is not None:
        out['pixel_type'] = image_data.PixelType
        out['num_rows'] = image_data.NumRows
        out['num_cols'] = image_data.NumCols

    geo_data = structure.GeoData
    if geo_data is not None and geo_data.SCP is not None \
            and geo_data.SCP.LLH is not None:
        llh = geo_data.SCP.LLH
        out['scp_lat'] = llh.Lat
        out['scp_lon'] = llh.Lon
        out['scp_hae'] = llh.HAE

    image_formation = structure.ImageFormation
    if image_formation is not None:
        out['tx_rcv_polarization'] = image_formation.TxRcvPolarizationProc

    return out


def get_metadata(file_name: str, summary: bool = False) -> OrderedDict:
    """
    Open a SICD, SIDD, or CPHD file and return its metadata as a dictionary
    suitable for JSON serialization.

    Parameters
    ----------
    file_name : str
        The path to a SICD, SIDD, or CPHD file.
    summary : bool
        If ``True`` and the file is a SICD, return only a short summary of the
        key collection fields rather than the full metadata.

    Returns
    -------
    OrderedDict
        A dictionary with keys ``file_name``, ``file_type``, and ``meta``, where
        ``meta`` is a list with one entry per metadata structure in the file.
    """

    file_type, reader = _open_reader(file_name)
    try:
        structures = _structures_for_reader(file_type, reader)
        meta = []
        for structure in structures:
            if summary and file_type == 'SICD':
                meta.append(_sicd_summary(structure))
            else:
                meta.append(structure.to_dict())
    finally:
        reader.close()

    return OrderedDict([
        ('file_name', file_name),
        ('file_type', file_type),
        ('meta', meta)])


def dump_metadata(file_name: str, dest: str = 'stdout', summary: bool = False,
                  indent: Optional[int] = 4) -> Optional[str]:
    """
    Dump the metadata of a SICD, SIDD, or CPHD file to a configurable destination
    as JSON.

    Parameters
    ----------
    file_name : str
        The path to a SICD, SIDD, or CPHD file.
    dest : str
        'stdout', 'string', or the path to an output file.
    summary : bool
        If ``True`` and the file is a SICD, dump only a short summary of the key
        collection fields.
    indent : None|int
        The indentation to use for the JSON output.

    Returns
    -------
    None|str
        There is only a return value if ``dest == 'string'``.
    """

    metadata = get_metadata(file_name, summary=summary)
    json_str = json.dumps(metadata, indent=indent, default=_json_default)

    if dest == 'string':
        return json_str
    if dest == 'stdout':
        sys.stdout.write(json_str + '\n')
        return None

    with open(dest, 'w') as the_file:
        the_file.write(json_str)
    return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Utility to dump SICD, SIDD, or CPHD metadata to JSON.',
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        'input_file',
        help='The path to a SICD, SIDD, or CPHD file.')
    parser.add_argument(
        '-o', '--output', default='stdout',
        help="'stdout' (the default) prints the JSON to standard out.\n"
             "Otherwise, this is the path to an output file, which will be "
             "overwritten if it exists.")
    parser.add_argument(
        '--summary', action='store_true',
        help='For a SICD, dump only a short summary of the key collection\n'
             'fields rather than the full metadata.')
    args = parser.parse_args()

    dump_metadata(args.input_file, dest=args.output, summary=args.summary)
