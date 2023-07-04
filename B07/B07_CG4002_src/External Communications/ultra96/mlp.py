import pynq.lib.dma
from pynq import allocate, Overlay
import pandas as pd
import numpy as np
import struct
import time

SIZE_INPUT = 30
SIZE_OUTPUT = 5


def init(verbose=0):
    overhead_start = time.time()
    ol = Overlay('design_1.bit')
    if verbose:
        print("Overlay loaded")

    # Initialise DMA
    dma = ol.axi_dma_0  # name of DMA block
    if verbose:
        print("dma initialised")

    overhead_end = time.time()
    if verbose:
        print("Overhead time taken:", overhead_end - overhead_start)
    return ol, dma

def predict(input_data, ol, dma, verbose=0):
    input_buffer = allocate(shape=(SIZE_INPUT,), dtype=np.int32)
    output_buffer = allocate(shape=(SIZE_OUTPUT,), dtype=np.int32)
    if verbose:
        print("buffers allocated")


    # test_data = np.asarray([-27.11265089990918, -4.8628507292813925, -84.33640165919502, -30.8771485748684, -13.019309690160489, -73.676549012633, -30.8771485748684, -13.019309690160489, -73.676549012633, -35.3659915884345, 3.869534323888661, -84.50262842392594, -31.45451187968462, 5.036785582281899, -83.62811886670274, -
    #                     22.725819846164946, -20.93406464353585, -66.82950139728165, -44.06798253418479, -3.136971368545526, -77.4077342657374, -44.06798253418479, -3.136971368545526, -77.4077342657374, -44.97577145716273, -0.509935760161586, -77.4970273996245, -32.77018538153825, 7.904743257526901, -79.64702183799949], dtype=np.float32)

    test_size = len(input_data)
    flattened_data = input_data.flatten()

    for i in range(test_size):
        input_buffer[i] = struct.unpack(
            'i', struct.pack('f', flattened_data[i]))[0]
    if verbose:
        print(input_buffer)
        print("data processed")

    output_buffer[1] = 1

    transfer_start = time.time()
    dma.sendchannel.transfer(input_buffer)
    if verbose:
        print("Send channel command")
    dma.recvchannel.transfer(output_buffer)
    if verbose:
        print("Receive channel command")
    dma.sendchannel.wait()
    if verbose:
        print("Send channel wait done")
    dma.recvchannel.wait()
    transfer_end = time.time()
    if verbose:
        print("Output is", output_buffer)
        print("Transfer time taken:", transfer_end - transfer_start)

    final_output = [0, 0, 0, 0, 0]
    for i in range(SIZE_OUTPUT):
        final_output[i] = struct.unpack('f', struct.pack('i', output_buffer[i]))[0]

    print(final_output)
    return final_output
