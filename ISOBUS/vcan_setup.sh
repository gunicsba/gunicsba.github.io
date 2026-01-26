#!/bin/bash

ip link add dev vcan0 type vcan
ip link set vcan0 mtu 16
ip link set up vcan0
tc qdisc add dev vcan0 root tbf rate 300kbit latency 100ms burst 1000


sudo ip link set can0 down
sudo ip link set can0 name vcan0
tc qdisc add dev vcan0 root tbf rate 300kbit latency 100ms burst 1000

sudo ip link set vcan0 up type can bitrate 250000 restart-ms 100


expected sequential data frame