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

# Global flags
SINGLE_PLAYER_MODE = False

laptop_connections = Queue()

IMU_queue_player_one = Queue()
IMU_queue_player_two = Queue()
VEST_queue_player_one = Queue()
VEST_queue_player_two = Queue()
BLE_queue_player_one = Queue()
BLE_queue_player_two = Queue()

action_queue_player_one = Queue()
action_queue_player_two = Queue()

game_state_queue_to_eval_server = Queue()
game_state_queue_from_eval_server = Queue()
game_state_queue_to_relay_laptop_one = Queue()
game_state_queue_to_relay_laptop_two = Queue()

game_state_ready = threading.Event()
update_from_eval_server = threading.Event()
update_relay_laptop_one = threading.Event()
update_relay_laptop_two = threading.Event()

global_shutdown = threading.Event()


class FPGA(threading.Thread):
    def __init__(self):
        super().__init__()

        self.shutdown = threading.Event()

    def run(self):
        while not global_shutdown.is_set():
            if not IMU_queue_player_one.empty():
                IMU_data = IMU_queue_player_one.get()
                if IMU_data == [1, 1, 1, 1, 1, 1]:
                    action_queue_player_one.put(Actions.shield)
                elif IMU_data == [2, 2, 2, 2, 2, 2]:
                    action_queue_player_one.put(Actions.grenade)
                elif IMU_data == [3, 3, 3, 3, 3, 3]:
                    action_queue_player_one.put(Actions.reload)
                elif IMU_data == [4, 4, 4, 4, 4, 4]:
                    action_queue_player_one.put(Actions.logout)
            if not IMU_queue_player_two.empty():
                IMU_data = IMU_queue_player_two.get()
                if IMU_data == [1, 1, 1, 1, 1, 1]:
                    action_queue_player_two.put(Actions.shield)
                elif IMU_data == [2, 2, 2, 2, 2, 2]:
                    action_queue_player_two.put(Actions.grenade)
                elif IMU_data == [3, 3, 3, 3, 3, 3]:
                    action_queue_player_two.put(Actions.reload)
                elif IMU_data == [4, 4, 4, 4, 4, 4]:
                    action_queue_player_two.put(Actions.logout)

        print('[FPGA] SHUTDOWN')


