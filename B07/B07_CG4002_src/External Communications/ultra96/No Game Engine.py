import os
import sys
import json
import socket
import threading
import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import traceback

from queue import Queue

from GameState import GameState

# Global flags
SINGLE_PLAYER_MODE      = False
DEBUG_FLAG              = False

laptop_connections = Queue()

IMU_queue_player_one = Queue()
IMU_queue_player_two = Queue()
GUN_queue_player_one = Queue()
GUN_queue_player_two = Queue()
VEST_queue_player_one = Queue()
VEST_queue_player_two = Queue()
BLE_queue_player_one = Queue()
BLE_queue_player_two = Queue()

message_queue_to_eval_server = Queue()


class GameEngine(threading.Thread):
    def __init__ (self):
        super().__init__()

        self.game_state = GameState()

class RelayLaptopServer(threading.Thread):
    def __init__ (self, port_num, player_num):
        super().__init__()

        self.player_num = player_num
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_address = ('', port_num)
        print('[Relay Laptop Server ' + str(self.player_num) + '] starting up on port %s' % self.server_address[1])
        self.server_socket.bind(self.server_address)

        self.connection = None
        self.shutdown = threading.Event()


    def setup_connection(self):

        print('[Relay Laptop Server ' + str(self.player_num) + '] Waiting for a connection from Laptop ' + str(self.player_num))
        self.connection, client_address = self.server_socket.accept()
        print('--------------------------------------------------')
        print('[Relay Laptop Server ' + str(self.player_num) + '] Connected to Laptop ' + str(self.player_num) + ' at ' + str(client_address))
        print('--------------------------------------------------')

        laptop_connections.put(self.connection)

    def stop(self):
        try:
            self.connection.close()
            print('[Relay Laptop Server ' + str(self.player_num) + '] Connection closed for Laptop ' + str(self.player_num))
        except OSError:
            #connection already closed
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
                print('[Relay Laptop Server ' + str(self.player_num) + '] No more data from Laptop ' + str(self.player_num))
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
                print('[Relay Laptop Server ' + str(self.player_num) + '] No more data from the client')
                self.stop()

            sensor_data = data.decode("utf8")
            sensor_data = json.loads(sensor_data)

        except ConnectionResetError:
            print('[Relay Laptop Server ' + str(self.player_num) + '] Connection Reset')
            self.stop()

        return sensor_data



    def run(self):
        self.server_socket.listen(1)
        self.setup_connection()
        
        while not self.shutdown.is_set():
            try:
                sensor_data = self.recv_sensor_data()
                if sensor_data['data_type'] == "IMU":
                    if sensor_data['player_num'] == 1:
                        IMU_queue_player_one.put(sensor_data)
                        print(IMU_queue_player_one.get())
                    else:
                        IMU_queue_player_two.put(sensor_data)
                        print(IMU_queue_player_two.get())
                elif sensor_data['data_type'] == "GUN":
                    if sensor_data['player_num'] == 1:
                        GUN_queue_player_one.put(sensor_data)
                        print(GUN_queue_player_one.get())
                    else:
                        GUN_queue_player_two.put(sensor_data)
                        print(GUN_queue_player_two.get())
                elif sensor_data['data_type'] == "VEST":
                    if sensor_data['player_num'] == 1:
                        VEST_queue_player_one.put(sensor_data)
                        print(VEST_queue_player_one.get())
                    else:
                        VEST_queue_player_two.put(sensor_data)
                        print(VEST_queue_player_two.get())
                elif sensor_data['data_type'] == "BLE":
                    if sensor_data['player_num'] == 1:
                        BLE_queue_player_one.put(sensor_data)
                        print(BLE_queue_player_one.get())
                    else:
                        BLE_queue_player_two.put(sensor_data)
                        print(BLE_queue_player_two.get())

            except Exception as e:
                self.stop()
                traceback.print_exc()
                print('[Relay Laptop Server ' + str(self.player_num) + '] Error: ', e)


