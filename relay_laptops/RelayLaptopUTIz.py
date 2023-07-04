import os
import queue
import sys
import json
import socket
import threading
import traceback
import sshtunnel
from _socket import SHUT_RDWR

import struct
from crccheck.crc import Crc8
from bluepy.btle import DefaultDelegate, Peripheral, BTLEDisconnectError
import time

from queue import Queue

SINGLE_PLAYER_MODE = False

PLAYER = None

SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"

P1_BTL_GUN = "D0:39:72:BF:C1:E4"
P1_BTL_VEST = "D0:39:72:BF:CD:17"  # RED VEST
P1_BTL_IMU = "D0:39:72:BF:BF:A4"

P2_BTL_GUN = "D0:39:72:BF:BF:CE"
P2_BTL_VEST = "D0:39:72:BF:C1:D9"  # BLUE VEST
P2_BTL_IMU = "D0:39:72:BF:CA:94"

BTL_ADDRLIST = []
BTL_TYPE = {}
BTL_RESET_STATUS = {}
BTL_HANDSHAKE_STATUS = {}
ACK_HANDSHAKE_SENT_flag = {}
ACK_IR_SENT_flag = {}
sequence_number = {}
prev_sequence_number = {}
COUNT_GOOD_PKT = {}
COUNT_FRAG_PKT = {}
COUNT_DROPPED_PKT = {}

sensor_data_queue_from_beetle = Queue()

game_state_queue_to_beetle = Queue()

global_shutdown = threading.Event()


