README

1. Profs run eval_server.py, tell us Eval Server IP and Port Number
2. We run Ultra96_2_Player.py with Eval Server IP and Port Number
3. We run RelayLaptop_2_Player.py, don't press enter yet
4. Input SECRET KEY on eval_server
5. Players start Laser Tag Game


Ultra96

ssh -X xilinx@192.168.95.220
whoneedsvisualizer

sudo -i
whoneedsvisualizer

cd ..
cd home
cd xilinx
cd ultra96

python3 Ultra96_2_Player.py [Eval Server IP] [Eval Server Port] [Laptop 1 Port] [Laptop 2 Port] [Secret Key]
python3 Ultra96_2_Player.py 127.0.0.1 12345 8888 8889 JIANNINGJIANNING

Relay Laptop

python3 RelayLaptop_2_Player.py [STU Username] [STU Password] [Ultra96 Port Number] [Player Number]
P1: python3 RelayLaptop_2_Player.py e0527277 p5hrNIpu@3223 8888 1
P2: python3 RelayLaptop_2_Player.py e0527277 p5hrNIpu@3223 8889 2

eval_server

ssh -X xilinx@192.168.95.220
whoneedsvisualizer

cd eval_server

python3 eval_server.py [Port Num] [Grp Num] [Mode]
python3 eval_server.py 12345 7 2