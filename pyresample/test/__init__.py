#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2014 Martin Raspaud

# Author(s):

#   Martin Raspaud <martin.raspaud@smhi.se>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""The test base.
"""


from pyresample.test import test_geometry, test_grid, test_image, test_kd_tree, test_plot, test_spherical_geometry, test_swath, test_utils

import unittest


def suite():
    """The global test suite.
    """
    mysuite = unittest.TestSuite()
    # Use the unittests also
    mysuite.addTests(test_geometry.suite())
    mysuite.addTests(test_grid.suite())
    mysuite.addTests(test_image.suite())
    mysuite.addTests(test_kd_tree.suite())
    mysuite.addTests(test_plot.suite())
    mysuite.addTests(test_spherical_geometry.suite())
    mysuite.addTests(test_swath.suite())
    mysuite.addTests(test_utils.suite())

    return mysuite