class EvalClient(threading.Thread):

    def __init__(self, eval_server_ip_address, eval_server_port_num, secret_key):
        super().__init__()

        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_address = (eval_server_ip_address, eval_server_port_num)
        self.secret_key = secret_key

        self.game_state = GameState()
        self.shutdown = threading.Event()

        try:
            self.client_socket.connect(self.server_address)
            print("[Eval Client] Connected to Eval Server: " + str(self.server_address[0]) + " on Port " + str(self.server_address[1]))

        except Exception as e:
            self.stop()
            traceback.print_exc()
            print("[Eval Client] Error: ", e)

    def encrypt_message(self, game_state_dict):
    
        secret_key = bytes(str(self.secret_key), encoding = "utf-8")
        plaintext = json.dumps(game_state_dict).encode("utf-8")
        plaintext = pad(plaintext, AES.block_size)
        cipher = AES.new(secret_key, AES.MODE_CBC)
        iv = cipher.iv
        encrypted_message = cipher.encrypt(plaintext)
        cipher_text = base64.b64encode(iv + encrypted_message)
        return cipher_text

    def stop(self):
        try:
            self.client_socket.close()
            print('[Eval Client] Connection to Eval Server closed')
        except OSError:
            #connection already closed
            pass
        self.shutdown.set()


    def send_game_state(self, action):
        success = True
        game_state_dict = self.game_state.get_dict()
        game_state_dict['p1']['action'] = str(action)
        print(game_state_dict)
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
        
        except ConnectionResetError:
            print('[Eval Client] Connection Reset')  
            self.stop()

        return updated_game_state

    def run(self):
        while not self.shutdown.is_set():
            try:
                action = input("[Eval Client] Input Action when ready to send to Eval Server: ")
                if action == 'done':
                    self.stop()
                    continue
                if not self.send_game_state(action):
                    self.stop()
                correct_game_state = self.receive_updated_game_state()
                print(correct_game_state)
            except Exception as e:
                self.stop()
                traceback.print_exc()
                print("[Eval Client] Error: ", e)

if __name__ == '__main__':

    _num_para = 7

    if len(sys.argv) != _num_para:
        print('Invalid number of arguments')
        print('python3 ' + os.path.basename(__file__) + ' [Mode] [Eval Server IP] [Eval Server Port] [Ultra96 Port 1] [Ultra96 Port 2] [Secret Key]')
        print('Mode             :  1 for 1-Player Game and 2 for 2-Player Game')
        print('Eval Server IP   :  IP Address of Evaluation Server')
        print('Eval Server Port :  Port Number of TCP Server on Evaluation Server')
        print('Ultra96 Port 1   :  Port Number of TCP Server for Laptop 1 on Ultra96')
        print('Ultra96 Port 2   :  Port Number of TCP Server for Laptop 2 on Ultra96')
        sys.exit()

    _num_players = int(sys.argv[1])

    if _num_players == 1:
        print("               SINGLE PLAYER MODE")
        SINGLE_PLAYER_MODE = True
    else:
        print("               DOUBLE PLAYER MODE")
        SINGLE_PLAYER_MODE = False


    _eval_server_ip_address = sys.argv[2]
    _eval_server_port_num = int(sys.argv[3])
    
    _ultra96_port_one = int(sys.argv[4])
    _ultra96_port_two = int(sys.argv[5])

    _secret_key = sys.argv[6]


    laptop_server_one = RelayLaptopServer(_ultra96_port_one, 1)
    laptop_server_two = RelayLaptopServer(_ultra96_port_two, 2)

    laptop_server_one.start()
    laptop_server_two.start()

    num_laptop_connections = 0
    while num_laptop_connections < _num_players:
        if not laptop_connections.empty():
            laptop_connections.get()
            num_laptop_connections += 1


    ready = input("Press Enter when ready to connect to Eval Server: ")

    eval_client = EvalClient(_eval_server_ip_address, _eval_server_port_num, _secret_key)
    eval_client.start()

    
    