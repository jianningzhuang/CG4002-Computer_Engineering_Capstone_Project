import os
import sys
import json
import time
import socket
import threading
import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import traceback
from _socket import SHUT_RDWR

from queue import Queue

from Helper import Actions
from GameState import GameState

import joblib

from mlp import *
import numpy as np

# Global flags

laptop_connections = Queue()

IMU_queue_player_one = Queue()
IMU_queue_player_two = Queue()
VEST_queue_player_one = Queue()
VEST_queue_player_two = Queue()

action_queue_player_one = Queue()
action_queue_player_two = Queue()

game_state_queue_to_relay_laptop_one = Queue()
game_state_queue_to_relay_laptop_two = Queue()

global_shutdown = threading.Event()


class FPGA(threading.Thread):
    def __init__(self):
        super().__init__()

        ol, dma = init()
        self.ol = ol
        self.dma = dma
        self.scaler = joblib.load("scaler.save")

        self.labels = [Actions.grenade, Actions.no,
                       Actions.logout, Actions.reload, Actions.shield]

        self.p1_data = []
        self.p2_data = []

        self.frame_size = 150
        self.threshold = 20

        self.p1_difference = 0
        self.p1_prev = None
        self.p1_start_of_move = False

        self.p2_difference = 0
        self.p2_prev = None
        self.p2_start_of_move = False

        self.shutdown = threading.Event()

    def run(self):
        while not global_shutdown.is_set():
            try:
                if not IMU_queue_player_one.empty():
                    IMU_data = IMU_queue_player_one.get()
                    if self.p1_start_of_move == True:
                        if IMU_data[0] != 200:
                            if self.p1_prev == None:
                                fill_start_time = time.time()
                                print(
                                    "[FPGA] Player 1 Start to fill up frame: ", fill_start_time)
                                self.p1_prev = IMU_data[2]
                            else:
                                self.p1_difference += abs(
                                    IMU_data[2] - self.p1_prev)
                                self.p1_prev = IMU_data[2]
                            self.p1_data.extend(IMU_data)
                            if len(self.p1_data) == self.frame_size:
                                full_frame_time = time.time()
                                print(
                                    "[FPGA] Player 1 Fill up to action size: ", full_frame_time)
                                # df = pd.DataFrame([self.p1_data])
                                # df.to_csv(str(time.time()) + '.csv')
                                if self.p1_difference > self.threshold:
                                    action_data = np.asarray(
                                        self.p1_data, dtype=np.float32)
                                    action_data = self.scaler.transform(
                                        np.array(action_data).reshape(1, -1))
                                    time_np = time.time()
                                    print(
                                        "[FPGA] Player 1 Converted to np array: ", time_np)
                                    predicted_action = self.labels[np.argmax(
                                        predict(action_data, self.ol, self.dma))]
                                    print(
                                        '[FPGA] Player 1 Predicted: ' + predicted_action)
                                    predict_time = time.time()
                                    print(
                                        "[FPGA] Player 1 Time to predict: ", predict_time)
                                    if predicted_action != Actions.no:
                                        action_queue_player_one.put(
                                            predicted_action)
                                self.p1_data = []
                                self.p1_difference = 0
                                self.p1_prev = None
                                self.p1_start_of_move = False
                    else:
                        if IMU_data[0] == 200:
                            self.p1_start_of_move = True

                if not IMU_queue_player_two.empty():
                    IMU_data = IMU_queue_player_two.get()
                    if self.p2_start_of_move == True:
                        if IMU_data[0] != 200:
                            if self.p2_prev == None:
                                fill_start_time = time.time()
                                print(
                                    "[FPGA] Player 2 Start to fill up frame: ", fill_start_time)
                                self.p2_prev = IMU_data[2]
                            else:
                                self.p2_difference += abs(
                                    IMU_data[2] - self.p2_prev)
                                self.p2_prev = IMU_data[2]
                            self.p2_data.extend(IMU_data)
                            if len(self.p2_data) == self.frame_size:
                                full_frame_time = time.time()
                                print(
                                    "[FPGA] Player 2 Fill up to action size: ", full_frame_time)
                                # df = pd.DataFrame([self.p2_data])
                                # df.to_csv(str(time.time()) + '.csv')
                                if self.p2_difference > self.threshold:
                                    action_data = np.asarray(
                                        self.p2_data, dtype=np.float32)
                                    action_data = self.scaler.transform(
                                        np.array(action_data).reshape(1, -1))
                                    time_np = time.time()
                                    print(
                                        "[FPGA] Player 2 Converted to np array: ", time_np)
                                    predicted_action = self.labels[np.argmax(
                                        predict(action_data, self.ol, self.dma))]
                                    print(
                                        '[FPGA] Player 2 Predicted: ' + predicted_action)
                                    predict_time = time.time()
                                    print(
                                        "[FPGA] Player 2 Time to predict: ", predict_time)
                                    if predicted_action != Actions.no:
                                        action_queue_player_two.put(
                                            predicted_action)
                                self.p2_data = []
                                self.p2_difference = 0
                                self.p2_prev = None
                                self.p2_start_of_move = False

                    else:
                        if IMU_data[0] == 200:
                            self.p2_start_of_move = True

            except Exception as e:
                self.shutdown.set()
                traceback.print_exc()
                print("[FPGA] Error: ", e)

        print('[FPGA] SHUTDOWN')