class GameEngine(threading.Thread):
    def __init__(self):
        super().__init__()

        self.game_state = GameState()
        self.player_1 = self.game_state.player_1
        self.player_2 = self.game_state.player_2
        self.player_1_action = Actions.no
        self.player_2_action = Actions.no

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

        game_state_queue_to_eval_server.put(self.game_state.get_dict())

        print('[Game Engine] Game State Committed')

        self.player_1_action = Actions.no
        self.player_2_action = Actions.no

        while not IMU_queue_player_one.empty():
            IMU_queue_player_one.get()
        while not IMU_queue_player_two.empty():
            IMU_queue_player_two.get()
        while not VEST_queue_player_one.empty():
            VEST_queue_player_one.get()
        while not VEST_queue_player_two.empty():
            VEST_queue_player_two.get()
        while not BLE_queue_player_one.empty():
            BLE_queue_player_one.get()
        while not BLE_queue_player_two.empty():
            BLE_queue_player_two.get()
        while not action_queue_player_one.empty():
            action_queue_player_one.get()
        while not action_queue_player_two.empty():
            action_queue_player_two.get()

        game_state_ready.set()

    def run(self):
        while not global_shutdown.is_set():

            if update_from_eval_server.is_set():
                print('[Game Engine] Updating Correct Game State')
                updated_game_state = game_state_queue_from_eval_server.get()
                self.player_1.initialize_from_dict(updated_game_state['p1'])
                self.player_2.initialize_from_dict(updated_game_state['p2'])

                print('[Game Engine] Updated Game State: ' +
                      str(self.game_state.get_dict()))

                while not game_state_queue_from_eval_server.empty():
                    game_state_queue_from_eval_server.get()

                update_from_eval_server.clear()

            if not game_state_ready.is_set():
                if SINGLE_PLAYER_MODE:
                    if self.player_1_action == Actions.no and not action_queue_player_one.empty():
                        self.player_1_action = action_queue_player_one.get()

                        if self.player_1_action == Actions.logout:
                            print("[GLOBAL] SHUTTING DOWN")
                            global_shutdown.set()

                        # no need resolve hit/miss, shoot and grenade always hit
                        pos_p1 = 1
                        pos_p2 = 1

                        self.commit_action(pos_p1, pos_p2)

                else:
                    if self.player_1_action == Actions.no and not action_queue_player_one.empty():  # only save first action?
                        self.player_1_action = action_queue_player_one.get()

                    if self.player_2_action == Actions.no and not action_queue_player_two.empty():
                        self.player_2_action = action_queue_player_two.get()

                    if self.player_1_action == Actions.logout and self.player_2_action == Actions.logout:
                        print("[GLOBAL] SHUTTING DOWN")
                        global_shutdown.set()

                    if self.player_1_action != Actions.no and self.player_2_action != Actions.no:
                        if self.player_1_action == Actions.shoot or self.player_1_action == Actions.grenade or self.player_2_action == Actions.shoot or self.player_2_action == Actions.grenade:
                            print('[Game Engine] Resolving HIT or MISS')
                            time.sleep(10)
                        pos_p1 = 1
                        pos_p2 = 4
                        if not VEST_queue_player_one.empty():  # check if VEST_queue empty after some delay? = 4 barrier
                            VEST_queue_player_one.get()
                            pos_p2 = 1
                        if not VEST_queue_player_two.empty():
                            VEST_queue_player_two.get()
                            pos_p2 = 1
                        self.commit_action(pos_p1, pos_p2)

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
            pass
        self.shutdown.set()
        global_shutdown.set()

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
        print("[Relay Laptop Server " + str(self.player_num) +
              "] Sending Game State: " + str(game_state_dict))

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

        while not self.shutdown.is_set():

            try:
                sensor_data = self.recv_sensor_data()
                print('[Relay Laptop Server ' + str(self.player_num) +
                      '] Sensor Data Received: ' + str(sensor_data))
                if sensor_data['data_type'] == "IMU":
                    if sensor_data['player_num'] == 1:
                        IMU_queue_player_one.put(sensor_data['data_value'])
                    else:
                        IMU_queue_player_two.put(sensor_data['data_value'])
                elif sensor_data['data_type'] == "GUN":
                    if sensor_data['player_num'] == 1:
                        action_queue_player_one.put(Actions.shoot)
                    else:
                        action_queue_player_two.put(Actions.shoot)
                elif sensor_data['data_type'] == "VEST":
                    if sensor_data['player_num'] == 1:
                        VEST_queue_player_one.put(sensor_data['data_value'])
                    else:
                        VEST_queue_player_two.put(sensor_data['data_value'])
                elif sensor_data['data_type'] == "BLE":
                    if sensor_data['player_num'] == 1:
                        BLE_queue_player_one.put(sensor_data['data_value'])
                    else:
                        BLE_queue_player_two.put(sensor_data['data_value'])
                else:
                    print('[Relay Laptop Server ' + str(self.player_num) +
                          '] Undefined Sensor Data Received: Please Send Again!')

                if self.player_num == 1:
                    if update_relay_laptop_one.is_set():
                        updated_game_state = game_state_queue_to_relay_laptop_one.get()
                        updated_game_state['updated'] = True

                        if not self.send_game_state(updated_game_state):
                            self.stop()

                        while not game_state_queue_to_relay_laptop_one.empty():
                            game_state_queue_to_relay_laptop_one.get()

                        update_relay_laptop_one.clear()
                    else:
                        updated_game_state = {'updated': False}
                        if not self.send_game_state(updated_game_state):
                            self.stop()

                if self.player_num == 2:
                    if update_relay_laptop_two.is_set():
                        updated_game_state = game_state_queue_to_relay_laptop_two.get()
                        updated_game_state['updated'] = True

                        if not self.send_game_state(updated_game_state):
                            self.stop()

                        while not game_state_queue_to_relay_laptop_two.empty():
                            game_state_queue_to_relay_laptop_two.get()

                        update_relay_laptop_two.clear()
                    else:
                        updated_game_state = {'updated': False}
                        if not self.send_game_state(updated_game_state):
                            self.stop()

            except Exception as e:
                self.stop()
                traceback.print_exc()
                print('[Relay Laptop Server ' +
                      str(self.player_num) + '] Error: ', e)

        print('[Relay Laptop Server ' + str(self.player_num) +
              '] SHUTDOWN')


