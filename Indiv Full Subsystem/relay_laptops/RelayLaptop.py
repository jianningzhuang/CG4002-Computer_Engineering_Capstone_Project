import os
import sys
import json
import socket
import threading
import traceback
import sshtunnel
from _socket import SHUT_RDWR

from queue import Queue

sensor_data_queue_from_beetle = Queue()

game_state_queue_from_relay_laptop = Queue()

update_from_relay_laptop = threading.Event()


class RelayLaptopClient(threading.Thread):

    def __init__(self, stu_username, stu_password, ultra96_port_num, player_num):
        super().__init__()

        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ultra96_ip_address = '192.168.95.220'
        self.ultra96_port_num = ultra96_port_num
        self.server_address = (self.ultra96_ip_address, self.ultra96_port_num)
        self.stu_username = stu_username
        self.stu_password = stu_password
        self.player_num = player_num
        self.shutdown = threading.Event()

    def open_tunnel(self):

        tunnel_one = sshtunnel.open_tunnel(
            ssh_address_or_host=('stu.comp.nus.edu.sg', 22),
            remote_bind_address=(self.ultra96_ip_address, 22),
            ssh_username=self.stu_username,
            ssh_password=self.stu_password,
            # local_bind_address = ('localhost', 11111),
            block_on_close=False
        )

        tunnel_one.start()
        print('[sshtunnel 1] Tunnel onto STU: ' +
              str(tunnel_one.local_bind_address))

        tunnel_two = sshtunnel.open_tunnel(
            ssh_address_or_host=('localhost', tunnel_one.local_bind_port),
            remote_bind_address=('localhost', self.ultra96_port_num),
            ssh_username='xilinx',
            ssh_password='whoneedsvisualizer',
            # local_bind_address=('localhost', self.ultra96_port_num),
            block_on_close=False
        )

        tunnel_two.start()
        print('[sshtunnel 2] Tunnel onto Xilinx: ' +
              str(tunnel_two.local_bind_address))

        return tunnel_two.local_bind_address

    def send_sensor_data(self, action):
        success = True
        sensor_data_dict = dict()
        sensor_data_dict['player_num'] = self.player_num
        if action == 'shield':
            sensor_data_dict['data_type'] = 'IMU'
            sensor_data_dict['data_value'] = [1, 1, 1, 1, 1, 1]
        elif action == 'grenade':
            sensor_data_dict['data_type'] = 'IMU'
            sensor_data_dict['data_value'] = [2, 2, 2, 2, 2, 2]
        elif action == 'reload':
            sensor_data_dict['data_type'] = 'IMU'
            sensor_data_dict['data_value'] = [3, 3, 3, 3, 3, 3]
        elif action == 'logout':
            sensor_data_dict['data_type'] = 'IMU'
            sensor_data_dict['data_value'] = [4, 4, 4, 4, 4, 4]
        elif action == 'shoot':
            sensor_data_dict['data_type'] = 'GUN'
            sensor_data_dict['data_value'] = 1
        elif action == 'hit':
            sensor_data_dict['data_type'] = 'VEST'
            sensor_data_dict['data_value'] = 1
        elif action == 'disconnect':
            sensor_data_dict['data_type'] = 'BLE'
            sensor_data_dict['data_value'] = 0
        elif action == 'connect':
            sensor_data_dict['data_type'] = 'BLE'
            sensor_data_dict['data_value'] = 1
        else:
            sensor_data_dict['data_type'] = 'UNDEFINED'
            sensor_data_dict['data_value'] = 0
        sensor_data = json.dumps(sensor_data_dict).encode("utf-8")
        print(sensor_data)
        m = str(len(sensor_data)) + '_'
        try:
            self.client_socket.sendall(m.encode("utf-8"))
            self.client_socket.sendall(sensor_data)
        except Exception as e:
            success = False
            traceback.print_exc()
            print("[Relay Laptop Client] Error: ", e)
        return success

    # receive data from ultra96
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
                print('[Relay Laptop Client] No more data from Relay Laptop Server')
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
                print('[Relay Laptop Client] No more data from Relay Laptop Server')
                self.stop()

            updated_game_state = data.decode("utf-8")
            updated_game_state = json.loads(updated_game_state)

        except ConnectionResetError:
            print('[Relay Laptop Client] Connection Reset')
            self.stop()

        return updated_game_state

    def stop(self):
        try:
            self.client_socket.shutdown(SHUT_RDWR)
            self.client_socket.close()
            print('[Relay Laptop Client] Connection to Ultra96 Server closed')
        except OSError:
            # connection already closed
            pass
        self.shutdown.set()

    def run(self):
        tunnel_address = self.open_tunnel()
        # tunnel_address = ('localhost', self.ultra96_port_num)

        try:
            self.client_socket.connect(tunnel_address)
            print("[Relay Laptop Client] Connected to Ultra96 Server: " +
                  str(self.server_address[0]) + " on Port " + str(self.server_address[1]))
            print("[Relay Laptop Client] Tunnel Address: " +
                  str(tunnel_address[0]) + " on Port " + str(tunnel_address[1]))

        except Exception as e:
            self.stop()
            traceback.print_exc()
            print("[Relay Laptop Client] Error: ", e)

        while not self.shutdown.is_set():
            try:
                action = input(
                    "[Relay Laptop Client] Input Action when ready to send to Ultra96 Server: ")
                if action == 'done':
                    self.stop()
                    continue
                if not self.send_sensor_data(action):
                    self.stop()
                # receive updated game state
                updated_game_state = self.receive_updated_game_state()
                print('[Relay Laptop Client] Updated Game State Received: ' +
                      str(updated_game_state))
                if updated_game_state['updated'] == True:
                    game_state_queue_from_relay_laptop.put(updated_game_state)
                    update_from_relay_laptop.set()

            except Exception as e:
                self.stop()
                traceback.print_exc()
                print("[Relay Laptop Client] Error: ", e)


if __name__ == '__main__':

    _num_para = 5

    if len(sys.argv) != _num_para:
        print('Invalid number of arguments')
        print('python3 ' + os.path.basename(__file__) +
              ' [STU Username] [STU Password] [Ultra96 Port Number] [Player Number]')
        print('STU Username         :  STU Username eXXXXXXX')
        print('STU Password         :  STU Password')
        print('Ultra96 Port Number  :  Port Number of TCP Server on Ultra96')
        print('Player Number        :  Player Number 1 or 2')

        sys.exit()

    _stu_username = sys.argv[1]
    _stu_password = sys.argv[2]

    _ultra96_port_num = int(sys.argv[3])
    _player_num = int(sys.argv[4])

    relay_laptop_client = RelayLaptopClient(
        _stu_username, _stu_password, _ultra96_port_num, _player_num)
    relay_laptop_client.start()