class GameEngine(threading.Thread):
    def __init__(self):
        super().__init__()

        self.game_state = GameState()
        self.player_1 = self.game_state.player_1
        self.player_2 = self.game_state.player_2
        self.player_1_action = Actions.no
        self.player_2_action = Actions.no
        self.hit_timeout = 0.5
        self.hit_timer = None
        self.shutdown = threading.Event()

    def commit_action(self, pos_p1, pos_p2):

        action_p1_is_valid = self.player_1.action_is_valid(
            self.player_1_action)
        action_p2_is_valid = self.player_2.action_is_valid(
            self.player_2_action)

        self.player_1.update(pos_p1, pos_p2, self.player_1_action,
                             self.player_2_action, action_p2_is_valid)
        self.player_2.update(pos_p2, pos_p1, self.player_2_action,
                             self.player_1_action, action_p1_is_valid)

        game_state_queue_to_relay_laptop_one.put(self.game_state.get_dict())

        game_state_queue_to_relay_laptop_two.put(self.game_state.get_dict())

        print('[Game Engine] Player 1: ' + self.player_1_action)
        print('[Game Engine] Player 2: ' + self.player_2_action)
        print('[Game Engine] Game State Committed')

        self.player_1_action = Actions.no
        self.player_2_action = Actions.no

    def stop_timer(self):
        self.hit_timer = None
        print('[Game Engine] MISS: Player Behind Barrier')

    def run(self):
        while not (global_shutdown.is_set() or self.shutdown.is_set()):
            try:
                if self.player_1_action == Actions.no and not action_queue_player_one.empty():
                    self.player_1_action = action_queue_player_one.get()

                    pos_p1 = 1
                    pos_p2 = 1
                    if self.player_1_action == Actions.shoot:
                        pos_p2 = 4
                        print('[Game Engine] Resolving HIT or MISS')
                        self.hit_timer = threading.Timer(
                            self.hit_timeout, self.stop_timer)
                        self.hit_timer.start()

                        while self.hit_timer:
                            if not VEST_queue_player_two.empty():
                                VEST_queue_player_two.get()
                                pos_p2 = 1
                                print(
                                    '[Game Engine] HIT: Players in Line of Sight')
                                if self.hit_timer:
                                    self.hit_timer.cancel()
                                    self.hit_timer = None
                    self.commit_action(pos_p1, pos_p2)

                if self.player_2_action == Actions.no and not action_queue_player_two.empty():
                    self.player_2_action = action_queue_player_two.get()

                    pos_p1 = 1
                    pos_p2 = 1
                    if self.player_2_action == Actions.shoot:
                        pos_p2 = 4
                        print('[Game Engine] Resolving HIT or MISS')
                        self.hit_timer = threading.Timer(
                            self.hit_timeout, self.stop_timer)
                        self.hit_timer.start()

                        while self.hit_timer:
                            if not VEST_queue_player_one.empty():
                                VEST_queue_player_one.get()
                                pos_p2 = 1
                                print(
                                    '[Game Engine] HIT: Players in Line of Sight')
                                if self.hit_timer:
                                    self.hit_timer.cancel()
                                    self.hit_timer = None
                    self.commit_action(pos_p1, pos_p2)

            except Exception as e:
                self.shutdown.set()
                traceback.print_exc()
                print("[Game Engine] Error: ", e)

        print('[Game Engine] SHUTDOWN')


