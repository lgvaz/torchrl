import time
from collections import defaultdict
from datetime import timedelta
from tensorboardX import SummaryWriter

import numpy as np


class Logger:
    def __init__(self, log_dir=None, debug=False):
        self.debug = debug
        self.logs = defaultdict(list)
        self.histograms = dict()
        self.precision = dict()
        self.time = time.time()
        self.steps_sum = 0
        self.eta = None
        self.i_step = 0

        print('Writing logs to: {}'.format(log_dir))
        self.writer = SummaryWriter(log_dir=log_dir)

    def add_log(self, name, value, precision=2):
        self.logs[name].append(value)
        self.precision[name] = precision

    def add_debug(self, name, value, precision=2):
        if self.debug:
            self.add_log(name, value, precision)

    def add_histogram(self, name, values):
        self.histograms[name] = np.array(values)

    def log(self, header=None):
        ''' Write the mean of the values added to each key and clear previous values '''
        # Take the mean of the values
        self.logs = {key: np.mean(value) for key, value in self.logs.items()}
        # Convert values to string, with defined precision
        avg_dict = {
            key: '{:.{prec}f}'.format(value, prec=self.precision[key])
            for key, value in self.logs.items()
        }

        # Log to the console
        if self.eta is not None:
            header += ' | ETA: {}'.format(self.eta)
        print_table(avg_dict, header)

        # Write tensorboard summary
        if self.writer is not None:
            for key, value in self.logs.items():
                self.writer.add_scalar(key, value, global_step=self.i_step)
            for key, value in self.histograms.items():
                self.writer.add_histogram(key, value, global_step=self.i_step)

        # Reset dict
        self.logs = defaultdict(list)
        self.histograms = dict()

    def timeit(self, i_step, max_steps=-1):
        steps, self.i_step = i_step - self.i_step, i_step
        new_time = time.time()
        steps_sec = steps / (new_time - self.time)
        self.add_log('Steps_per_second', steps_sec)
        self.time = new_time
        self.steps_sum += steps

        if max_steps != -1:
            eta_seconds = (max_steps - self.steps_sum) / steps_sec
            # Format days, hours, minutes, seconds and remove milliseconds
            self.eta = str(timedelta(seconds=eta_seconds)).split('.')[0]


def print_table(tags_and_values_dict, header=None, width=42):
    '''
    Prints a pretty table =)
    Expects keys and values of dict to be a string
    '''

    tags_maxlen = max(len(tag) for tag in tags_and_values_dict)
    values_maxlen = max(len(value) for value in tags_and_values_dict.values())

    max_width = max(width, tags_maxlen + values_maxlen)

    print()
    if header:
        print(header)

    print((2 + max_width) * '-')

    for tag, value in tags_and_values_dict.items():
        num_spaces = 2 + values_maxlen - len(value)
        string_right = '{:{n}}{}'.format('|', value, n=num_spaces)
        num_spaces = 2 + max_width - len(tag) - len(string_right)
        print(''.join((tag, ' ' * num_spaces, string_right)))

    print((2 + max_width) * '-')
