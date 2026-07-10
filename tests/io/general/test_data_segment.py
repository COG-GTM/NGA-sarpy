import os
import tempfile
import unittest

import numpy

from sarpy.io.general.format_function import ComplexFormatFunction
from sarpy.io.general.data_segment import DataSegment, NumpyArraySegment, \
    SubsetSegment, BandAggregateSegment, BlockAggregateSegment, \
    ReorientationSegment, NumpyMemmapSegment, HDF5DatasetSegment, \
    FileReadDataSegment
from sarpy.io.general.utils import h5py
from io import BytesIO


class TestNumpyArraySegment(unittest.TestCase):
    def test_basic_read(self):
        data = numpy.reshape(numpy.arange(60, dtype='int16'), (5, 6, 2))
        complex_data = numpy.empty((5, 6), dtype='complex64')
        complex_data.real = data[:, :, 0]
        complex_data.imag = data[:, :, 1]

        data_segment = NumpyArraySegment(
            data, formatted_dtype='complex64', formatted_shape=(5, 6),
            format_function=ComplexFormatFunction('int16', 'IQ', band_dimension=2),
            mode='r')

        with self.subTest(msg='read_raw full'):
            test_data = data_segment.read_raw(None)
            self.assertTrue(numpy.all(data == test_data))

        with self.subTest(msg='read_raw subscript'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment.read_raw(subscript)
            self.assertTrue(numpy.all(data[subscript] == test_data))

        with self.subTest(msg='read_raw index with squeeze'):
            test_data = data_segment.read_raw((0, 1, 1), squeeze=True)
            self.assertTrue(test_data.ndim == 0, msg='{}'.format(test_data))
            self.assertTrue(data[0, 1, 1] == test_data)

        with self.subTest(msg='read_raw index without squeeze'):
            test_data = data_segment.read_raw((0, 1, 1), squeeze=False)
            self.assertTrue(test_data.ndim == 3)
            self.assertTrue(data[0, 1, 1] == test_data)

        with self.subTest(msg='read full'):
            test_data = data_segment.read(None)
            self.assertTrue(numpy.all(complex_data == test_data))

        with self.subTest(msg='read subscript'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment.read(subscript)
            self.assertTrue(numpy.all(complex_data[subscript] == test_data))

        with self.subTest(msg='read subscript with ellipsis'):
            subscript = (..., slice(1, 3, 1))
            test_data = data_segment.read(subscript)
            self.assertTrue(numpy.all(complex_data[subscript] == test_data))

        with self.subTest(msg='read index with squeeze'):
            test_data = data_segment.read((0, 1), squeeze=True)
            self.assertTrue(test_data.ndim == 0)
            self.assertTrue(complex_data[0, 1] == test_data)

        with self.subTest(msg='read index without squeeze'):
            test_data = data_segment.read((0, 1), squeeze=False)
            self.assertTrue(test_data.ndim == 2)
            self.assertTrue(complex_data[0, 1] == test_data)

        with self.subTest(msg='read using __getitem__ subscript'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment[0:2, 1:3]
            self.assertTrue(numpy.all(complex_data[subscript] == test_data))

        with self.subTest(msg='read using __getitem__ and specifying raw'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment[0:2, 1:3, 'raw']
            self.assertTrue(numpy.all(data[subscript] == test_data))

        with self.subTest(msg='corners :3,:3'):
            test_data = data_segment[:3, :3]
            self.assertTrue(test_data.shape == (3, 3))

        with self.subTest(msg='corners -3:,:3'):
            test_data = data_segment[-3:, :3]
            self.assertTrue(test_data.shape == (3, 3))

        with self.subTest(msg='corners :3,-3:'):
            test_data = data_segment[:3, -3:]
            self.assertTrue(test_data.shape == (3, 3))

        with self.subTest(msg='corners -3:,-3:'):
            test_data = data_segment[-3:, -3:]
            self.assertTrue(test_data.shape == (3, 3))

        with self.assertRaises(ValueError, msg='write_raw attempt'):
            data_segment.write_raw(data, start_indices=0)

        with self.assertRaises(ValueError, msg='write attempt'):
            data_segment.write(complex_data, start_indices=0)

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='read access when closed'):
            _ = data_segment.read(None)

        with self.assertRaises(ValueError, msg='read_raw access when closed'):
            _ = data_segment.read_raw(None)

    def test_read_with_transpose_and_reverse(self):
        data = numpy.reshape(numpy.arange(60, dtype='int16'), (5, 6, 2))

        for axis in [None, (0, ), (1, ), (0, 1)]:
            complex_data = numpy.empty((5, 6), dtype='complex64')
            complex_data.real = data[:, :, 0]
            complex_data.imag = data[:, :, 1]
            if axis is None:
                complex_data = numpy.transpose(complex_data)
            else:
                complex_data = numpy.transpose(numpy.flip(complex_data, axis=axis))

            data_segment = NumpyArraySegment(
                data, formatted_dtype='complex64', formatted_shape=(6, 5),
                reverse_axes=axis, transpose_axes=(1, 0, 2),
                format_function=ComplexFormatFunction('int16', 'IQ', band_dimension=2),
                mode='r')

            with self.subTest(msg='read full, axis {}'.format(axis)):
                test_data = data_segment.read(None)
                self.assertTrue(numpy.all(complex_data == test_data))

            with self.subTest(msg='read subscript, axis {}'.format(axis)):
                subscript = (slice(1, 3, 1), slice(0, 2, 1))
                test_data = data_segment.read(subscript)
                self.assertTrue(numpy.all(test_data == complex_data[subscript]))

            with self.subTest(msg='corners :3,:3, axis {}'.format(axis)):
                test_data = data_segment[:3, :3]
                self.assertTrue(test_data.shape == (3, 3))

            with self.subTest(msg='corners -3:,:3, axis {}'.format(axis)):
                test_data = data_segment[-3:, :3]
                self.assertTrue(test_data.shape == (3, 3))

            with self.subTest(msg='corners :3,-3:, axis {}'.format(axis)):
                test_data = data_segment[:3, -3:]
                self.assertTrue(test_data.shape == (3, 3))

            with self.subTest(msg='corners -3:,-3:, axis {}'.format(axis)):
                test_data = data_segment[-3:, -3:]
                self.assertTrue(test_data.shape == (3, 3))

    def test_basic_write(self):
        data = numpy.reshape(numpy.arange(24, dtype='int16'), (3, 4, 2))
        complex_data = numpy.empty((3, 4), dtype='complex64')
        complex_data.real = data[:, :, 0]
        complex_data.imag = data[:, :, 1]

        with self.subTest(msg='write_raw'):
            empty = numpy.empty((3, 4, 2), dtype='int16')
            data_segment = NumpyArraySegment(
                empty, formatted_dtype='complex64', formatted_shape=(3, 4),
                format_function=ComplexFormatFunction('int16', 'IQ', band_dimension=2),
                mode='w')

            data_segment.write_raw(data, start_indices=0)
            self.assertTrue(numpy.all(empty == data))

        with self.subTest(msg='write'):
            empty = numpy.empty((3, 4, 2), dtype='int16')
            data_segment = NumpyArraySegment(
                empty, formatted_dtype='complex64', formatted_shape=(3, 4),
                format_function=ComplexFormatFunction('int16', 'IQ', band_dimension=2),
                mode='w')

            data_segment.write(complex_data, start_indices=0)
            self.assertTrue(numpy.all(empty == data))

        with self.assertRaises(ValueError, msg='read_raw attempt'):
            _ = data_segment.read_raw(0)

        with self.assertRaises(ValueError, msg='read attempt'):
            _ = data_segment.read(0)

        with self.subTest(msg='close'):
            empty = numpy.empty((3, 4, 2), dtype='int16')
            data_segment = NumpyArraySegment(
                empty, formatted_dtype='complex64', formatted_shape=(3, 4),
                format_function=ComplexFormatFunction('int16', 'IQ', band_dimension=2),
                mode='w')
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='write access when closed'):
            data_segment.write(complex_data)

        with self.assertRaises(ValueError, msg='write_raw access when closed'):
            data_segment.write(complex_data)


class TestSubsetSegment(unittest.TestCase):
    def test_read(self):
        data = numpy.reshape(numpy.arange(24, dtype='int16'), (6, 4))

        subset_def = (slice(2, 5, 1), slice(2, 4, 1))
        parent_segment = NumpyArraySegment(data, mode='r')
        data_segment = SubsetSegment(parent_segment, subset_def, 'raw')

        with self.subTest(msg='full read'):
            test_data = data_segment[:]
            self.assertTrue(numpy.all(data[subset_def] == test_data))

        with self.subTest(msg='partial read'):
            test_data = data_segment[1:3]
            self.assertTrue(numpy.all(data[(slice(3, 5, 1), slice(2, 4, 1))] == test_data))

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='read_raw access when closed'):
            _ = data_segment.read_raw(None)

        with self.assertRaises(ValueError, msg='read access when closed'):
            _ = data_segment.read(None)

    def test_write(self):
        data = numpy.zeros((6, 4), dtype='int16')

        subset_def = (slice(2, 5, 1), slice(2, 4, 1))
        parent_segment = NumpyArraySegment(data, mode='w')
        data_segment = SubsetSegment(parent_segment, subset_def, 'raw')

        test_data = numpy.reshape(numpy.arange(6, dtype='int16'), (3, 2))

        with self.subTest(msg='subset write'):
            data_segment.write(test_data, start_indices=0)
            self.assertTrue(numpy.all(data[subset_def] == test_data))

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='write access when closed'):
            data_segment.write(test_data)

        with self.assertRaises(ValueError, msg='write_raw access when closed'):
            data_segment.write(test_data)

    def test_close_parent_ownership(self):
        data = numpy.reshape(numpy.arange(24, dtype='int16'), (6, 4))
        subset_def = (slice(2, 5, 1), slice(2, 4, 1))

        with self.subTest(msg='close_parent False leaves parent open'):
            parent_segment = NumpyArraySegment(data, mode='r')
            data_segment = SubsetSegment(
                parent_segment, subset_def, 'raw', close_parent=False)
            data_segment.close()
            self.assertTrue(data_segment.closed)
            self.assertFalse(parent_segment.closed)
            parent_segment.close()

        with self.subTest(msg='close_parent True closes parent'):
            parent_segment = NumpyArraySegment(data, mode='r')
            data_segment = SubsetSegment(
                parent_segment, subset_def, 'raw', close_parent=True)
            data_segment.close()
            self.assertTrue(data_segment.closed)
            self.assertTrue(parent_segment.closed)


