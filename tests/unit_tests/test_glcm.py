import numpy as np
import pytest

from glcm_cupy import GLCM, glcm
from glcm_cupy.glcm.glcm_py import glcm_py_im


@pytest.mark.parametrize(
    "size",
    [15, ]
)
@pytest.mark.parametrize(
    "bins",
    [4, 16]
)
@pytest.mark.parametrize(
    "radius",
    [1, 2, 4]
)
def test_glcm(size, bins, radius):
    ar = np.random.randint(0, bins, [size, size, 1])
    g = GLCM(radius=radius, bin_from=bins, bin_to=bins).run(ar)
    g_fn = glcm(ar, radius=radius, bin_from=bins, bin_to=bins)
    expected = glcm_py_im(ar, radius=radius, bin_from=bins, bin_to=bins)
    assert g == pytest.approx(expected, abs=0.001)
    assert g_fn == pytest.approx(expected, abs=0.001)


def test_channel_independence():
    """ This asserts that the channel GLCMs are independent """
    ar = np.random.randint(0, 255, [16, 16, 2])
    radius, bins = 3, 16
    ar0, ar1 = ar[..., 0:1], ar[..., 1:2]
    glcm = GLCM(radius=radius, bin_from=256, bin_to=bins)
    g = glcm.run(ar)
    g0 = glcm.run(ar0)
    g1 = glcm.run(ar1)
    g_exp = np.concatenate([g0, g1], axis=2)
    assert g == pytest.approx(g_exp, abs=1e-06)