class NotificationDelegate(DefaultDelegate):
    # Initialises delegate object and message buffer for each Beetle
    def __init__(self, mac_address):
        DefaultDelegate.__init__(self)
        self.macAddress = mac_address
        self.buffer = b''  # specifies string as byte literal
        ACK_HANDSHAKE_SENT_flag[self.macAddress] = False
        ACK_IR_SENT_flag[self.macAddress] = False
        self.sequence_num = 0

        # IMU DATA COLLECTION
        # self.code_has_been_executed = False
        # self.start_time = 0
        # self.flag = False

    def handleNotification(self, cHandle, raw_packet):

        # print("pkt:", raw_packet)
        self.buffer += raw_packet

        # clear MPU initialising printing
        if b'>.' or b'..' in self.buffer:
            self.buffer = self.buffer.replace(b'>.', b'')
            self.buffer = self.buffer.replace(b'..', b'')

        # IMU DATA COLLECTION
        # if raw_packet[0] == 77:
        #     # execute only once
        #     if not self.code_has_been_executed:
        #         start_time = time.time()
        #         while time.time() - start_time < 3:
        #             pass
        #         print("EXECUTE ACTION IN 5s!")
        #         start_time1 = time.time()
        #         while time.time() - start_time1 < 5:
        #             pass
        #         print("NOW!")
        #         self.start_time = time.perf_counter()
        #         self.code_has_been_executed = True
        #
        #     elapsed_time = time.perf_counter() - self.start_time
        #     if elapsed_time >= 3 and self.flag == False:
        #         print("3s ACTION WINDOW ENDED")
        #         self.flag = True

        if len(self.buffer) < 20:
            COUNT_FRAG_PKT[self.macAddress] += 1
            # print('PKT FRAGMENTED:', COUNT_FRAG_PKT)

        else:
            # send non-fragmented (full) packet for processing
            # print(self.buffer)
            self.manage_packet_data(self.buffer)
            # clear buffer to prepare for next packet
            self.buffer = self.buffer[20:]

    def crcCheck(self, full_packet):
        checksum = Crc8.calc(full_packet[0:19])
        if checksum == full_packet[19]:
            return True
        return False

    def manage_packet_data(self, full_packet):
        # print(full_packet)

        # check for packet corruption
        if not self.crcCheck(full_packet):
            # drop corrupted packet
            COUNT_DROPPED_PKT[self.macAddress] += 1
            # print('PKT checksum failed, dropped!:', COUNT_DROPPED_PKT)
            return
        try:
            # packet type is 'A': BTL sends ACK to laptop
            if full_packet[0] == 65:
                BTL_HANDSHAKE_STATUS[self.macAddress] = True
                ACK_HANDSHAKE_SENT_flag[self.macAddress] = True
                message = [BTL_TYPE[self.macAddress] +
                           str(PLAYER), "BTL->LAPTOP ACK received"]
                print(message)

            # packet is NOT ACK from BTL ie. handshake done, ready for data
            elif BTL_HANDSHAKE_STATUS[self.macAddress]:

                # packet type is 'G' for gunshot (IR transmitted) or 'V' for vest (IR received)
                if full_packet[0] == 71 or full_packet[0] == 86:
                    self.process_IR_data(full_packet)

                # packet type is 'M' for motion: MPU data
                elif full_packet[0] == 77:
                    self.process_motion_data(full_packet)

                else:
                    COUNT_DROPPED_PKT[self.macAddress] += 1
                    print('DROPPED PKTS:', COUNT_DROPPED_PKT)

            else:  # reset BTL if packet is neither ACK nor sensor data, corrupted
                COUNT_DROPPED_PKT[self.macAddress] += 1
                print('DROPPED PKTS:', COUNT_DROPPED_PKT)
                BTL_RESET_STATUS[self.macAddress] = True

        except Exception as e:
            print("manage_packet_data exception: ", e)

    def process_IR_data(self, full_packet):
        try:
            packetFormat = '!c' + 19 * 'B'
            opened_packet = struct.unpack(packetFormat, full_packet)
            if opened_packet[1] == self.sequence_num:
                COUNT_DROPPED_PKT[self.macAddress] += 1
                return
            self.sequence_num = opened_packet[1]
            sequence_number[self.macAddress] = self.sequence_num
            ACK_IR_SENT_flag[self.macAddress] = True
            COUNT_GOOD_PKT[self.macAddress] += 1

            # push sensor data dict onto sensor_data_queue
            if full_packet[0] == 71:  # GUN
                # only send P1 GUN data to queue
                if not (SINGLE_PLAYER_MODE == True and PLAYER == 2):
                    gun_data_dict = dict()
                    gun_data_dict['player_num'] = PLAYER
                    gun_data_dict['data_type'] = 'GUN'
                    gun_data_dict['data_value'] = 1
                    sensor_data_queue_from_beetle.put(gun_data_dict)
                    print(gun_data_dict)

            if full_packet[0] == 86:  # VEST
                # only send P1 VEST data to queue
                if not (SINGLE_PLAYER_MODE == True and PLAYER == 2):
                    vest_data_dict = dict()
                    vest_data_dict['player_num'] = PLAYER
                    vest_data_dict['data_type'] = 'VEST'
                    vest_data_dict['data_value'] = 1
                    sensor_data_queue_from_beetle.put(vest_data_dict)
                    print(vest_data_dict)

        except Exception as e:
            print("process_IR_data exception: ", e)

    def process_motion_data(self, full_packet):
        try:
            packetFormat = '!c' + (3) * 'h' + 13 * 'b'
            opened_packet = struct.unpack(packetFormat, full_packet)
            packet_list = list(opened_packet)
            float_y = float(packet_list[1]) / 100
            float_p = float(packet_list[2]) / 100
            float_r = float(packet_list[3]) / 100
            COUNT_GOOD_PKT[self.macAddress] += 1

            # IMU DATA COLLECTION
            # t = time.localtime()
            # print(time.strftime("%H:%M:%S", t), float_y, ',', float_p, ',', float_r)

            # push sensor data dict onto sensor_data_queue
            # only send P1 MOTION data to queue
            if not (SINGLE_PLAYER_MODE == True and PLAYER == 2):
                motion_data_dict = dict()
                motion_data_dict['player_num'] = PLAYER
                motion_data_dict['data_type'] = 'IMU'
                motion_data_dict['data_value'] = [float_y, float_p, float_r]
                sensor_data_queue_from_beetle.put(motion_data_dict)
                print(motion_data_dict)

        except Exception as e:
            print("process_motion_data exception: ", e)


