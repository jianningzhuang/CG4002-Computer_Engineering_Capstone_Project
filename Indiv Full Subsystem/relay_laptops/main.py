import struct
import concurrent.futures
from bluepy.btle import DefaultDelegate, Peripheral, BTLEDisconnectError
# from crccheck.crc import Crc8

SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"
PLAYER = '1'
# PLAYER = '2'

# MAC ADDRESSES
# BTL1 = D0:39:72:BF:BF:A4
# BTL2 = D0:39:72:BF:CA:94
# BTL3 = D0:39:72:BF:C1:D9

BTL2 = "D0:39:72:BF:C1:E4"
BTL1 = "D0:39:72:BF:CD:17"
BTL3 = 'D0:39:72:BF:C8:CE'  # MPU

BTL_ADDRLIST = [BTL1, BTL2, BTL3]

BTL_TYPE = {BTL1: 'G', BTL2: 'V', BTL3: 'M'}

BTL_RESET_STATUS = {BTL1: False, BTL2: False, BTL3: False}

BTL_HANDSHAKE_STATUS = {BTL1: False, BTL2: False, BTL3: False}

ACK_HANDSHAKE_SENT_flag = {BTL1: False, BTL2: False, BTL3: False}

ACK_IR_SENT_flag = {BTL1: False, BTL2: False, BTL3: False}

COUNT_FRAG_PKT = {BTL1: 0, BTL2: 0, BTL3: 0}

COUNT_DROPPED_PKT = {BTL1: 0, BTL2: 0, BTL3: 0}


class NotificationDelegate(DefaultDelegate):
    # Initialises delegate object and message buffer for each Beetle
    def __init__(self, mac_address):
        DefaultDelegate.__init__(self)
        self.macAddress = mac_address
        self.buffer = b''  # specifies string as byte literal
        ACK_HANDSHAKE_SENT_flag[self.macAddress] = False
        ACK_IR_SENT_flag[self.macAddress] = False

    def handleNotification(self, cHandle, raw_packet):
        self.buffer += raw_packet
        if len(self.buffer) < 20:
            COUNT_FRAG_PKT[self.macAddress] += 1
            print('PKT FRAGMENTED:', COUNT_FRAG_PKT)

        else:
            # send non-fragmented (full) packet for processing
            self.manage_packet_data(self.buffer)
            # clear buffer to prepare for next packet
            self.buffer = self.buffer[20:]

    # def crcCheck(self, raw_packet):
    #     checksum = Crc8.calc(raw_packet[0:19])
    #     if checksum == raw_packet[19]:
    #         return True
    #     return False

    def doChecksum(self, raw_packet):
        checksum = 0
        for i in range(19):
            checksum = (checksum ^ raw_packet[i]) & 0xFF
        if checksum == raw_packet[19]:
            return True
        else:
            return False

    def manage_packet_data(self, raw_packet):
        # check packet length, strictly 20 bytes
        if len(raw_packet) < 20:
            return
        # check for packet corruption
        if not self.doChecksum(raw_packet):
            # drop corrupted packet
            COUNT_DROPPED_PKT[self.macAddress] += 1
            print(raw_packet)
            print('PKT checksum failed, dropped!:', COUNT_DROPPED_PKT)
            return
        try:
            # packet type is 'A': BTL sends ACK to laptop
            if raw_packet[0] == 65:
                BTL_HANDSHAKE_STATUS[self.macAddress] = True
                ACK_HANDSHAKE_SENT_flag[self.macAddress] = True
                message = [BTL_TYPE[self.macAddress] + PLAYER, "BTL->LAPTOP ACK received"]
                print(message)

            # packet is NOT ACK from BTL ie. handshake done, ready for data
            elif BTL_HANDSHAKE_STATUS[self.macAddress]:

                # packet type is 'G' for gunshot (IR transmitted) or 'V' for vest (IR received)
                if raw_packet[0] == 71 or raw_packet[0] == 86:
                    self.process_IR_data(raw_packet)

                # packet type is 'M' for motion: MPU data
                elif raw_packet[0] == 77:
                    self.process_motion_data(raw_packet)

                else:
                    COUNT_DROPPED_PKT[self.macAddress] += 1
                    print('DROPPED PKTS:', COUNT_DROPPED_PKT)

            else:  # reset BTL if packet is neither ACK or sensor data, corrupted
                COUNT_DROPPED_PKT[self.macAddress] += 1
                print('DROPPED PKTS:', COUNT_DROPPED_PKT)
                BTL_RESET_STATUS[self.macAddress] = True

        except Exception as e:
            print("manage_packet_data exception: ", e)

    def process_IR_data(self, raw_packet):
        return

    def process_motion_data(self, raw_packet):
        return