class RelayLaptopServer(threading.Thread):
    def __init__(self, port_num, player_num):
        super().__init__()

        self.player_num = player_num
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_address = ('', port_num)
        print('[Relay Laptop Server ' + str(self.player_num) +
              '] starting up on port %s' % self.server_address[1])
        self.server_socket.bind(self.server_address)

        self.connection = None
        self.shutdown = threading.Event()

    def setup_connection(self):

        print('[Relay Laptop Server ' + str(self.player_num) +
              '] Waiting for a connection from Laptop ' + str(self.player_num))
        self.connection, client_address = self.server_socket.accept()
        print('--------------------------------------------------')
        print('[Relay Laptop Server ' + str(self.player_num) + '] Connected to Laptop ' +
              str(self.player_num) + ' at ' + str(client_address))
        print('--------------------------------------------------')

        laptop_connections.put(self.connection)

    def stop(self):
        try:
            self.connection.shutdown(SHUT_RDWR)
            self.connection.close()
            print('[Relay Laptop Server ' + str(self.player_num) +
                  '] Connection closed for Laptop ' + str(self.player_num))
        except OSError:
            # connection already closed
            print('[Relay Laptop Server ' + str(self.player_num) +
                  '] Connection already closed for Laptop ' + str(self.player_num))
            pass
        self.shutdown.set()

    def recv_sensor_data(self):
        sensor_data = None
        try:
            # recv length followed by '_' followed by sensor data
            data = b''
            while not data.endswith(b'_'):
                _d = self.connection.recv(1)
                if not _d:
                    data = b''
                    break
                data += _d
            if len(data) == 0:
                print('[Relay Laptop Server ' + str(self.player_num) +
                      '] No more data from Laptop ' + str(self.player_num))
                self.stop()

            data = data.decode("utf-8")
            length = int(data[:-1])

            data = b''
            while len(data) < length:
                _d = self.connection.recv(length - len(data))
                if not _d:
                    data = b''
                    break
                data += _d
            if len(data) == 0:
                print('[Relay Laptop Server ' + str(self.player_num) +
                      '] No more data from the client')
                self.stop()

            sensor_data = data.decode("utf8")
            sensor_data = json.loads(sensor_data)

        except ConnectionResetError:
            print('[Relay Laptop Server ' +
                  str(self.player_num) + '] Connection Reset')
            self.stop()

        return sensor_data

    def send_game_state(self, game_state_dict):
        success = True
        # print("[Relay Laptop Server " + str(self.player_num) +
        #      "] Sending Game State: " + str(game_state_dict))

        updated_game_state = json.dumps(game_state_dict)
        m = str(len(updated_game_state)) + '_'
        try:
            self.connection.sendall(m.encode("utf-8"))
            self.connection.sendall(updated_game_state.encode("utf-8"))
        except Exception as e:
            success = False
            traceback.print_exc()
            print('[Relay Laptop Server ' +
                  str(self.player_num) + '] Error: ', e)
        return success

    def run(self):
        self.server_socket.listen(1)
        self.setup_connection()

        while not (global_shutdown.is_set() or self.shutdown.is_set()):

            try:
                sensor_data = self.recv_sensor_data()
                # print('[Relay Laptop Server ' + str(self.player_num) +
                #      '] Sensor Data Received: ' + str(sensor_data))

                if sensor_data['data_type'] == "IMU":
                    if sensor_data['player_num'] == 1:
                        IMU_queue_player_one.put(sensor_data['data_value'])
                    else:
                        IMU_queue_player_two.put(sensor_data['data_value'])
                elif sensor_data['data_type'] == "GUN":
                    shoot_receive_time = time.time()
                    if sensor_data['player_num'] == 1:
                        print("Player 1 Shoot Received: ", shoot_receive_time)
                        action_queue_player_one.put(Actions.shoot)
                    else:
                        print("Player 2 Shoot Received: ", shoot_receive_time)
                        action_queue_player_two.put(Actions.shoot)
                elif sensor_data['data_type'] == "VEST":
                    hit_receive_time = time.time()
                    if sensor_data['player_num'] == 1:
                        print("Player 1 Hit Received: ", hit_receive_time)
                        VEST_queue_player_one.put(sensor_data['data_value'])
                    else:
                        print("Player 2 Hit Received: ", hit_receive_time)
                        VEST_queue_player_two.put(sensor_data['data_value'])
                elif sensor_data['data_type'] == "TIMEOUT":
                    pass
                else:
                    print('[Relay Laptop Server ' + str(self.player_num) +
                          '] Undefined Sensor Data Received: Please Send Again!')

                if self.player_num == 1:
                    if not game_state_queue_to_relay_laptop_one.empty():
                        # maybe need to while get?
                        updated_game_state = game_state_queue_to_relay_laptop_one.get()

                        if not self.send_game_state(updated_game_state):
                            self.stop()

                        # if type(updated_game_state['p1']) is dict:
                        #    if updated_game_state['p1']['action'] == Actions.logout:
                        #        self.shutdown.set()

                if self.player_num == 2:
                    if not game_state_queue_to_relay_laptop_two.empty():
                        # maybe need to while get?
                        updated_game_state = game_state_queue_to_relay_laptop_two.get()

                        if not self.send_game_state(updated_game_state):
                            self.stop()

                        # if type(updated_game_state['p1']) is dict:
                        #    if updated_game_state['p1']['action'] == Actions.logout:
                        #        self.shutdown.set()

            except Exception as e:
                self.stop()
                traceback.print_exc()
                print('[Relay Laptop Server ' +
                      str(self.player_num) + '] Error: ', e)

        print('[Relay Laptop Server ' + str(self.player_num) +
              '] SHUTDOWN')
        self.stop()


