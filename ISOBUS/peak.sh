sudo ip link set can0 down
sudo ip link set can0 name vcan0
sudo ip link set vcan0 up type can bitrate 250000 restart-ms 100