class TestBandAggregateSegment(unittest.TestCase):
    def test_read(self):
        data0 = numpy.reshape(numpy.arange(12, dtype='uint8'), (3, 4))
        data1 = numpy.reshape(numpy.arange(12, 24, dtype='uint8'), (3, 4))
        ds0 = NumpyArraySegment(data0, mode='r')
        ds1 = NumpyArraySegment(data1, mode='r')
        data_segment = BandAggregateSegment((ds0, ds1), 2)

        with self.subTest(msg='direct band comparison'):
            test_data = data_segment[:]
            self.assertTrue(numpy.all(test_data[..., 0] == data0))
            self.assertTrue(numpy.all(test_data[..., 1] == data1))

        with self.subTest(msg='reading band comparison'):
            self.assertTrue(numpy.all(data_segment[..., 0] == data0))
            self.assertTrue(numpy.all(data_segment[..., 1] == data1))

        with self.subTest(msg='section reading'):
            subset = (slice(2, 3, 1), slice(1, 3, 1))
            test_data = data_segment.read(subset)
            self.assertTrue(numpy.all(test_data[..., 0] == data0[subset]))
            self.assertTrue(numpy.all(test_data[..., 1] == data1[subset]))

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='read_raw access when closed'):
            _ = data_segment.read_raw(None)

        with self.assertRaises(ValueError, msg='read access when closed'):
            _ = data_segment.read(None)

    def test_write(self):
        data0 = numpy.empty((3, 4), dtype='uint16')
        data1 = numpy.empty((3, 4), dtype='uint16')
        ds0 = NumpyArraySegment(data0, mode='w')
        ds1 = NumpyArraySegment(data1, mode='w')
        data_segment = BandAggregateSegment((ds0, ds1), 2)

        with self.subTest(msg='writing check'):
            test_data = numpy.reshape(numpy.arange(24, dtype='uint16'), (3, 4, 2))
            data_segment.write(test_data)
            self.assertTrue(numpy.all(test_data[..., 0] == data0))
            self.assertTrue(numpy.all(test_data[..., 1] == data1))

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='write access when closed'):
            data_segment.write(test_data)

        with self.assertRaises(ValueError, msg='write_raw access when closed'):
            data_segment.write(test_data)

    def test_close_children_ownership(self):
        data0 = numpy.reshape(numpy.arange(12, dtype='uint8'), (3, 4))
        data1 = numpy.reshape(numpy.arange(12, 24, dtype='uint8'), (3, 4))

        with self.subTest(msg='close_children False leaves children open'):
            ds0 = NumpyArraySegment(data0, mode='r')
            ds1 = NumpyArraySegment(data1, mode='r')
            data_segment = BandAggregateSegment((ds0, ds1), 2, close_children=False)
            data_segment.close()
            self.assertTrue(data_segment.closed)
            self.assertFalse(ds0.closed)
            self.assertFalse(ds1.closed)
            ds0.close()
            ds1.close()

        with self.subTest(msg='close_children True closes children'):
            ds0 = NumpyArraySegment(data0, mode='r')
            ds1 = NumpyArraySegment(data1, mode='r')
            data_segment = BandAggregateSegment((ds0, ds1), 2, close_children=True)
            data_segment.close()
            self.assertTrue(data_segment.closed)
            self.assertTrue(ds0.closed)
            self.assertTrue(ds1.closed)


