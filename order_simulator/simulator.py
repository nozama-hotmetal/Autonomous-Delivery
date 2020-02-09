import time
import logging
import sys; sys.path.append('../server')
from datetime import datetime, timedelta

import numpy as np
import socketio
import eventlet
from threading import Lock, Thread
from torch.utils.tensorboard import SummaryWriter

from simulator_utils import read_time_files
from data_structures import Robot, DeliveryList, DataBase


LOADING_TIME = 5
UNLOADING_TIME = 5

# TODO: queue is not necessary
start = datetime(2020, 1, 1, 0, 0, 0)
now = datetime(2020, 1, 1, 0, 0, 0)
time_lock = Lock()

sio = socketio.Server()
app = socketio.WSGIApp(sio)


@sio.on('connect')
def greeting(*args):
    print(f'Connected')

@sio.on('deliv_list')
def stack_deliv_list(sid, deliv_dict_list):
    global robot, deliv_list
    deliv_list.update_from_scheduler(deliv_dict_list, robot.orientation)

    simulate_round()

def simulate_round():
    global now, timer, deliv_list
    print('='*80)
    print(f'Simulation starting for round {deliv_list.num_round}')
    print('-'.join([str(d.addr) for d in deliv_list.deliv_list]))

    for deliv in deliv_list.deliv_list:
        robot.get_ready_for_next_deliv(deliv.addr)

        if robot.is_turn():
            turn_sec = timer.turn_time(at=robot.latest_addr)
            print(f"\tTurning robot at {robot.latest_addr}: took {turn_sec:.2f} seconds.")
            time_lock.acquire(); now += timedelta(seconds=turn_sec); time_lock.release()

        travel_sec = timer.travel_time(robot.orientation, robot.latest_addr, deliv.addr)
        print(f"Driving robot from {robot.latest_addr} to {robot.next_addr} took {travel_sec:.2f} seconds")
        time_lock.acquire(); now += timedelta(seconds=travel_sec); time_lock.release()
        # TODO: when robot.get_ready_for_next_deliv is updated, delete the below line
        robot.latest_addr = robot.next_addr

        if deliv.addr != 0:
            unloading_sec = timer.unloading_time()
            print(f"\tUnloading took {unloading_sec:.2f} seconds")
            time_lock.acquire(); now += timedelta(seconds=unloading_sec); time_lock.release()

        sio.emit('unload_complete') # to scheduler
        print('Sent unload complete message to the scheduler')
    print('='*80)

@sio.on('deliv_prog')
def update_deliv_prog(sid, deliv_prog):
    global order_db, item_db, now, start
    print(f'Delivery progress received from scheduler: {deliv_prog}')
    order_db_stats = order_db.set_from_dict(deliv_prog)
    item_db_stats = item_db.set_from_dict(deliv_prog)
    db_stats = {**order_db_stats, **item_db_stats}
    time_lock.acquire
    walltime = (now - start).total_seconds()
    time_lock.release
    order_db.write_to_tensorboard(db_stats, walltime)
    item_db.write_to_tensorboard(db_stats, walltime)

class Timer:
    def __init__(self, clock, counterclock, turn):
        self.clock = clock
        self.counterclock = counterclock
        self.turn = turn
        self.loading = LOADING_TIME
        self.unloading = UNLOADING_TIME
        self.eps = 0.1

    def travel_time(self, orientation, from_, to):
        assert orientation in {'clock', 'counterclock'}
        time_dict = self.clock if orientation == 'clock' else self.counterclock
        return np.random.normal(time_dict[from_][to], self.eps)

    def turn_time(self, at):
        return np.random.normal(self.turn[at], self.eps)

    def loading_time(self):
        return np.random.normal(self.loading, self.eps)

    def unloading_time(self):
        return np.random.normal(self.unloading, self.eps)

    @classmethod
    def from_files(cls, clock_fpath, counterclock_fpath, turn_fpath):
        clock, counterclock, turn = read_time_files(clock_fpath, counterclock_fpath, turn_fpath)
        return cls(clock, counterclock, turn)


if __name__ == "__main__":
    clock_fpath = 'time_files/clock.csv'
    counterclock_fpath = 'time_files/counter_clock.csv'

    turn_fpath = 'time_files/turn.csv'

    timer = Timer.from_files(clock_fpath, counterclock_fpath, turn_fpath)
    robot = Robot()
    deliv_list = DeliveryList()
    writer = SummaryWriter(comment='simulated')
    order_db = DataBase('order', writer)
    item_db = DataBase('item', writer)

    eventlet.wsgi.server(eventlet.listen(('', 60000)), app, log_output=False)