class BeetleThread(threading.Thread):
    def __init__(self, peripheral_obj_beetle):
        super().__init__()

        self.peripheral_obj_beetle = peripheral_obj_beetle
        self.serial_service = self.peripheral_obj_beetle.getServiceByUUID(
            SERVICE_UUID)
        self.serial_chars = self.serial_service.getCharacteristics()[0]
        self.initiate_handshake()

    def connect(self):
        BTL_HANDSHAKE_STATUS[self.peripheral_obj_beetle.addr] = False
        print(BTL_TYPE[self.peripheral_obj_beetle.addr] +
              str(PLAYER), 'attempting connection...')
        try:
            self.peripheral_obj_beetle.disconnect()
            self.peripheral_obj_beetle.connect(self.peripheral_obj_beetle.addr)
            self.peripheral_obj_beetle.withDelegate(
                NotificationDelegate(self.peripheral_obj_beetle.addr))
            print('connection successful to:', self.peripheral_obj_beetle.addr)
        except Exception:
            print('connection unsuccessful to:',
                  self.peripheral_obj_beetle.addr)
            self.connect()

    def reset(self):
        padding = (0,) * 19
        packetFormat = 'c' + 19 * 'B'  # 1 char & 19 unsigned char
        resetByte = bytes('R', 'utf-8')
        packet = struct.pack(packetFormat, resetByte, *padding)
        self.serial_chars.write(packet, withResponse=False)
        BTL_RESET_STATUS[self.peripheral_obj_beetle.addr] = False
        self.connect()

    def initiate_handshake(self):
        timeout_count = 0
        try:
            while not BTL_HANDSHAKE_STATUS[self.peripheral_obj_beetle.addr]:
                # send handshake packet to BTL

                message = [BTL_TYPE[self.peripheral_obj_beetle.addr] +
                           str(PLAYER), 'LAPTOP->BTL H sent']
                print(message)
                padding = (0,) * 19
                packetFormat = 'c' + 19 * 'B'  # 1 char & 19 unsigned char
                handshakeByte = bytes('H', 'utf-8')
                packet1 = struct.pack(packetFormat, handshakeByte, *padding)
                timeout_count += 1
                self.serial_chars.write(packet1, withResponse=False)
                print("H #{} sent to".format(timeout_count),
                      BTL_TYPE[self.peripheral_obj_beetle.addr] + str(PLAYER))

                if timeout_count % 10 == 0:
                    print("10 H sent, TIMEOUT & resetting",
                          BTL_TYPE[self.peripheral_obj_beetle.addr] + str(PLAYER))
                    timeout_count = 0
                    # reconnect BTL
                    self.reset()

                # if ACK packet received from BTL, return ACK packet to BTL
                if self.peripheral_obj_beetle.waitForNotifications(3.0):
                    padding = (0,) * 19
                    packetFormat = 'c' + 19 * 'B'
                    ackByte = bytes('A', 'utf-8')
                    packet2 = struct.pack(packetFormat, ackByte, *padding)
                    if ACK_HANDSHAKE_SENT_flag[self.peripheral_obj_beetle.addr]:
                        self.serial_chars.write(packet2, withResponse=False)
            return True
        except BTLEDisconnectError:
            print("handshake exception")
            self.connect()
            self.initiate_handshake()

    def run(self):
        try:
            while True:
                if BTL_RESET_STATUS[self.peripheral_obj_beetle.addr]:
                    break

                if self.peripheral_obj_beetle.waitForNotifications(2.0):

                    if ACK_IR_SENT_flag[self.peripheral_obj_beetle.addr]:

                        if game_state_queue_to_beetle.empty():  # ACK packet to reply to GUN or VEST packet
                            padding = (0,) * 19
                            packetFormat = 'c' + 19 * 'B'
                            ackByte = bytes('A', 'utf-8')
                            packet3 = struct.pack(
                                packetFormat, ackByte, *padding)
                            self.serial_chars.write(
                                packet3, withResponse=False)
                            ACK_IR_SENT_flag[self.peripheral_obj_beetle.addr] = False

                        else:  # send updated game state to GUN or VEST inside
                            # ACK packet
                            updated_game_state = game_state_queue_to_beetle.get()
                            p1_hp = updated_game_state["p1"]["hp"]
                            p1_bullets = updated_game_state["p1"]["bullets"]
                            p1_shield_time = updated_game_state["p1"]["shield_time"]
                            p1_shield_health = updated_game_state["p1"]["shield_health"]

                            padding = (0,) * 15
                            packetFormat = 'c' + + 4 * 'i' + 16 * 'B'
                            statusByte = bytes('A', 'utf-8')
                            packet4 = struct.pack(
                                packetFormat, statusByte, p1_hp, p1_bullets, p1_shield_time, p1_shield_health, *padding)
                            self.serial_chars.write(
                                packet4, withResponse=False)
                            ACK_IR_SENT_flag[self.peripheral_obj_beetle.addr] = False

                # FULL SUBSYSTEM TEST FUNCTION
                # total_sum = COUNT_GOOD_PKT[self.peripheral_obj_beetle.addr] + COUNT_DROPPED_PKT[
                #     self.peripheral_obj_beetle.addr] + COUNT_FRAG_PKT[self.peripheral_obj_beetle.addr]
                # t = time.localtime()
                # print(time.strftime("%H:%M:%S", t), BTL_TYPE[self.peripheral_obj_beetle.addr] + PLAYER, "[TOTAL:",
                #       total_sum, "|", "GOOD:", COUNT_GOOD_PKT[self.peripheral_obj_beetle.addr], "|", "DROPPED:",
                #       COUNT_DROPPED_PKT[self.peripheral_obj_beetle.addr], "|", "FRAG:",
                #       COUNT_FRAG_PKT[self.peripheral_obj_beetle.addr], "]")#, end="")

                # time.sleep(5)

            self.connect()
            self.initiate_handshake()
            self.run()

        except Exception as e:
            print(e, ":", self.peripheral_obj_beetle.addr)
            self.connect()
            self.initiate_handshake()
            self.run()


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
        self.tunnel_address = self.open_tunnel()
        # self.tunnel_address = ('localhost', self.ultra96_port_num)
        self.shutdown = threading.Event()

        try:
            self.client_socket.connect(self.tunnel_address)
            print("[Relay Laptop Client] Connected to Ultra96 Server: " +
                  str(self.server_address[0]) + " on Port " + str(self.server_address[1]))
            print("[Relay Laptop Client] Tunnel Address: " +
                  str(self.tunnel_address[0]) + " on Port " + str(self.tunnel_address[1]))

        except Exception as e:
            self.stop()
            traceback.print_exc()
            print("[Relay Laptop Client] Error: ", e)

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

    def send_sensor_data(self, sensor_data_dict):
        success = True
        sensor_data = json.dumps(sensor_data_dict).encode("utf-8")
        print('[Relay Laptop Client] Sending Sensor Data: ' + str(sensor_data))
        m = str(len(sensor_data)) + '_'
        try:
            self.client_socket.sendall(m.encode("utf-8"))
            self.client_socket.sendall(sensor_data)
        except Exception as e:
            success = False
            traceback.print_exc()
            print("[Relay Laptop Client] Error: ", e)
        return success

    def receive_updated_game_state(self):
        while not (global_shutdown.is_set() or self.shutdown.is_set()):
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
                    print(
                        '[Relay Laptop Client] No more data from Relay Laptop Server')
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
                    print(
                        '[Relay Laptop Client] No more data from Relay Laptop Server')
                    self.stop()

                updated_game_state = data.decode("utf-8")
                updated_game_state = json.loads(updated_game_state)

                print('[Relay Laptop Client] Updated Game State Received: ' +
                      str(updated_game_state))

                game_state_queue_to_beetle.put(updated_game_state)

            except ConnectionResetError:
                print('[Relay Laptop Client] Connection Reset')
                self.stop()

    def stop(self):
        try:
            self.client_socket.shutdown(SHUT_RDWR)
            self.client_socket.close()
            print('[Relay Laptop Client] Connection to Ultra96 Server closed')
        except OSError:
            # connection already closed
            print('[Relay Laptop Client] Connection to Ultra96 Server already closed')
            pass
        self.shutdown.set()

    def run(self):
        recv_thread = threading.Thread(target=self.receive_updated_game_state)
        recv_thread.start()
        while not (global_shutdown.is_set() or self.shutdown.is_set()):
            try:
                if not sensor_data_queue_from_beetle.empty():
                    sensor_data_dict = sensor_data_queue_from_beetle.get()

                    if not self.send_sensor_data(sensor_data_dict):
                        self.stop()

            except Exception as e:
                self.stop()
                traceback.print_exc()
                print("[Relay Laptop Client] Error: ", e)

        print("[Relay Laptop Client] Shutdown")
        self.stop()
        recv_thread.join()