class TestBlockAggregateSegment(unittest.TestCase):
    def test_read(self):
        data0 = numpy.reshape(numpy.arange(6, dtype='int16'), (3, 2))
        data1 = numpy.reshape(numpy.arange(6, 12, dtype='int16'), (3, 2))
        ds0 = NumpyArraySegment(data0, mode='r')
        ds1 = NumpyArraySegment(data1, mode='r')
        data_segment = BlockAggregateSegment(
            (ds0, ds1), (
                (slice(0, 3, 1), slice(0, 2, 1)),
                (slice(0, 3, 1), slice(2, 4, 1))),
            'raw', 0, (3, 4), 'int16', (3, 4))

        with self.subTest(msg='read'):
            test_data = data_segment[:]
            self.assertTrue(numpy.all(data0 == test_data[:, :2]))
            self.assertTrue(numpy.all(data1 == test_data[:, 2:]))

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='read_raw access when closed'):
            _ = data_segment.read_raw(None)

        with self.assertRaises(ValueError, msg='read access when closed'):
            _ = data_segment.read(None)

    def test_write(self):
        data0 = numpy.empty((3, 2), dtype='int16')
        data1 = numpy.empty((3, 2), dtype='int16')
        ds0 = NumpyArraySegment(data0, mode='w')
        ds1 = NumpyArraySegment(data1, mode='w')
        data_segment = BlockAggregateSegment(
            (ds0, ds1), (
                (slice(0, 3, 1), slice(0, 2, 1)),
                (slice(0, 3, 1), slice(2, 4, 1))),
            'raw', 0, (3, 4), 'int16', (3, 4))

        test_data = numpy.reshape(numpy.arange(12, dtype='int16'), (3, 4))
        with self.subTest(msg='write'):
            data_segment.write(test_data, start_indices=0)
            self.assertTrue(numpy.all(test_data[:, :2] == data0))
            self.assertTrue(numpy.all(test_data[:, 2:] == data1))

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='write access when closed'):
            data_segment.write(test_data)

        with self.assertRaises(ValueError, msg='write_raw access when closed'):
            data_segment.write(test_data)

    def test_close_children_ownership(self):
        data0 = numpy.reshape(numpy.arange(6, dtype='int16'), (3, 2))
        data1 = numpy.reshape(numpy.arange(6, 12, dtype='int16'), (3, 2))
        arrangement = (
            (slice(0, 3, 1), slice(0, 2, 1)),
            (slice(0, 3, 1), slice(2, 4, 1)))

        with self.subTest(msg='close_children False leaves children open'):
            ds0 = NumpyArraySegment(data0, mode='r')
            ds1 = NumpyArraySegment(data1, mode='r')
            data_segment = BlockAggregateSegment(
                (ds0, ds1), arrangement, 'raw', 0, (3, 4), 'int16', (3, 4),
                close_children=False)
            data_segment.close()
            self.assertTrue(data_segment.closed)
            self.assertFalse(ds0.closed)
            self.assertFalse(ds1.closed)
            ds0.close()
            ds1.close()

        with self.subTest(msg='close_children True closes children'):
            ds0 = NumpyArraySegment(data0, mode='r')
            ds1 = NumpyArraySegment(data1, mode='r')
            data_segment = BlockAggregateSegment(
                (ds0, ds1), arrangement, 'raw', 0, (3, 4), 'int16', (3, 4),
                close_children=True)
            data_segment.close()
            self.assertTrue(data_segment.closed)
            self.assertTrue(ds0.closed)
            self.assertTrue(ds1.closed)


