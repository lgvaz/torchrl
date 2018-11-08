import numpy as np
from reward.env.base_env import BaseEnv
import reward.utils as U

# Soft dependency
try:
    import gym
except ImportError:
    _has_gym = False
else:
    _has_gym = True


class GymEnv(BaseEnv):
    """
    Creates and wraps a gym environment.

    Parameters
    ----------
    env_name: str
        The Gym ID of the env. For a list of available envs check
        `this <https://gym.openai.com/envs/>`_ page.
    wrappers: list
        List of wrappers to be applied on the env.
        Each wrapper should be a function that receives and returns the env.
    """

    def __init__(self, env_name, **kwargs):
        if not _has_gym:
            raise ImportError("Could not import gym")
        super().__init__(env_name, **kwargs)

    def _create_env(self):
        env = gym.make(self.env_name)

        return env

    @property
    def state_space(self):
        return GymEnv.get_space(self.env.observation_space)

    @property
    def action_space(self):
        return GymEnv.get_space(self.env.action_space)

    def reset(self):
        """
        Calls the reset method on the gym environment.

        Returns
        -------
        state: numpy.ndarray
            A numpy array with the state information.
        """
        return self.env.reset()

    def step(self, action):
        """
        Calls the step method on the gym environment.

        Parameters
        ----------
        action: int or float or numpy.ndarray
            The action to be executed in the environment, it should be an int for
            discrete enviroments and float for continuous. There's also the possibility
            of executing multiple actions (if the environment supports so),
            in this case it should be a numpy.ndarray.

        Returns
        -------
        next_state: numpy.ndarray
            A numpy array with the state information.
        reward: float
            The reward.
        done: bool
            Flag indicating the termination of the episode.
        """
        # TODO: Squeezing may break some envs (e.g. Pendulum-v0)
        action = np.squeeze(action)
        if isinstance(self.action_space, U.space.Discrete):
            action = int(action)
        next_state, reward, done, info = self.env.step(action)
        return next_state, reward, done, info

    def render(self):
        self.env.render()

    # def record(self, path):
    #     self.env = Monitor(env=self.env, directory=path, video_callable=lambda x: True)

    def sample_random_action(self):
        return self.env.action_space.sample()

    def seed(self, value):
        self.env.seed(value)

    def update_config(self, config):
        """
        Updates a Config object to include information about the environment.

        Parameters
        ----------
        config: Config
            Object used for storing configuration.
        """
        super().update_config(config)
        config.env.obj.update(dict(wrappers=self.wrappers))

    def close(self):
        self.env.close()

    def remove_timestep_limit(self):
        # TODO: Not always the case that time-limit is the first wrapper
        self.env = self.env.env

    @staticmethod
    def get_space(space):
        """
        Gets the shape of the possible types of states in gym.

        Parameters
        ----------
        space: gym.spaces
            Space object that describes the valid actions and observations

        Returns
        -------
        dict
            Dictionary containing the space shape and type
        """
        if isinstance(space, gym.spaces.Box):
            if space.dtype == np.float32:
                return U.space.Continuous(
                    low=space.low, high=space.high, shape=space.shape
                )
        if isinstance(space, gym.spaces.Discrete):
            return NotImplementedError
        if isinstance(space, gym.spaces.MultiDiscrete):
            return NotImplementedError
