import multiprocessing
from collections import namedtuple
from ctypes import c_double, c_float, c_int, c_uint8

# from torch.multiprocessing import Manager, Pipe, Process, Queue
from multiprocessing import Manager, Pipe, Process, Queue
from multiprocessing.sharedctypes import RawArray

import numpy as np

import reward.utils as U
from reward.runner import BaseRunner
from boltons.cacheutils import cachedproperty


class PAACRunner(BaseRunner):
    NUMPY_TO_C_DTYPE = {
        np.float32: c_float,
        np.float64: c_double,
        np.uint8: c_uint8,
        np.int32: c_int,
        np.int64: c_int,
    }

    def __init__(self, env, ep_maxlen=None, num_workers=None):
        super().__init__(env=env, ep_maxlen=ep_maxlen)
        self.num_workers = num_workers or multiprocessing.cpu_count()
        self._env_rs_sum = np.zeros(self.num_envs)
        self._env_ep_lengths = np.zeros(self.num_envs)
        self.manager = Manager()

        self._create_shared_transitions()
        self._create_workers()

    @property
    def env_name(self):
        return self.env[0].env_name

    @property
    def num_envs(self):
        return len(self.env)

    @cachedproperty
    def s_space(self):
        space = self.env[0].s_space
        space.shape = (self.num_envs,) + space.shape
        return space

    @cachedproperty
    def ac_space(self):
        return self.env[0].ac_space

    def _create_shared_transitions(self):
        s = self._get_shared(np.zeros(self.s_space.shape, dtype=self.s_space.dtype))
        ac = self._get_shared(self._get_ac_array())
        r = self._get_shared(np.zeros(self.num_envs, dtype=np.float32))
        d = self._get_shared(np.zeros(self.num_envs, dtype=np.float32))
        info = [self.manager.dict() for _ in range(self.num_envs)]

        self.shared_tran = U.memories.SimpleMemory(s=s, r=r, d=d, ac=ac, info=info)

    def _create_workers(self):
        """
        Creates and starts each worker in a distinct process.

        Parameters
        ----------
        env: list
            List of env, each worker will have approximately the same number of env.
        """
        WorkerNTuple = namedtuple("Worker", ["process", "connection", "barrier"])
        self.workers = []

        for env_i, s_s, s_r, s_d, s_a, s_i in zip(
            self.split(self.env),
            self.split(self.shared_tran.s),
            self.split(self.shared_tran.r),
            self.split(self.shared_tran.d),
            self.split(self.shared_tran.ac),
            self.split(self.shared_tran.info),
        ):

            shared_tran = U.memories.SimpleMemory(s=s_s, r=s_r, d=s_d, ac=s_a, info=s_i)
            parent_conn, child_conn = Pipe()
            queue = Queue()

            process = EnvWorker(
                env=env_i, conn=queue, barrier=child_conn, shared_transition=shared_tran
            )
            process.daemon = True
            process.start()

            self.workers.append(
                WorkerNTuple(process=process, connection=queue, barrier=parent_conn)
            )

    def _get_ac_array(self):
        if isinstance(self.ac_space, U.space.Continuous):
            shape = (self.num_envs, np.prod(self.ac_space.shape))
        elif isinstance(self.ac_space, U.space.Discrete):
            shape = (self.num_envs,)
        else:
            raise ValueError(
                "Action space {} not implemented".format(type(self.ac_space))
            )

        return np.zeros(shape, dtype=self.ac_space.dtype)

    def _get_shared(self, array):
        """
        A numpy array that can be shared between processes.
        From: `alfredcv <https://sourcegraph.com/github.com/Alfredvc/paac/-/blob/runner.py#L20:9-20:20$references>`_.

        Parameters
        ----------
        array: np.array
            The shared to be shared

        Returns
        -------
        A shared numpy array.
        """

        dtype = self.NUMPY_TO_C_DTYPE[array.dtype.type]

        shape = array.shape
        shared = RawArray(dtype, array.reshape(-1))
        return np.frombuffer(shared, dtype).reshape(shape)

    def act(self, ac):
        # Send actions to worker
        self.shared_tran.ac[...] = ac
        for worker in self.workers:
            worker.connection.put(True)
        self.sync()
        self.num_steps += self.num_envs

        sns = self.shared_tran.s.copy()
        rs = self.shared_tran.r.copy()
        ds = self.shared_tran.d.copy()
        infos = list(map(dict, self.shared_tran.info))

        # Accumulate rs
        self._env_rs_sum += rs
        self._env_ep_lengths += 1
        # TODO: Incorporate ep_maxlen
        for i, d in enumerate(ds):
            if d:
                self.rs.append(self._env_rs_sum[i])
                self.ep_lens.append(self._env_ep_lengths[i])
                self._env_rs_sum[i] = 0
                self._env_ep_lengths[i] = 0

        return sns, rs, ds, infos

    def reset(self):
        """
        Reset all workers in parallel, using Pipe for communication.
        """
        # Send signal to reset
        for worker in self.workers:
            worker.connection.put(None)
        # Receive results
        self.sync()
        ss = self.shared_tran.s.copy()

        return ss

    def sample_random_ac(self):
        return np.array([env.sample_random_ac() for env in self.env])

    def sync(self):
        for worker in self.workers:
            worker.barrier.recv()

    def split(self, array):
        """
        Divide the input in approximately equal chunks for all workers.

        Parameters
        ----------
        array: array or list
            The object to be divided.

        Returns
        -------
        list
            The divided object.
        """
        q, r = divmod(self.num_envs, self.num_workers)
        return [
            array[i * q + min(i, r) : (i + 1) * q + min(i + 1, r)]
            for i in range(self.num_workers)
        ]

    def terminate_workers(self):
        for worker in self.workers:
            worker.process.terminate()

    def close(self):
        self.terminate_workers()
        for env in self.env:
            env.close()


class EnvWorker(Process):
    def __init__(self, env, conn, barrier, shared_transition):
        super().__init__()
        self.env = env
        self.conn = conn
        self.barrier = barrier
        self.shared_tran = shared_transition

    def run(self):
        super().run()
        self._run()

    def _run(self):
        while True:
            data = self.conn.get()

            if data is None:
                for i, env in enumerate(self.env):
                    self.shared_tran.s[i] = env.reset()

            else:
                for i, (a, env) in enumerate(zip(self.shared_tran.ac, self.env)):
                    sn, r, d, info = env.step(a)

                    if d:
                        sn = env.reset()

                    self.shared_tran.s[i] = sn
                    self.shared_tran.r[i] = r
                    self.shared_tran.d[i] = d
                    self.shared_tran.info[i].update(info)

            self.barrier.send(True)
