#pyresample, Resampling of remote sensing image data in python
# 
# Copyright (C) 2010, 2014  Esben S. Nielsen
#                           Adam.Dybbroe
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Handles reprojection of geolocated data. Several types of resampling are
supported"""

from __future__ import absolute_import

import types
import warnings
import sys

import numpy as np

from . import geometry
from . import data_reduce
from . import _spatial_mp

if sys.version < '3':
    range = xrange
else:
    long = int

kd_tree_name = None
try:
    from pykdtree.kdtree import KDTree
    kd_tree_name = 'pykdtree'
except ImportError:
    try:
        import scipy.spatial as sp
        kd_tree_name = 'scipy.spatial'
    except ImportError:
        raise ImportError('Either pykdtree or scipy must be available')


class EmptyResult(Exception):
    pass


def which_kdtree():
    """Returns the name of the kdtree used for resampling
    """

    return kd_tree_name


def resample_nearest(source_geo_def, data, target_geo_def,
                     radius_of_influence, epsilon=0,
                     fill_value=0, reduce_data=True, nprocs=1, segments=None):
    """Resamples data using kd-tree nearest neighbour approach

    :Parameters:
    source_geo_def : object
        Geometry definition of source
    data : numpy array               
        1d array of single channel data points or
        (source_size, k) array of k channels of datapoints
    target_geo_def : object
        Geometry definition of target
    radius_of_influence : float 
        Cut off distance in meters
    epsilon : float, optional
        Allowed uncertainty in meters. Increasing uncertainty
        reduces execution time
    fill_value : {int, None}, optional 
            Set undetermined pixels to this value.
            If fill_value is None a masked array is returned 
            with undetermined pixels masked    
    reduce_data : bool, optional
        Perform initial coarse reduction of source dataset in order
        to reduce execution time
    nprocs : int, optional
        Number of processor cores to be used
    segments : {int, None}
        Number of segments to use when resampling.
        If set to None an estimate will be calculated

    :Returns: 
    data : numpy array 
        Source data resampled to target geometry
    """

    return _resample(source_geo_def, data, target_geo_def, 'nn',
                     radius_of_influence, neighbours=1,
                     epsilon=epsilon, fill_value=fill_value,
                     reduce_data=reduce_data, nprocs=nprocs, segments=segments)


def resample_gauss(source_geo_def, data, target_geo_def,
                   radius_of_influence, sigmas, neighbours=8, epsilon=0,
                   fill_value=0, reduce_data=True, nprocs=1, segments=None, with_uncert=False):
    """Resamples data using kd-tree gaussian weighting neighbour approach

    :Parameters:
    source_geo_def : object
        Geometry definition of source
    data : numpy array               
        Array of single channel data points or
        (source_geo_def.shape, k) array of k channels of datapoints
    target_geo_def : object
        Geometry definition of target
    radius_of_influence : float 
        Cut off distance in meters
    sigmas : list of floats or float            
        List of sigmas to use for the gauss weighting of each 
        channel 1 to k, w_k = exp(-dist^2/sigma_k^2).
        If only one channel is resampled sigmas is a single float value.
    neighbours : int, optional 
        The number of neigbours to consider for each grid point
    epsilon : float, optional
        Allowed uncertainty in meters. Increasing uncertainty
        reduces execution time
    fill_value : {int, None}, optional 
            Set undetermined pixels to this value.
            If fill_value is None a masked array is returned 
            with undetermined pixels masked    
    reduce_data : bool, optional
        Perform initial coarse reduction of source dataset in order
        to reduce execution time
    nprocs : int, optional
        Number of processor cores to be used
    segments : {int, None}
        Number of segments to use when resampling.
        If set to None an estimate will be calculated
    with_uncert : bool, optional
        Calculate uncertainty estimates

    :Returns:
    data : numpy array (default)
        Source data resampled to target geometry

    data, stddev, counts : numpy array, numpy array, numpy array (if with_uncert == True)
        Source data resampled to target geometry.
        Weighted standard devaition for all pixels having more than one source value
        Counts of number of source values used in weighting per pixel        
    """

    def gauss(sigma):
        # Return gauss function object
        return lambda r: np.exp(-r ** 2 / float(sigma) ** 2)

    # Build correct sigma argument
    is_multi_channel = False
    try:
        sigmas.__iter__()
        sigma_list = sigmas
        is_multi_channel = True
    except:
        sigma_list = [sigmas]

    for sigma in sigma_list:
        if not isinstance(sigma, (long, int, float)):
            raise TypeError('sigma must be number')

    # Get gauss function objects
    if is_multi_channel:
        weight_funcs = list(map(gauss, sigma_list))
    else:
        weight_funcs = gauss(sigmas)

    return _resample(source_geo_def, data, target_geo_def, 'custom',
                     radius_of_influence, neighbours=neighbours,
                     epsilon=epsilon, weight_funcs=weight_funcs, fill_value=fill_value,
                     reduce_data=reduce_data, nprocs=nprocs, segments=segments, with_uncert=with_uncert)


def resample_custom(source_geo_def, data, target_geo_def,
                    radius_of_influence, weight_funcs, neighbours=8,
                    epsilon=0, fill_value=0, reduce_data=True, nprocs=1,
                    segments=None, with_uncert=False):
    """Resamples data using kd-tree custom radial weighting neighbour approach

    :Parameters:
    source_geo_def : object
        Geometry definition of source
    data : numpy array               
        Array of single channel data points or
        (source_geo_def.shape, k) array of k channels of datapoints
    target_geo_def : object
        Geometry definition of target
    radius_of_influence : float 
        Cut off distance in meters
    weight_funcs : list of function objects or function object       
        List of weight functions f(dist) to use for the weighting 
        of each channel 1 to k.
        If only one channel is resampled weight_funcs is
        a single function object.
    neighbours : int, optional 
        The number of neigbours to consider for each grid point
    epsilon : float, optional
        Allowed uncertainty in meters. Increasing uncertainty
        reduces execution time
    fill_value : {int, None}, optional 
            Set undetermined pixels to this value.
            If fill_value is None a masked array is returned 
            with undetermined pixels masked    
    reduce_data : bool, optional
        Perform initial coarse reduction of source dataset in order
        to reduce execution time
    nprocs : int, optional
        Number of processor cores to be used
    segments : {int, None}
        Number of segments to use when resampling.
        If set to None an estimate will be calculated

    :Returns:
    data : numpy array (default)
        Source data resampled to target geometry

    data, stddev, counts : numpy array, numpy array, numpy array (if with_uncert == True)
        Source data resampled to target geometry.
        Weighted standard devaition for all pixels having more than one source value
        Counts of number of source values used in weighting per pixel
    """

    try:
        for weight_func in weight_funcs:
            if not isinstance(weight_func, types.FunctionType):
                raise TypeError('weight_func must be function object')
    except:
        if not isinstance(weight_funcs, types.FunctionType):
            raise TypeError('weight_func must be function object')

    return _resample(source_geo_def, data, target_geo_def, 'custom',
                     radius_of_influence, neighbours=neighbours,
                     epsilon=epsilon, weight_funcs=weight_funcs,
                     fill_value=fill_value, reduce_data=reduce_data,
                     nprocs=nprocs, segments=segments, with_uncert=with_uncert)


def _resample(source_geo_def, data, target_geo_def, resample_type,
              radius_of_influence, neighbours=8, epsilon=0, weight_funcs=None,
              fill_value=0, reduce_data=True, nprocs=1, segments=None, with_uncert=False):
    """Resamples swath using kd-tree approach"""

    valid_input_index, valid_output_index, index_array, distance_array = \
        get_neighbour_info(source_geo_def,
                           target_geo_def,
                           radius_of_influence,
                           neighbours=neighbours,
                           epsilon=epsilon,
                           reduce_data=reduce_data,
                           nprocs=nprocs,
                           segments=segments)

    return get_sample_from_neighbour_info(resample_type,
                                          target_geo_def.shape,
                                          data, valid_input_index,
                                          valid_output_index,
                                          index_array,
                                          distance_array=distance_array,
                                          weight_funcs=weight_funcs,
                                          fill_value=fill_value,
                                          with_uncert=with_uncert)
    
def get_neighbour_info(source_geo_def, target_geo_def, radius_of_influence, 
                       neighbours=8, epsilon=0, reduce_data=True, 
                       nprocs=1, segments=None):

    """Returns neighbour info

    :Parameters:
    source_geo_def : object
        Geometry definition of source
    target_geo_def : object
        Geometry definition of target
    radius_of_influence : float 
        Cut off distance in meters
    neighbours : int, optional 
        The number of neigbours to consider for each grid point
    epsilon : float, optional
        Allowed uncertainty in meters. Increasing uncertainty
        reduces execution time
    fill_value : {int, None}, optional 
            Set undetermined pixels to this value.
            If fill_value is None a masked array is returned 
            with undetermined pixels masked    
    reduce_data : bool, optional
        Perform initial coarse reduction of source dataset in order
        to reduce execution time
    nprocs : int, optional
        Number of processor cores to be used
    segments : {int, None}
        Number of segments to use when resampling.
        If set to None an estimate will be calculated

    :Returns:
    (valid_input_index, valid_output_index, 
    index_array, distance_array) : tuple of numpy arrays
        Neighbour resampling info
    """

    if source_geo_def.size < neighbours:
        warnings.warn('Searching for %s neighbours in %s data points' %
                      (neighbours, source_geo_def.size))

    if segments is None:
        cut_off = 3000000
        if target_geo_def.size > cut_off:
            segments = int(target_geo_def.size / cut_off)
        else:
            segments = 1

    # Find reduced input coordinate set
    valid_input_index, source_lons, source_lats = _get_valid_input_index(source_geo_def, target_geo_def,
                                                                         reduce_data,
                                                                         radius_of_influence,
                                                                         nprocs=nprocs)

    # Create kd-tree
    try:
        resample_kdtree = _create_resample_kdtree(source_lons, source_lats,
                                                  valid_input_index,
                                                  nprocs=nprocs)
    except EmptyResult:
        # Handle if all input data is reduced away
        valid_output_index, index_array, distance_array = \
            _create_empty_info(source_geo_def, target_geo_def, neighbours)
        return (valid_input_index, valid_output_index, index_array,
                distance_array)

    if segments > 1:
        # Iterate through segments
        for i, target_slice in enumerate(geometry._get_slice(segments,
                                                             target_geo_def.shape)):

            # Query on slice of target coordinates
            next_voi, next_ia, next_da = \
                _query_resample_kdtree(resample_kdtree, source_geo_def,
                                       target_geo_def,
                                       radius_of_influence, target_slice,
                                       neighbours=neighbours,
                                       epsilon=epsilon,
                                       reduce_data=reduce_data,
                                       nprocs=nprocs)

            # Build result iteratively
            if i == 0:
                # First iteration
                valid_output_index = next_voi
                index_array = next_ia
                distance_array = next_da
            else:
                valid_output_index = np.append(valid_output_index, next_voi)
                if neighbours > 1:
                    index_array = np.row_stack((index_array, next_ia))
                    distance_array = np.row_stack((distance_array, next_da))
                else:
                    index_array = np.append(index_array, next_ia)
                    distance_array = np.append(distance_array, next_da)
    else:
        # Query kd-tree with full target coordinate set
        full_slice = slice(None)
        valid_output_index, index_array, distance_array = \
            _query_resample_kdtree(resample_kdtree, source_geo_def,
                                   target_geo_def,
                                   radius_of_influence, full_slice,
                                   neighbours=neighbours,
                                   epsilon=epsilon,
                                   reduce_data=reduce_data,
                                   nprocs=nprocs)

    # Check if number of neighbours is potentially too low
    if neighbours > 1:
        if not np.all(np.isinf(distance_array[:, -1])):
            warnings.warn(('Possible more than %s neighbours '
                           'within %s m for some data points') %
                          (neighbours, radius_of_influence))

    return valid_input_index, valid_output_index, index_array, distance_array


def _get_valid_input_index(source_geo_def, target_geo_def, reduce_data,
                           radius_of_influence, nprocs=1):
    """Find indices of reduced inputput data"""

    source_lons, source_lats = source_geo_def.get_lonlats(nprocs=nprocs)
    source_lons = source_lons.ravel()
    source_lats = source_lats.ravel()

    if source_lons.size == 0 or source_lats.size == 0:
        raise ValueError('Cannot resample empty data set')
    elif source_lons.size != source_lats.size or \
            source_lons.shape != source_lats.shape:
        raise ValueError('Mismatch between lons and lats')

    # Remove illegal values
    valid_data = ((source_lons >= -180) & (source_lons <= 180) &
                  (source_lats <= 90) & (source_lats >= -90))
    valid_input_index = np.ones(source_geo_def.size, dtype=np.bool)

    if reduce_data:
        # Reduce dataset
        if (isinstance(source_geo_def, geometry.CoordinateDefinition) and
            isinstance(target_geo_def, (geometry.GridDefinition,
                                        geometry.AreaDefinition))) or \
           (isinstance(source_geo_def, (geometry.GridDefinition,
                                        geometry.AreaDefinition)) and
            isinstance(target_geo_def, (geometry.GridDefinition,
                                        geometry.AreaDefinition))):
            # Resampling from swath to grid or from grid to grid
            lonlat_boundary = target_geo_def.get_boundary_lonlats()
            valid_input_index = \
                data_reduce.get_valid_index_from_lonlat_boundaries(
                    lonlat_boundary[0],
                    lonlat_boundary[1],
                    source_lons, source_lats,
                    radius_of_influence)

    # Combine reduced and legal values
    valid_input_index = (valid_data & valid_input_index)

    if(isinstance(valid_input_index, np.ma.core.MaskedArray)):
        # Make sure valid_input_index is not a masked array
        valid_input_index = valid_input_index.filled(False)

    return valid_input_index, source_lons, source_lats


def _get_valid_output_index(source_geo_def, target_geo_def, target_lons,
                            target_lats, reduce_data, radius_of_influence):
    """Find indices of reduced output data"""

    valid_output_index = np.ones(target_lons.size, dtype=np.bool)

    if reduce_data:
        if isinstance(source_geo_def, (geometry.GridDefinition,
                                       geometry.AreaDefinition)) and \
                isinstance(target_geo_def, geometry.CoordinateDefinition):
            # Resampling from grid to swath
            lonlat_boundary = source_geo_def.get_boundary_lonlats()
            valid_output_index = \
                data_reduce.get_valid_index_from_lonlat_boundaries(
                    lonlat_boundary[0],
                    lonlat_boundary[1],
                    target_lons,
                    target_lats,
                    radius_of_influence)
            valid_output_index = valid_output_index.astype(np.bool)

    # Remove illegal values
    valid_out = ((target_lons >= -180) & (target_lons <= 180) &
                 (target_lats <= 90) & (target_lats >= -90))

    # Combine reduced and legal values
    valid_output_index = (valid_output_index & valid_out)

    return valid_output_index


def _create_resample_kdtree(source_lons, source_lats, valid_input_index, nprocs=1):
    """Set up kd tree on input"""

    """
    if not isinstance(source_geo_def, geometry.BaseDefinition):
        raise TypeError('source_geo_def must be of geometry type')
    
    #Get reduced cartesian coordinates and flatten them
    source_cartesian_coords = source_geo_def.get_cartesian_coords(nprocs=nprocs)
    input_coords = geometry._flatten_cartesian_coords(source_cartesian_coords)
    input_coords = input_coords[valid_input_index]
    """

    source_lons_valid = source_lons[valid_input_index]
    source_lats_valid = source_lats[valid_input_index]

    if nprocs > 1:
        cartesian = _spatial_mp.Cartesian_MP(nprocs)
    else:
        cartesian = _spatial_mp.Cartesian()

    input_coords = cartesian.transform_lonlats(
        source_lons_valid, source_lats_valid)

    if input_coords.size == 0:
        raise EmptyResult('No valid data points in input data')

    # Build kd-tree on input
    if kd_tree_name == 'pykdtree':
        resample_kdtree = KDTree(input_coords)
    elif nprocs > 1:
        resample_kdtree = _spatial_mp.cKDTree_MP(input_coords,
                                                 nprocs=nprocs)
    else:
        resample_kdtree = sp.cKDTree(input_coords)

    return resample_kdtree


def _query_resample_kdtree(resample_kdtree, source_geo_def, target_geo_def,
                           radius_of_influence, data_slice,
                           neighbours=8, epsilon=0, reduce_data=True, nprocs=1):
    """Query kd-tree on slice of target coordinates"""

    # Check validity of input
    if not isinstance(target_geo_def, geometry.BaseDefinition):
        raise TypeError('target_geo_def must be of geometry type')
    elif not isinstance(radius_of_influence, (long, int, float)):
        raise TypeError('radius_of_influence must be number')
    elif not isinstance(neighbours, int):
        raise TypeError('neighbours must be integer')
    elif not isinstance(epsilon, (long, int, float)):
        raise TypeError('epsilon must be number')

    # Get sliced target coordinates
    target_lons, target_lats = target_geo_def.get_lonlats(nprocs=nprocs,
                                                          data_slice=data_slice, dtype=source_geo_def.dtype)

    # Find indiced of reduced target coordinates
    valid_output_index = _get_valid_output_index(source_geo_def,
                                                 target_geo_def,
                                                 target_lons.ravel(),
                                                 target_lats.ravel(),
                                                 reduce_data,
                                                 radius_of_influence)

    # Get cartesian target coordinates and select reduced set
    if nprocs > 1:
        cartesian = _spatial_mp.Cartesian_MP(nprocs)
    else:
        cartesian = _spatial_mp.Cartesian()

    target_lons_valid = target_lons.ravel()[valid_output_index]
    target_lats_valid = target_lats.ravel()[valid_output_index]

    output_coords = cartesian.transform_lonlats(
        target_lons_valid, target_lats_valid)

    # Query kd-tree
    distance_array, index_array = resample_kdtree.query(output_coords,
                                                        k=neighbours,
                                                        eps=epsilon,
                                                        distance_upper_bound=radius_of_influence)

    return valid_output_index, index_array, distance_array


def _create_empty_info(source_geo_def, target_geo_def, neighbours):
    """Creates dummy info for empty result set"""

    valid_output_index = np.ones(target_geo_def.size, dtype=np.bool)
    if neighbours > 1:
        index_array = (np.ones((target_geo_def.size, neighbours),
                               dtype=np.int32) * source_geo_def.size)
        distance_array = np.ones((target_geo_def.size, neighbours))
    else:
        index_array = (np.ones(target_geo_def.size, dtype=np.int32) *
                       source_geo_def.size)
        distance_array = np.ones(target_geo_def.size)

    return valid_output_index, index_array, distance_array


def get_sample_from_neighbour_info(resample_type, output_shape, data,
                                   valid_input_index, valid_output_index,
                                   index_array, distance_array=None,
                                   weight_funcs=None, fill_value=0,
                                   with_uncert=False):
    """Resamples swath based on neighbour info

    :Parameters:
    resample_type : {'nn', 'custom'}
        'nn': Use nearest neighbour resampling
        'custom': Resample based on weight_funcs
    output_shape : (int, int)
        Shape of output as (rows, cols)
    data : numpy array
        Source data
    valid_input_index : numpy array
        valid_input_index from get_neighbour_info
    valid_output_index : numpy array
        valid_output_index from get_neighbour_info
    index_array : numpy array
        index_array from get_neighbour_info
    distance_array : numpy array, optional
        distance_array from get_neighbour_info
        Not needed for 'nn' resample type
    weight_funcs : list of function objects or function object, optional       
        List of weight functions f(dist) to use for the weighting 
        of each channel 1 to k.
        If only one channel is resampled weight_funcs is
        a single function object.
        Must be supplied when using 'custom' resample type
    fill_value : {int, None}, optional 
        Set undetermined pixels to this value.
        If fill_value is None a masked array is returned 
        with undetermined pixels masked

    :Returns: 
    result : numpy array 
        Source data resampled to target geometry
    """

    if data.ndim > 2 and data.shape[0] * data.shape[1] == valid_input_index.size:
        data = data.reshape(data.shape[0] * data.shape[1], data.shape[2])
    elif data.shape[0] != valid_input_index.size:
        data = data.ravel()

    if valid_input_index.size != data.shape[0]:
        raise ValueError('Mismatch between geometry and dataset')

    is_multi_channel = (data.ndim > 1)
    valid_input_size = valid_input_index.sum()
    valid_output_size = valid_output_index.sum()

    # Handle empty result set
    if valid_input_size == 0 or valid_output_size == 0:
        if is_multi_channel:
            output_shape = list(output_shape)
            output_shape.append(data.shape[1])

        if fill_value is None:
            # Use masked array for fill values
            return np.ma.array(np.zeros(output_shape, data.dtype),
                               mask=np.ones(output_shape, dtype=np.bool))
        else:
            # Return fill vaues for all pixels
            return np.ones(output_shape, dtype=data.dtype) * fill_value

    # Get size of output and reduced input
    input_size = valid_input_size
    if len(output_shape) > 1:
        output_size = output_shape[0] * output_shape[1]
    else:
        output_size = output_shape[0]

    # Check validity of input
    if not isinstance(data, np.ndarray):
        raise TypeError('data must be numpy array')
    elif valid_input_index.ndim != 1:
        raise TypeError('valid_index must be one dimensional array')
    elif data.shape[0] != valid_input_index.size:
        raise TypeError('Not the same number of datapoints in '
                        'valid_input_index and data')

    valid_types = ('nn', 'custom')
    if not resample_type in valid_types:
        raise TypeError('Invalid resampling type: %s' % resample_type)

    if resample_type == 'custom' and weight_funcs is None:
        raise ValueError('weight_funcs must be supplied when using '
                         'custom resampling')

    if not isinstance(fill_value, (long, int, float)) and fill_value is not None:
        raise TypeError('fill_value must be number or None')

    if index_array.ndim == 1:
        neighbours = 1
    else:
        neighbours = index_array.shape[1]
        if resample_type == 'nn':
            raise ValueError('index_array contains more neighbours than '
                             'just the nearest')

    # Reduce data
    new_data = data[valid_input_index]

    # Nearest neighbour resampling should conserve data type
    # Get data type
    conserve_input_data_type = False
    if resample_type == 'nn':
        conserve_input_data_type = True
        input_data_type = new_data.dtype

    # Handle masked array input
    is_masked_data = False
    if np.ma.is_masked(new_data):
        # Add the mask as channels to the dataset
        is_masked_data = True
        new_data = np.column_stack((new_data.data, new_data.mask))

    if new_data.ndim > 1:  # Multiple channels or masked input
        output_shape = list(output_shape)
        output_shape.append(new_data.shape[1])

    # Prepare weight_funcs argument for handeling mask data
    if weight_funcs is not None and is_masked_data:
        if is_multi_channel:
            weight_funcs = weight_funcs * 2
        else:
            weight_funcs = (weight_funcs,) * 2

    # Handle request for masking intead of using fill values
    use_masked_fill_value = False
    if fill_value is None:
        use_masked_fill_value = True
        fill_value = _get_fill_mask_value(new_data.dtype)

    # Resample based on kd-tree query result
    if resample_type == 'nn' or neighbours == 1:
        # Get nearest neighbour using array indexing
        index_mask = (index_array == input_size)
        new_index_array = np.where(index_mask, 0, index_array)
        result = new_data[new_index_array]
        result[index_mask] = fill_value
    else:
        # Calculate result using weighting.
        # Note: the code below has low readability in order
        #       to avoid looping over numpy arrays

        # Get neighbours and masks of valid indices
        ch_neighbour_list = []
        index_mask_list = []
        for i in range(neighbours):  # Iterate over number of neighbours
            # Make working copy neighbour index and
            # set out of bounds indices to zero
            index_ni = index_array[:, i].copy()
            index_mask_ni = (index_ni == input_size)
            index_ni[index_mask_ni] = 0

            # Get channel data for the corresponing indices
            ch_ni = new_data[index_ni]
            ch_neighbour_list.append(ch_ni)
            index_mask_list.append(index_mask_ni)

        # Calculate weights
        weight_list = []
        for i in range(neighbours):  # Iterate over number of neighbours
            # Make working copy of neighbour distances and
            # set out of bounds distance to 1 in order to avoid numerical Inf
            distance = distance_array[:, i].copy()
            distance[index_mask_list[i]] = 1

            if new_data.ndim > 1:  # More than one channel in data set.
                # Calculate weights for each channel
                weights = []
                num_weights = valid_output_index.sum()
                num_channels = new_data.shape[1]
                for j in range(num_channels):
                    calc_weight = weight_funcs[j](distance)
                    # Turn a scalar weight into a numpy array
                    # (no effect if calc_weight already is an array)
                    expanded_calc_weight = np.ones(num_weights) * calc_weight
                    weights.append(expanded_calc_weight)

                # Collect weights for all channels for neighbour number
                weight_list.append(np.column_stack(weights))
            else:  # Only one channel
                weights = weight_funcs(distance)
                weight_list.append(weights)

        result = 0
        norm = 0
        count = 0
        norm_sqr = 0
        stddev = 0

        # Calculate result
        for i in range(neighbours):  # Iterate over number of neighbours
            # Find invalid indices to be masked of from calculation
            if new_data.ndim > 1:  # More than one channel in data set.
                inv_index_mask = np.expand_dims(
                    np.invert(index_mask_list[i]), axis=1)
            else:  # Only one channel
                inv_index_mask = np.invert(index_mask_list[i])

            # Aggregate result and norm
            weights_tmp = inv_index_mask * weight_list[i]
            result += weights_tmp * ch_neighbour_list[i]
            norm += weights_tmp

        # Normalize result and set fillvalue
        result_valid_index = (norm > 0)
        result[result_valid_index] /= norm[result_valid_index]

        if with_uncert:  # Calculate uncertainties
            # 2. pass to calculate standard deviation
            for i in range(neighbours):  # Iterate over number of neighbours
                # Find invalid indices to be masked of from calculation
                if new_data.ndim > 1:  # More than one channel in data set.
                    inv_index_mask = np.expand_dims(
                        np.invert(index_mask_list[i]), axis=1)
                else:  # Only one channel
                    inv_index_mask = np.invert(index_mask_list[i])

                # Aggregate stddev information
                weights_tmp = inv_index_mask * weight_list[i]
                count += inv_index_mask
                norm_sqr += weights_tmp ** 2
                values = inv_index_mask * ch_neighbour_list[i]
                stddev += weights_tmp * (values - result) ** 2

            # Calculate final stddev
            new_valid_index = (count > 1)
            v1 = norm[new_valid_index]
            v2 = norm_sqr[new_valid_index]
            stddev[new_valid_index] = np.sqrt(
                (v1 / (v1 ** 2 - v2)) * stddev[new_valid_index])
            stddev[~new_valid_index] = np.NaN

        # Add fill values
        result[np.invert(result_valid_index)] = fill_value

    # Create full result
    if new_data.ndim > 1:  # More than one channel
        output_raw_shape = ((output_size, new_data.shape[1]))
    else:  # One channel
        output_raw_shape = output_size

    full_result = np.ones(output_raw_shape) * fill_value
    full_result[valid_output_index] = result
    result = full_result

    if with_uncert:  # Add fill values for uncertainty
        full_stddev = np.ones(output_raw_shape) * np.nan
        full_count = np.zeros(output_raw_shape)
        full_stddev[valid_output_index] = stddev
        full_count[valid_output_index] = count
        stddev = full_stddev
        count = full_count

        stddev = stddev.reshape(output_shape)
        count = count.reshape(output_shape)

        if is_masked_data:  # Ignore uncert computation of masks
            stddev = _remask_data(stddev, is_to_be_masked=False)
            count = _remask_data(count, is_to_be_masked=False)

        # Set masks for invalid stddev
        stddev = np.ma.array(stddev, mask=np.isnan(stddev))

    # Reshape resampled data to correct shape
    result = result.reshape(output_shape)

    # Remap mask channels to create masked output
    if is_masked_data:
        result = _remask_data(result)

    # Create masking of fill values
    if use_masked_fill_value:
        result = np.ma.masked_equal(result, fill_value)

    # Set output data type to input data type if relevant
    if conserve_input_data_type:
        result = result.astype(input_data_type)

    if with_uncert:
        if np.ma.isMA(result):
            stddev = np.ma.array(stddev, mask=(result.mask | stddev.mask))
            count = np.ma.array(count, mask=result.mask)
        return result, stddev, count
    else:
        return result


def _get_fill_mask_value(data_dtype):
    """Returns the maximum value of dtype"""

    if issubclass(data_dtype.type, np.floating):
        fill_value = np.finfo(data_dtype.type).max
    elif issubclass(data_dtype.type, np.integer):
        fill_value = np.iinfo(data_dtype.type).max
    else:
        raise TypeError('Type %s is unsupported for masked fill values' %
                        data_dtype.type)
    return fill_value


def _remask_data(data, is_to_be_masked=True):
    """Interprets half the array as mask for the other half"""

    channels = data.shape[-1]
    if is_to_be_masked:
        mask = data[..., (channels // 2):]
        # All pixels affected by masked pixels are masked out
        mask = (mask != 0)
        data = np.ma.array(data[..., :(channels // 2)], mask=mask)
    else:
        data = data[..., :(channels // 2)]

    if data.shape[-1] == 1:
        data = data.reshape(data.shape[:-1])
    return data
