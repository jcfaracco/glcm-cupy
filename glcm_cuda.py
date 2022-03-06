from __future__ import annotations

import os
from dataclasses import dataclass

import cupy as cp
import numpy as np
from skimage.util import view_as_windows
from tqdm import tqdm

from kernel import glcm_module

BLOCKS = 256
THREADS = 256
MAX_VALUE_SUPPORTED = 255
NO_VALUES_SUPPORTED = 256 ** 2


@dataclass
class GLCM:
    """
    
    Args:
        max_value: Maximum value of the image, default 256
        step_size: Step size of the window
        radius: Radius of the windows
        bins: Bin reduction. If None, then no reduction is done

    """

    max_value: int = 255
    step_size: int = 1
    radius: int = 2
    bins: int | None = None

    threads: int = 256

    HOMOGENEITY = 0
    CONTRAST = 1
    ASM = 2
    MEAN_I = 3
    MEAN_J = 4
    VAR_I = 5
    VAR_J = 6
    CORRELATION = 7

    @property
    def diameter(self):
        return self.radius * 2 + 1

    @property
    def no_of_values(self):
        return self.diameter ** 2

    def __post_init__(self):
        self.i_flat = cp.zeros((self.diameter ** 2,), dtype=cp.uint8)
        self.j_flat = cp.zeros((self.diameter ** 2,), dtype=cp.uint8)
        self.glcm = cp.zeros((self.max_value + 1) ** 2, dtype=cp.uint8)
        self.features = cp.zeros(8, dtype=cp.float32)

        assert self.max_value <= MAX_VALUE_SUPPORTED, \
            f"Max value supported is {MAX_VALUE_SUPPORTED}"
        assert self.no_of_values < NO_VALUES_SUPPORTED, \
            f"Max number of values supported is {NO_VALUES_SUPPORTED}"

        os.environ['CUPY_EXPERIMENTAL_SLICE_COPY'] = '1'

    @staticmethod
    def binarize(im: np.ndarray, from_bins: int, to_bins: int):
        """ Binarize an image from a certain bin to another

        Args:
            im: Image as np.ndarray
            from_bins: From the Bin of input image
            to_bins: To the Bin of output image

        Returns:
            Binarized Image

        """
        return (im / from_bins * to_bins).astype(np.uint8)

    def from_3dimage(self,
                     im: np.ndarray):
        """ Generates the GLCM from a multi band image

        Args:
            im: A 3 dim image as an ndarray

        Returns:
            The GLCM Array 4dim with shape
                rows, cols, channel, feature
        """

        glcm_chs = []
        for ch in range(im.shape[-1]):
            glcm_chs.append(self.from_2dimage(im[..., ch]))

        return np.stack(glcm_chs, axis=2)

    def from_2dimage(self,
                     im: np.ndarray) -> np.ndarray:
        """ Generates the GLCM from a single band image

        Args:
            im: Image in np.ndarray. Cannot be in cp.ndarray

        Returns:
            The GLCM Array 3dim with shape
                rows, cols, feature
        """

        assert im.dtype == np.uint8, \
            f"Image dtype must be of np.uint8, it's {im.dtype}"

        if self.bins is not None:
            im = self.binarize(im, self.max_value, self.bins)

        # This will yield a shape (window_i, window_j, row, col)
        # E.g. 100x100 with 5x5 window -> 96, 96, 5, 5
        windows_ij = view_as_windows(im, (self.diameter, self.diameter))

        # We flatten the cells as cell order is not important
        windows_ij = windows_ij.reshape((*windows_ij.shape[:-2], -1))

        # Yield Windows and flatten the windows
        windows_i = windows_ij[:-self.step_size, :-self.step_size] \
            .reshape((-1, windows_ij.shape[-1]))
        windows_j = windows_ij[self.step_size:, self.step_size:] \
            .reshape((-1, windows_ij.shape[-1]))

        glcm_features = cp.zeros((windows_i.shape[0], 8), dtype=cp.float32)

        for e, (i, j) in tqdm(enumerate(zip(windows_i, windows_j)),
                              total=len(windows_i)):
            glcm_features[e] = self._from_windows(i, j)

        return glcm_features.reshape(windows_ij.shape[0] - self.step_size,
                                     windows_ij.shape[1] - self.step_size, 8)

    def _from_windows(self,
                      i: np.ndarray,
                      j: np.ndarray, ) -> np.ndarray:
        """ Generate the GLCM from the I J Window

        Notes:
            i must be the same shape as j

        Args:
            i: I Window
            j: J Window

        Returns:
            The GLCM array, of size (8,)

        """

        assert i.shape == j.shape, f"Shape of i {i.shape} != j {j.shape}"
        blocks = int(max(i.max(), j.max())) + 1
        self.i_flat[:] = i.flatten()
        self.j_flat[:] = j.flatten()
        self.glcm[:] = 0
        self.features[:] = 0

        glcm_k0 = glcm_module.get_function('glcm_0')
        glcm_k1 = glcm_module.get_function('glcm_1')
        glcm_k2 = glcm_module.get_function('glcm_2')
        glcm_k0(
            grid=(blocks,),
            block=(self.threads,),
            args=(
                self.i_flat, self.j_flat,
                self.max_value, self.no_of_values,
                self.glcm, self.features
            )
        )
        glcm_k1(
            grid=(blocks,),
            block=(self.threads,),
            args=(
                self.glcm, self.max_value,
                self.no_of_values, self.features
            )
        )
        glcm_k2(
            grid=(blocks,),
            block=(self.threads,),
            args=(
                self.glcm, self.max_value,
                self.no_of_values, self.features
            )
        )

        return self.features
