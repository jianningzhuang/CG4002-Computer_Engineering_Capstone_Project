import sshtunnel

def start_tunnel():

        # open tunnel to stu
        tunnel1 = sshtunnel.open_tunnel(
            ssh_address_or_host = ('stu.comp.nus.edu.sg', 22),
            remote_bind_address = ('192.168.95.220', 22),
            ssh_username = 'e0527277',
            ssh_password = '',
            #local_bind_address = ('127.0.0.1', 8889),
            #block_on_close = False
            )

        tunnel1.start()

        print('[Tunnel Opened] Tunnel into stu: ' + str(tunnel1.local_bind_port))

        # sshtunneling into ultra96
        tunnel2 = sshtunnel.open_tunnel(
            ssh_address_or_host = ('localhost', tunnel1.local_bind_port),
            remote_bind_address=('127.0.0.1', 8886),
            ssh_username = 'xilinx',
            ssh_password = 'xilinx',
            local_bind_address = ('127.0.0.1', 8886), #localhost to bind it to
            #block_on_close = False
            )

        tunnel2.start()

        print('[Tunnel Opened] Tunnel into Xilinx')
        
        return tunnel2.local_bind_address



print(start_tunnel())