class BeetleThread:
    def __init__(self, peripheral_obj_beetle):
        self.peripheral_obj_beetle = peripheral_obj_beetle
        self.serial_service = self.peripheral_obj_beetle.getServiceByUUID(SERVICE_UUID)
        self.serial_chars = self.serial_service.getCharacteristics()[0]
        self.initiate_handshake()

    def connect(self):
        BTL_HANDSHAKE_STATUS[self.peripheral_obj_beetle.addr] = False
        message = [BTL_TYPE[self.peripheral_obj_beetle.addr] + PLAYER, 'attempting connection...']
        print(message)
        try:
            self.peripheral_obj_beetle.disconnect()
            self.peripheral_obj_beetle.connect(self.peripheral_obj_beetle.addr)
            self.peripheral_obj_beetle.withDelegate(NotificationDelegate(self.peripheral_obj_beetle.addr))
            print('connection successful to:', self.peripheral_obj_beetle.addr)
        except Exception:
            print('connection unsuccessful to:', self.peripheral_obj_beetle.addr)
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
                message = [BTL_TYPE[self.peripheral_obj_beetle.addr] + PLAYER, 'LAPTOP->BTL H sent']
                print(message)
                padding = (0,) * 19
                packetFormat = 'c' + 19 * 'B'  # 1 char & 19 unsigned char
                handshakeByte = bytes('H', 'utf-8')
                packet1 = struct.pack(packetFormat, handshakeByte, *padding)
                timeout_count += 1
                self.serial_chars.write(packet1, withResponse=False)
                print("H #{} sent to:".format(timeout_count), self.peripheral_obj_beetle.addr)

                if timeout_count % 5 == 0:
                    print("5 HANDSHAKES SENT. TIMEOUT & RESET BTL")
                    timeout_count = 0
                    # reconnect BTL
                    self.reset()

                # if ACK packet received from BTL, return ACK packet to BTL
                if self.peripheral_obj_beetle.waitForNotifications(5.0):
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
                    padding = (0,) * 19
                    packetFormat = 'c' + 19 * 'B'
                    ackByte = bytes('A', 'utf-8')
                    packet3 = struct.pack(packetFormat, ackByte, *padding)
                    if ACK_IR_SENT_flag[self.peripheral_obj_beetle.addr]:
                        self.serial_chars.write(packet3, withResponse=False)
                        ACK_IR_SENT_flag[self.peripheral_obj_beetle.addr] = False

            self.connect()
            self.initiate_handshake()
            self.run()

        except Exception as e:
            print(e, ":", self.peripheral_obj_beetle.addr)
            self.connect()
            self.initiate_handshake()
            self.run()


if __name__ == '__main__':
    # beetles = []
    # for btl_mac_addr in BTL_ADDRLIST:
    #     # creates Peripheral object and makes connection to device (address declared)
    #     peripheral_beetle = Peripheral(btl_mac_addr)
    #     # stores reference to Delegate object
    #     peripheral_beetle.withDelegate(NotificationDelegate(btl_mac_addr))
    #     beetle = BeetleThread(peripheral_beetle)
    #     beetles.append(beetle)
    #
    # with concurrent.futures.ThreadPoolExecutor() as executor:
    #      for btl in beetles:
    #          thread = executor.submit(btl.run)

    peripheral_beetle = Peripheral(BTL1)
    peripheral_beetle.withDelegate(NotificationDelegate(BTL1))
    beetle = BeetleThread(peripheral_beetle)
    with concurrent.futures.ThreadPoolExecutor() as executor:
      thread = executor.submit(beetle.run)
