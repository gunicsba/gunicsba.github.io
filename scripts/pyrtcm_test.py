#!/usr/bin/env python

import socket
import base64
import sys
from pyrtcm import RTCMReader
import argparse


parser = argparse.ArgumentParser(description="Parse command line parameters")
parser.add_argument('-n', '--name', type=str, help="Base Name", required=True)

bs = "bs1"
args = parser.parse_args()

#pridal som sem comment

# Definition of one or multiple NTRIP base stations
if bs=="bs1":
    server = "147.100.179.214"
    port = "2101"
    mountpoint = args.name
    username = "uname"
    password = "passw"

def getHTTPBasicAuthString(username,password):
    inputstring = username + ':' + password
    pwd_bytes = base64.encodebytes(inputstring.encode("utf-8"))
    pwd = pwd_bytes.decode("utf-8").replace('\n','')
    return pwd

def is_ecef_in_hungary(x, y, z):
    """
    Check if the ECEF coordinates are within Hungary's bounding box.
    """
    #print(f"RTCM 1005 - ECEF Coordinates for {mountpoint}: X={ecef_x}, Y={ecef_y}, Z={ecef_z}")
    return (3892460 <= x <= 4283409 and
            1172136 <= y <= 1737684 )

pwd = getHTTPBasicAuthString(username,password)

header =\
"GET /{} HTTP/1.0\r\n".format(mountpoint) +\
"User-Agent: NTRIP u-blox\r\n" +\
"Accept: */*\r\n" +\
"Authorization: Basic {}\r\n".format(pwd) +\
"Connection: close\r\n\r\n"

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((server,int(port)))
s.sendto(header.encode('utf-8'),(server,int(port)))
resp = s.recv(1024)

if resp.startswith(b"STREAMTABLE"):
    print("Invalid or No Mountpoint")
    exit()
#elif not resp.startswith(b"HTTP/1.1 200 OK"):
    #print("All good")

try:
    while True:
        # There are some length bytes at the head here but it actually
        # seems more robust to simply let the higher level RTCMv3 parser
        # frame everything itself and bin the garbage as required.

        #length = s.recv(4)

        #try:
        #    length = int(length.strip(), 16)
        #except ValueError:
        #    continue
        
        #data = s.recv(1024)
        #print(data)
        rtcm_reader = RTCMReader(s)
        messages_to_skip = { 1230, 1046,1004,1005,1008,1107, 1042, 1012, 1077, 1087, 1097, 1127 }
        messages_to_keep = { 1005, 1006}

        for raw_data, parsed_data in rtcm_reader:
          message_type = int(str(parsed_data).split('(')[1].split(',')[0])

          if message_type not in messages_to_keep:
            continue
          #print("RTCM:", message_type)
          #print("Parsed RTCM message:", parsed_data)

          ecef_x = parsed_data.DF025
          ecef_y = parsed_data.DF026
          ecef_z = parsed_data.DF027
          if is_ecef_in_hungary(ecef_x, ecef_y, ecef_z):
            print(f"The base station is in Hungary. {mountpoint}")
            exit()
          else:
            print(f"The base station is elsewhere. {mountpoint}")
#            print("The base station is not in Hungary. x ", ecef_x, " y " , ecef_y, " z ", ecef_z)
            exit()

        if not data:
            exit()
        
        #ret = ser.write(data)
        #print(ret)
        #print >>sys.stderr, [ord(d) for d in data]
        sys.stdout.flush()

finally:
    s.close()