if __name__ == '__main__':

    _num_para = 6

    if len(sys.argv) != _num_para:
        print('Invalid number of arguments')
        print('python3 ' + os.path.basename(__file__) +
              ' [Mode] [STU Username] [STU Password] [Ultra96 Port Number] [Player Number]')
        print('Mode                 :  1 for 1-Player Game and 2 for 2-Player Game')
        print('STU Username         :  STU Username eXXXXXXX')
        print('STU Password         :  STU Password')
        print('Ultra96 Port Number  :  Port Number of TCP Server on Ultra96')
        print('Player Number        :  Player Number 1 or 2')

        sys.exit()

    _mode = int(sys.argv[1])

    if _mode == 1:
        print("ONE PLAYER GAME")
        SINGLE_PLAYER_MODE = True
    else:
        print("TWO PLAYER GAME")
        SINGLE_PLAYER_MODE = False

    _stu_username = sys.argv[2]
    _stu_password = sys.argv[3]

    _ultra96_port_num = int(sys.argv[4])
    _player_num = int(sys.argv[5])

    PLAYER = _player_num

    if _player_num == 1:
        BTL_GUN = P1_BTL_GUN
        BTL_VEST = P1_BTL_VEST
        BTL_IMU = P1_BTL_IMU
    elif _player_num == 2:
        BTL_GUN = P2_BTL_GUN
        BTL_VEST = P2_BTL_VEST
        BTL_IMU = P2_BTL_IMU
    else:
        print('Invalid Number of Players')
        sys.exit()

    if _player_num == 1:
        BTL_ADDRLIST = [BTL_GUN, BTL_VEST, BTL_IMU]
        BTL_TYPE = {BTL_GUN: 'G', BTL_VEST: 'V', BTL_IMU: 'M'}
        BTL_RESET_STATUS = {BTL_GUN: False, BTL_VEST: False, BTL_IMU: False}
        BTL_HANDSHAKE_STATUS = {BTL_GUN: False,
                                BTL_VEST: False, BTL_IMU: False}
        ACK_HANDSHAKE_SENT_flag = {
            BTL_GUN: False, BTL_VEST: False, BTL_IMU: False}
        ACK_IR_SENT_flag = {BTL_GUN: False, BTL_VEST: False, BTL_IMU: False}
        sequence_number = {BTL_GUN: 0, BTL_VEST: 0, BTL_IMU: 0}
        prev_sequence_number = {BTL_GUN: 0, BTL_VEST: 0, BTL_IMU: 0}
        COUNT_GOOD_PKT = {BTL_GUN: 0, BTL_VEST: 0, BTL_IMU: 0}
        COUNT_FRAG_PKT = {BTL_GUN: 0, BTL_VEST: 0, BTL_IMU: 0}
        COUNT_DROPPED_PKT = {BTL_GUN: 0, BTL_VEST: 0, BTL_IMU: 0}
    elif _player_num == 2:
        BTL_ADDRLIST = [BTL_VEST]
        BTL_TYPE = {BTL_VEST: 'V'}
        BTL_RESET_STATUS = {BTL_VEST: False}
        BTL_HANDSHAKE_STATUS = {BTL_VEST: False}
        ACK_HANDSHAKE_SENT_flag = {BTL_VEST: False}
        ACK_IR_SENT_flag = {BTL_VEST: False}
        sequence_number = {BTL_VEST: 0}
        prev_sequence_number = {BTL_VEST: 0}
        COUNT_GOOD_PKT = {BTL_VEST: 0}
        COUNT_FRAG_PKT = {BTL_VEST: 0}
        COUNT_DROPPED_PKT = {BTL_VEST: 0}

    beetles = []
    for btl_mac_addr in BTL_ADDRLIST:
        peripheral_beetle = Peripheral(btl_mac_addr)
        peripheral_beetle.withDelegate(NotificationDelegate(btl_mac_addr))
        beetle = BeetleThread(peripheral_beetle)
        beetles.append(beetle)

    relay_laptop_client = RelayLaptopClient(
        _stu_username, _stu_password, _ultra96_port_num, _player_num)

    ready = input("Press Enter when ready to send data:")

    for beetle in beetles:
        beetle.start()

    relay_laptop_client.start()

    try:
        relay_laptop_client.join()
        for beetle in beetles:
            beetle.join()
    except (Exception, KeyboardInterrupt) as e:
        global_shutdown.set()
        traceback.print_exc()
        print("[GLOBAL] Shutting Down")