class EvalClient(threading.Thread):

    def __init__(self, eval_server_ip_address, eval_server_port_num, secret_key):
        super().__init__()

        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_address = (eval_server_ip_address, eval_server_port_num)
        self.secret_key = secret_key

        self.shutdown = threading.Event()

        try:
            self.client_socket.connect(self.server_address)
            print("[Eval Client] Connected to Eval Server: " +
                  str(self.server_address[0]) + " on Port " + str(self.server_address[1]))

        except Exception as e:
            self.stop()
            traceback.print_exc()
            print("[Eval Client] Error: ", e)

    def encrypt_message(self, game_state_dict):

        secret_key = bytes(str(self.secret_key), encoding="utf-8")
        plaintext = json.dumps(game_state_dict).encode("utf-8")
        plaintext = pad(plaintext, AES.block_size)
        cipher = AES.new(secret_key, AES.MODE_CBC)
        iv = cipher.iv
        encrypted_message = cipher.encrypt(plaintext)
        cipher_text = base64.b64encode(iv + encrypted_message)
        return cipher_text

    def stop(self):
        try:
            self.client_socket.shutdown(SHUT_RDWR)
            self.client_socket.close()
            print('[Eval Client] Connection to Eval Server closed')
        except OSError:
            # connection already closed
            pass
        self.shutdown.set()
        global_shutdown.set()

    def send_game_state(self, game_state_dict):
        success = True
        print("[Eval Client] Sending Game State: " + str(game_state_dict))
        cipher_text = self.encrypt_message(game_state_dict)
        m = str(len(cipher_text)) + '_'
        try:
            self.client_socket.sendall(m.encode("utf-8"))
            self.client_socket.sendall(cipher_text)
        except Exception as e:
            success = False
            traceback.print_exc()
            print("[Eval Client] Error: ", e)
        return success

    def receive_updated_game_state(self):
        updated_game_state = None
        try:
            data = b''
            while not data.endswith(b'_'):
                _d = self.client_socket.recv(1)
                if not _d:
                    data = b''
                    break
                data += _d
            if len(data) == 0:
                print('[Eval Client] No more data from Evaluation Server')
                self.stop()

            data = data.decode("utf-8")
            length = int(data[:-1])

            data = b''
            while len(data) < length:
                _d = self.client_socket.recv(length - len(data))
                if not _d:
                    data = b''
                    break
                data += _d
            if len(data) == 0:
                print('[Eval Client] No more data from Evaluation Server')
                self.stop()

            updated_game_state = data.decode("utf-8")
            updated_game_state = json.loads(updated_game_state)

            game_state_queue_from_eval_server.put(updated_game_state)
            update_from_eval_server.set()

            game_state_queue_to_relay_laptop_one.put(updated_game_state)
            update_relay_laptop_one.set()

            if not SINGLE_PLAYER_MODE:
                game_state_queue_to_relay_laptop_two.put(updated_game_state)
                update_relay_laptop_two.set()

        except ConnectionResetError:
            print('[Eval Client] Connection Reset')
            self.stop()

        return updated_game_state

    def run(self):
        while not global_shutdown.is_set():
            try:
                print('[Eval Client] Waiting for Game State to be ready')
                game_state_ready.wait()

                print('[Eval Client] Game State Ready')
                game_state_dict = game_state_queue_to_eval_server.get()

                while not game_state_queue_to_eval_server.empty():
                    game_state_queue_to_eval_server.get()

                if not self.send_game_state(game_state_dict):
                    self.stop()

                updated_game_state = self.receive_updated_game_state()
                print('[Eval Client] Updated Game State Received: ' +
                      str(updated_game_state))

                game_state_ready.clear()

            except Exception as e:
                self.stop()
                traceback.print_exc()
                print("[Eval Client] Error: ", e)

        print('[Eval Client] SHUTDOWN')


if __name__ == '__main__':

    _num_para = [6, 7]

    if len(sys.argv) not in _num_para:
        print('Invalid number of arguments')
        print('python3 ' + os.path.basename(__file__) +
              ' [Mode] [Eval Server IP] [Eval Server Port] [Ultra96 Port 1] [Ultra96 Port 2] [Secret Key]')
        print('Mode             :  1 for 1-Player Game and 2 for 2-Player Game')
        print('Eval Server IP   :  IP Address of Evaluation Server')
        print('Eval Server Port :  Port Number of TCP Server on Evaluation Server')
        print('Ultra96 Port 1   :  Port Number of TCP Server for Laptop 1 on Ultra96')
        print('Ultra96 Port 2   :  Port Number of TCP Server for Laptop 2 on Ultra96 (provide even if SINGLE PLAYER MODE)')
        print('Secret key       :  Secret Key shared with Eval Server')
        sys.exit()

    _num_players = int(sys.argv[1])

    if _num_players == 1:
        print("SINGLE PLAYER MODE")
        SINGLE_PLAYER_MODE = True
    else:
        print("TWO PLAYER MODE")
        SINGLE_PLAYER_MODE = False

    _eval_server_ip_address = sys.argv[2]
    _eval_server_port_num = int(sys.argv[3])

    _ultra96_port_one = int(sys.argv[4])
    if not SINGLE_PLAYER_MODE:
        _ultra96_port_two = int(sys.argv[5])

    if SINGLE_PLAYER_MODE:
        _secret_key = sys.argv[5]
    else:
        _secret_key = sys.argv[6]

    laptop_server_one = RelayLaptopServer(_ultra96_port_one, 1)
    if not SINGLE_PLAYER_MODE:
        laptop_server_two = RelayLaptopServer(_ultra96_port_two, 2)

    laptop_server_one.start()
    if not SINGLE_PLAYER_MODE:
        laptop_server_two.start()

    num_laptop_connections = 0
    while num_laptop_connections < _num_players:
        if not laptop_connections.empty():
            laptop_connections.get()
            num_laptop_connections += 1

    fpga = FPGA()
    fpga.start()

    game_engine = GameEngine()
    game_engine.start()

    ready = input("Press Enter when ready to connect to Eval Server: ")

    eval_client = EvalClient(_eval_server_ip_address,
                             _eval_server_port_num, _secret_key)
    eval_client.start()