class TestFileReadSegment(unittest.TestCase):
    def test_read(self):
        data = numpy.reshape(numpy.arange(24, dtype='int16'), (3, 4, 2))
        complex_data = numpy.empty((3, 4), dtype='complex64')
        complex_data.real = data[:, :, 0]
        complex_data.imag = data[:, :, 1]

        file_object = BytesIO(data.tobytes())
        data_segment = FileReadDataSegment(
            file_object, 0, 'int16', (3, 4, 2), 'complex64', (3, 4),
            format_function=ComplexFormatFunction('int16', 'IQ', band_dimension=2))

        with self.subTest(msg='read_raw full'):
            test_data = data_segment.read_raw(None)
            self.assertTrue(numpy.all(data == test_data))

        with self.subTest(msg='read_raw subscript'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment.read_raw(subscript)
            self.assertTrue(numpy.all(data[subscript] == test_data))

        with self.subTest(msg='read_raw index with squeeze'):
            test_data = data_segment.read_raw((0, 1, 1), squeeze=True)
            self.assertTrue(test_data.ndim == 0, msg='{}'.format(test_data))
            self.assertTrue(data[0, 1, 1] == test_data)

        with self.subTest(msg='read_raw index without squeeze'):
            test_data = data_segment.read_raw((0, 1, 1), squeeze=False)
            self.assertTrue(test_data.ndim == 3)
            self.assertTrue(data[0, 1, 1] == test_data)

        with self.subTest(msg='read full'):
            test_data = data_segment.read(None)
            self.assertTrue(numpy.all(complex_data == test_data))

        with self.subTest(msg='read subscript'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment.read(subscript)
            self.assertTrue(numpy.all(complex_data[subscript] == test_data))

        with self.subTest(msg='read subscript with ellipsis'):
            subscript = (..., slice(1, 3, 1))
            test_data = data_segment.read(subscript)
            self.assertTrue(numpy.all(complex_data[subscript] == test_data))

        with self.subTest(msg='read index with squeeze'):
            test_data = data_segment.read((0, 1), squeeze=True)
            self.assertTrue(test_data.ndim == 0)
            self.assertTrue(complex_data[0, 1] == test_data)

        with self.subTest(msg='read index without squeeze'):
            test_data = data_segment.read((0, 1), squeeze=False)
            self.assertTrue(test_data.ndim == 2)
            self.assertTrue(complex_data[0, 1] == test_data)

        with self.subTest(msg='read using __getitem__ subscript'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment[0:2, 1:3]
            self.assertTrue(numpy.all(complex_data[subscript] == test_data))

        with self.subTest(msg='read using __getitem__ and specifying raw'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment[0:2, 1:3, 'raw']
            self.assertTrue(numpy.all(data[subscript] == test_data))

        with self.assertRaises(ValueError, msg='write_raw attempt'):
            data_segment.write_raw(data, start_indices=0)

        with self.assertRaises(ValueError, msg='write attempt'):
            data_segment.write(complex_data, start_indices=0)

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='read access when closed'):
            _ = data_segment.read(None)

        with self.assertRaises(ValueError, msg='read_raw access when closed'):
            _ = data_segment.read_raw(None)


class TestReorientationSegment(unittest.TestCase):
    def test_read(self):
        data = numpy.reshape(numpy.arange(20, dtype='int16'), (4, 5))

        for axis in [None, (0, ), (1, ), (0, 1)]:
            parent_segment = NumpyArraySegment(data, mode='r')
            data_segment = ReorientationSegment(
                parent_segment, reverse_axes=axis, transpose_axes=(1, 0))

            if axis is None:
                expected = numpy.transpose(data)
            else:
                expected = numpy.transpose(numpy.flip(data, axis=axis))

            with self.subTest(msg='read_raw full, axis {}'.format(axis)):
                test_data = data_segment.read_raw(None)
                self.assertTrue(numpy.all(data == test_data))

            with self.subTest(msg='read full, axis {}'.format(axis)):
                test_data = data_segment.read(None)
                self.assertTrue(numpy.all(expected == test_data))

            with self.subTest(msg='read subscript, axis {}'.format(axis)):
                subscript = (slice(1, 4, 1), slice(0, 2, 1))
                test_data = data_segment.read(subscript)
                self.assertTrue(numpy.all(expected[subscript] == test_data))

            with self.subTest(msg='formatted_shape, axis {}'.format(axis)):
                self.assertEqual(data_segment.formatted_shape, (5, 4))

            data_segment.close()

    def test_closed_access(self):
        data = numpy.reshape(numpy.arange(20, dtype='int16'), (4, 5))
        parent_segment = NumpyArraySegment(data, mode='r')
        data_segment = ReorientationSegment(parent_segment, transpose_axes=(1, 0))

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='read access when closed'):
            _ = data_segment.read(None)

        with self.assertRaises(ValueError, msg='read_raw access when closed'):
            _ = data_segment.read_raw(None)

    def test_close_parent_ownership(self):
        data = numpy.reshape(numpy.arange(20, dtype='int16'), (4, 5))

        with self.subTest(msg='close_parent False leaves parent open'):
            parent_segment = NumpyArraySegment(data, mode='r')
            data_segment = ReorientationSegment(
                parent_segment, transpose_axes=(1, 0), close_parent=False)
            data_segment.close()
            self.assertTrue(data_segment.closed)
            self.assertFalse(parent_segment.closed)
            parent_segment.close()

        with self.subTest(msg='close_parent True closes parent'):
            parent_segment = NumpyArraySegment(data, mode='r')
            data_segment = ReorientationSegment(
                parent_segment, transpose_axes=(1, 0), close_parent=True)
            data_segment.close()
            self.assertTrue(data_segment.closed)
            self.assertTrue(parent_segment.closed)


class TestNumpyMemmapSegment(unittest.TestCase):
    def setUp(self):
        self.data = numpy.reshape(numpy.arange(60, dtype='int16'), (5, 6, 2))
        fd, self.file_path = tempfile.mkstemp(suffix='.dat')
        os.close(fd)
        self.data.tofile(self.file_path)

    def tearDown(self):
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

    def test_construct_from_path_forces_close_file(self):
        data_segment = NumpyMemmapSegment(
            self.file_path, 0, 'int16', (5, 6, 2), mode='r')
        self.assertTrue(data_segment.close_file)
        data_segment.close()

    def test_construct_from_file_object_ownership(self):
        with self.subTest(msg='close_file defaults False for open file object'):
            file_object = open(self.file_path, 'rb')
            data_segment = NumpyMemmapSegment(
                file_object, 0, 'int16', (5, 6, 2), mode='r')
            self.assertFalse(data_segment.close_file)
            data_segment.close()
            self.assertFalse(file_object.closed)
            file_object.close()

        with self.subTest(msg='close_file True closes file object'):
            file_object = open(self.file_path, 'rb')
            data_segment = NumpyMemmapSegment(
                file_object, 0, 'int16', (5, 6, 2), mode='r', close_file=True)
            self.assertTrue(data_segment.close_file)
            data_segment.close()
            self.assertTrue(file_object.closed)

    def test_read(self):
        complex_data = numpy.empty((5, 6), dtype='complex64')
        complex_data.real = self.data[:, :, 0]
        complex_data.imag = self.data[:, :, 1]

        data_segment = NumpyMemmapSegment(
            self.file_path, 0, 'int16', (5, 6, 2),
            formatted_dtype='complex64', formatted_shape=(5, 6),
            format_function=ComplexFormatFunction('int16', 'IQ', band_dimension=2),
            mode='r')

        with self.subTest(msg='read_raw full'):
            test_data = data_segment.read_raw(None)
            self.assertTrue(numpy.all(self.data == test_data))

        with self.subTest(msg='read_raw subscript'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment.read_raw(subscript)
            self.assertTrue(numpy.all(self.data[subscript] == test_data))

        with self.subTest(msg='read_raw negative step'):
            subscript = (slice(4, 1, -1), slice(0, 6, 1), slice(0, 2, 1))
            test_data = data_segment.read_raw(subscript)
            self.assertTrue(numpy.all(self.data[subscript] == test_data))

        with self.subTest(msg='read full'):
            test_data = data_segment.read(None)
            self.assertTrue(numpy.all(complex_data == test_data))

        with self.subTest(msg='read subscript'):
            subscript = (slice(0, 2, 1), slice(1, 3, 1))
            test_data = data_segment.read(subscript)
            self.assertTrue(numpy.all(complex_data[subscript] == test_data))

        with self.subTest(msg='corners :3,:3'):
            test_data = data_segment[:3, :3]
            self.assertTrue(test_data.shape == (3, 3))

        with self.subTest(msg='corners -3:,:3'):
            test_data = data_segment[-3:, :3]
            self.assertTrue(test_data.shape == (3, 3))

        with self.subTest(msg='corners :3,-3:'):
            test_data = data_segment[:3, -3:]
            self.assertTrue(test_data.shape == (3, 3))

        with self.subTest(msg='corners -3:,-3:'):
            test_data = data_segment[-3:, -3:]
            self.assertTrue(test_data.shape == (3, 3))

        data_segment.close()

    def test_write(self):
        write_data = numpy.reshape(numpy.arange(60, 120, dtype='int16'), (5, 6, 2))

        data_segment = NumpyMemmapSegment(
            self.file_path, 0, 'int16', (5, 6, 2), mode='w')

        with self.subTest(msg='write_raw and flush'):
            data_segment.write_raw(write_data, start_indices=0)
            data_segment.flush()
            self.assertTrue(data_segment.check_fully_written())

        data_segment.close()

        with self.subTest(msg='persisted bytes'):
            reopened = numpy.fromfile(self.file_path, dtype='int16')
            self.assertTrue(numpy.all(numpy.reshape(reopened, (5, 6, 2)) == write_data))

    def test_close_idempotent(self):
        data_segment = NumpyMemmapSegment(
            self.file_path, 0, 'int16', (5, 6, 2), mode='r')

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.subTest(msg='second close is a no-op'):
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='read access when closed'):
            _ = data_segment.read(None)

        with self.assertRaises(ValueError, msg='read_raw access when closed'):
            _ = data_segment.read_raw(None)


@unittest.skipIf(h5py is None, 'h5py is not installed')
class TestHDF5DatasetSegment(unittest.TestCase):
    def setUp(self):
        self.data = numpy.reshape(numpy.arange(24, dtype='int16'), (4, 6))
        fd, self.file_path = tempfile.mkstemp(suffix='.h5')
        os.close(fd)
        with h5py.File(self.file_path, 'w') as h5_file:
            h5_file.create_dataset('the_data', data=self.data)

    def tearDown(self):
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

    def test_construct_from_path_forces_close_file(self):
        data_segment = HDF5DatasetSegment(self.file_path, 'the_data')
        self.assertTrue(data_segment.close_file)
        self.assertEqual(data_segment.mode, 'r')
        data_segment.close()

    def test_construct_from_file_object_ownership(self):
        with self.subTest(msg='close_file defaults False for open h5py.File'):
            h5_file = h5py.File(self.file_path, 'r')
            data_segment = HDF5DatasetSegment(h5_file, h5_file['the_data'])
            self.assertFalse(data_segment.close_file)
            data_segment.close()
            self.assertTrue(h5_file.id.valid, msg='file should remain open')
            h5_file.close()

        with self.subTest(msg='close_file True closes h5py.File'):
            h5_file = h5py.File(self.file_path, 'r')
            data_segment = HDF5DatasetSegment(
                h5_file, h5_file['the_data'], close_file=True)
            self.assertTrue(data_segment.close_file)
            data_segment.close()
            self.assertFalse(h5_file.id.valid, msg='file should be closed')

    def test_read(self):
        data_segment = HDF5DatasetSegment(self.file_path, 'the_data')

        with self.subTest(msg='read_raw full'):
            test_data = data_segment.read_raw(None)
            self.assertTrue(numpy.all(self.data == test_data))

        with self.subTest(msg='read_raw positive step slice'):
            subscript = (slice(1, 3, 1), slice(0, 4, 2))
            test_data = data_segment.read_raw(subscript)
            self.assertTrue(numpy.all(self.data[subscript] == test_data))

        with self.subTest(msg='read_raw negative step slice'):
            subscript = (slice(3, 0, -1), slice(0, 6, 1))
            test_data = data_segment.read_raw(subscript)
            self.assertTrue(numpy.all(self.data[subscript] == test_data))

        with self.subTest(msg='read full'):
            test_data = data_segment.read(None)
            self.assertTrue(numpy.all(self.data == test_data))

        data_segment.close()

    def test_mode_and_write_rejection(self):
        data_segment = HDF5DatasetSegment(self.file_path, 'the_data')

        with self.subTest(msg='only read mode is allowed'):
            self.assertEqual(HDF5DatasetSegment._allowed_modes, ('r', ))
            with self.assertRaises(ValueError):
                data_segment._set_mode('w')

        with self.assertRaises(NotImplementedError, msg='write_raw attempt'):
            data_segment.write_raw(self.data, start_indices=0)

        with self.assertRaises(NotImplementedError, msg='get_raw_bytes attempt'):
            _ = data_segment.get_raw_bytes()

        data_segment.close()

    def test_closed_access(self):
        data_segment = HDF5DatasetSegment(self.file_path, 'the_data')

        with self.subTest(msg='close functionality test'):
            self.assertFalse(data_segment.closed)
            data_segment.close()
            self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError, msg='read access when closed'):
            _ = data_segment.read(None)

        with self.assertRaises(ValueError, msg='read_raw access when closed'):
            _ = data_segment.read_raw(None)


class TestDataSegmentValidation(unittest.TestCase):
    def test_invalid_mode(self):
        data = numpy.reshape(numpy.arange(12, dtype='int16'), (3, 4))
        with self.assertRaises(ValueError, msg='invalid mode string'):
            _ = NumpyArraySegment(data, mode='q')

        with self.assertRaises(TypeError, msg='non-string mode'):
            _ = NumpyArraySegment(data, mode=17)

    def test_mismatched_shapes(self):
        data = numpy.reshape(numpy.arange(12, dtype='int16'), (3, 4))
        with self.assertRaises(ValueError, msg='mismatched raw/formatted shape'):
            _ = NumpyArraySegment(
                data, formatted_dtype='int16', formatted_shape=(5, 6), mode='r')

    def test_access_after_close(self):
        data = numpy.reshape(numpy.arange(12, dtype='int16'), (3, 4))
        data_segment = NumpyArraySegment(data, mode='r')
        data_segment.close()
        self.assertTrue(data_segment.closed)

        with self.assertRaises(ValueError):
            _ = data_segment.read(None)

        with self.assertRaises(ValueError):
            _ = data_segment.read_raw(None)

        write_segment = NumpyArraySegment(
            numpy.empty((3, 4), dtype='int16'), mode='w')
        write_segment.close()

        with self.assertRaises(ValueError):
            write_segment.write(data, start_indices=0)

        with self.assertRaises(ValueError):
            write_segment.write_raw(data, start_indices=0)

    # NB: DataSegment does not define __enter__/__exit__, so there is no
    # context manager protocol to test.


############
# Smoke tests - fast, minimal sanity checks for the data_segment module.
# Run in isolation via:
#   python -m pytest tests/io/general/test_data_segment.py -k smoke -v

class TestDataSegmentSmoke(unittest.TestCase):
    def test_smoke_module_import(self):
        import importlib
        module = importlib.import_module('sarpy.io.general.data_segment')
        for class_name in [
                'DataSegment', 'NumpyArraySegment', 'SubsetSegment',
                'BandAggregateSegment', 'BlockAggregateSegment',
                'ReorientationSegment', 'NumpyMemmapSegment',
                'HDF5DatasetSegment', 'FileReadDataSegment']:
            with self.subTest(msg=class_name):
                self.assertTrue(hasattr(module, class_name))

    def test_smoke_numpy_array_segment_lifecycle(self):
        data = numpy.reshape(numpy.arange(4, dtype='int16'), (2, 2))
        data_segment = NumpyArraySegment(data, mode='r')
        test_data = data_segment.read(None)
        self.assertEqual(test_data.shape, (2, 2))
        self.assertTrue(numpy.all(data == test_data))
        data_segment.close()
        self.assertTrue(data_segment.closed)

    def test_smoke_subset_segment(self):
        data = numpy.reshape(numpy.arange(12, dtype='int16'), (3, 4))
        data_segment = SubsetSegment(
            NumpyArraySegment(data, mode='r'), (slice(0, 2, 1), slice(0, 2, 1)), 'raw')
        test_data = data_segment.read(None)
        self.assertEqual(test_data.shape, (2, 2))
        self.assertTrue(numpy.all(data[:2, :2] == test_data))
        data_segment.close()

    def test_smoke_band_aggregate_segment(self):
        data0 = numpy.reshape(numpy.arange(4, dtype='int16'), (2, 2))
        data1 = numpy.reshape(numpy.arange(4, 8, dtype='int16'), (2, 2))
        data_segment = BandAggregateSegment(
            (NumpyArraySegment(data0, mode='r'), NumpyArraySegment(data1, mode='r')), 2)
        test_data = data_segment.read(None)
        self.assertEqual(test_data.shape, (2, 2, 2))
        self.assertTrue(numpy.all(data0 == test_data[..., 0]))
        data_segment.close()

    def test_smoke_block_aggregate_segment(self):
        data0 = numpy.reshape(numpy.arange(4, dtype='int16'), (2, 2))
        data1 = numpy.reshape(numpy.arange(4, 8, dtype='int16'), (2, 2))
        data_segment = BlockAggregateSegment(
            (NumpyArraySegment(data0, mode='r'), NumpyArraySegment(data1, mode='r')),
            ((slice(0, 2, 1), slice(0, 2, 1)), (slice(0, 2, 1), slice(2, 4, 1))),
            'raw', 0, (2, 4), 'int16', (2, 4))
        test_data = data_segment.read(None)
        self.assertEqual(test_data.shape, (2, 4))
        self.assertTrue(numpy.all(data0 == test_data[:, :2]))
        data_segment.close()

    def test_smoke_reorientation_segment(self):
        data = numpy.reshape(numpy.arange(12, dtype='int16'), (3, 4))
        data_segment = ReorientationSegment(
            NumpyArraySegment(data, mode='r'), transpose_axes=(1, 0))
        test_data = data_segment.read(None)
        self.assertEqual(test_data.shape, (4, 3))
        self.assertTrue(numpy.all(numpy.transpose(data) == test_data))
        data_segment.close()

    def test_smoke_numpy_memmap_segment(self):
        data = numpy.reshape(numpy.arange(4, dtype='int16'), (2, 2))
        fd, file_path = tempfile.mkstemp(suffix='.dat')
        os.close(fd)
        try:
            data.tofile(file_path)
            data_segment = NumpyMemmapSegment(file_path, 0, 'int16', (2, 2), mode='r')
            test_data = data_segment.read(None)
            self.assertEqual(test_data.shape, (2, 2))
            self.assertTrue(numpy.all(data == test_data))
            data_segment.close()
        finally:
            os.remove(file_path)

    def test_smoke_file_read_data_segment(self):
        data = numpy.reshape(numpy.arange(4, dtype='int16'), (2, 2))
        data_segment = FileReadDataSegment(
            BytesIO(data.tobytes()), 0, 'int16', (2, 2), 'int16', (2, 2))
        test_data = data_segment.read(None)
        self.assertEqual(test_data.shape, (2, 2))
        self.assertTrue(numpy.all(data == test_data))
        data_segment.close()

    @unittest.skipIf(h5py is None, 'h5py is not installed')
    def test_smoke_hdf5_dataset_segment(self):
        data = numpy.reshape(numpy.arange(4, dtype='int16'), (2, 2))
        fd, file_path = tempfile.mkstemp(suffix='.h5')
        os.close(fd)
        try:
            with h5py.File(file_path, 'w') as h5_file:
                h5_file.create_dataset('the_data', data=data)
            data_segment = HDF5DatasetSegment(file_path, 'the_data')
            test_data = data_segment.read(None)
            self.assertEqual(test_data.shape, (2, 2))
            self.assertTrue(numpy.all(data == test_data))
            data_segment.close()
        finally:
            os.remove(file_path)
