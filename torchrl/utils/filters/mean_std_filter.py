import numpy as np
from torchrl.utils import EPSILON


class MeanStdFilter:
    '''
    Calculates the exact mean and std deviation, originally by `ray_rllib
    <https://github.com/ray-project/ray/blob/master/python/ray/rllib/utils/filter.py#L61>`_.
    '''

    def __init__(self, shape, clip_range=5):
        self.shape = shape
        self.clip_range = clip_range
        self.n = 0
        self.xs = []

        self.M = np.zeros(shape)
        self.S = np.zeros(shape)

    @property
    def mean(self):
        return self.M

    @property
    def var(self):
        if self.n == 0 or self.n == 1:
            return np.ones(self.S.shape)
        else:
            return self.S / (self.n - 1)

    @property
    def std(self):
        return np.sqrt(self.var)

    def update(self):
        n_old = self.n
        n_new = len(self.xs)
        if n_new == 0:
            return

        x = np.array(self.xs)
        self.n += n_new
        self.xs = []

        x_M = x.mean(axis=0)
        x_S = ((x - x_M)**2).sum(axis=0)
        # First update
        if self.n == n_new:
            self.M = x_M
            self.S = x_S
        else:
            new_M = (n_old * self.M + n_new * x_M) / self.n
            self.S = self.S + x_S + (self.M - x_M)**2 * n_old * n_new / self.n
            self.M = new_M

    def normalize(self, x):
        self.xs.extend(x)
        return ((x - self.mean) / (self.std + EPSILON)).clip(
            min=-self.clip_range, max=self.clip_range)

    def scale(self, x):
        self.xs.extend(x)
        return (x / (self.std + EPSILON)).clip(min=-self.clip_range, max=self.clip_range)