if __name__ == '__main__':

    _num_para = 3

    if len(sys.argv) != _num_para:
        print('Invalid number of arguments')
        print('python3 ' + os.path.basename(__file__) +
              ' [Ultra96 Port 1] [Ultra96 Port 2]')
        print('Ultra96 Port 1   :  Port Number of TCP Server for Laptop 1 on Ultra96')
        print('Ultra96 Port 2   :  Port Number of TCP Server for Laptop 2 on Ultra96')
        sys.exit()

    _ultra96_port_one = int(sys.argv[1])
    _ultra96_port_two = int(sys.argv[2])

    laptop_server_one = RelayLaptopServer(_ultra96_port_one, 1)
    laptop_server_two = RelayLaptopServer(_ultra96_port_two, 2)

    laptop_server_one.start()
    laptop_server_two.start()

    num_laptop_connections = 0
    while num_laptop_connections < 2:
        if not laptop_connections.empty():
            laptop_connections.get()
            num_laptop_connections += 1

    fpga = FPGA()
    fpga.start()

    game_engine = GameEngine()
    game_engine.start()

    try:
        laptop_server_one.join()
        laptop_server_two.join()
        game_engine.join()
        global_shutdown.set()
        print("[GLOBAL] Shutting Down")
        fpga.join()
    except (Exception, KeyboardInterrupt) as e:
        global_shutdown.set()
        traceback.print_exc()
        print("[GLOBAL] Shutting Down")
